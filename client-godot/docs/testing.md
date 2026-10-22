# 测试、质量门禁与验证边界

从仓库根运行。使用 `dependencies.lock.json` 中锁定的 Godot 4.7.1 Windows x64；控制台启动器必须有配套 GUI 可执行文件，不能以文件名或空日志认定成功。官方脚本检查引擎版本与 SHA-256，并隔离用户数据。

## 独立 Python 环境

```powershell
python -m venv client-godot/artifacts/test-env
New-Item -ItemType File -Force client-godot/artifacts/test-env/.gdignore | Out-Null
$python = (Resolve-Path client-godot/artifacts/test-env/Scripts/python.exe).Path
& $python -m pip install -r client-godot/tests/requirements-complexity.txt -r client-godot/tests/requirements-features.txt -r client-godot/tests/requirements-visual.txt
$engine = '<锁定 Godot exe 的绝对路径>'
```

安装仅用于测试，不进入客户端运行依赖。检查入口不自动安装包。复杂度解析依赖固定版本，网络/功能/视觉依赖分别沿用现有 requirements；不放宽版本以得到通过。

## 四组正式入口

```powershell
& ./client-godot/scripts/check.ps1 -Godot $engine -Python $python
& ./client-godot/scripts/check_accounts.ps1 -Godot $engine -Python $python
& ./client-godot/scripts/check_network.ps1 -Godot $engine -Python $python
& ./client-godot/scripts/check_features.ps1 -Godot $engine -Python $python
```

基础入口默认在导入后、行为检查前执行强制复杂度门禁。`-Python` 默认 `python`；`-SkipImport` 仍执行门禁，只有 `-ImportOnly` 仅导入、不依赖 Python。CC=10 合法，CC>10、解析失败、缺依赖和版本不符均使入口非零退出。覆盖模式以检查器为准，排除第三方、生成物和二进制。

runner 使用本地 HTTP/WebSocket 夹具和独立 APPDATA，不访问公共账户或付费模型。失败不能删断言、跳过场景或只改文档称通过。完整运行必须核对中止位置，不能将中止后未执行的检查计为通过。

## 回复事件样例

唯一回归样例为 `tests/fixtures/chat/reply_events.json`。由已知可用历史提交恢复的 9 个事件原样迁入客户端，运行器同时交给 Godot 收包链路与旧 Python 客户端 `client/src/network/event_types.py` 真实解析器。无需恢复根目录 contracts 或修改旧端代码；该文件是测试数据，不是新增的服务端协议定义。

基础入口还执行 `tests/session/test_reply_audio_errors.gd`，用合成 WAV 重现诊断包的 32 kHz、28,800 帧及 49,152/8,492 字节两段接收后失败尾包。覆盖排队和播放中失败、无音频失败、本地解码失败、重复终包、恰好一次提醒、真实后续播放、失败缓存中止和日志白名单。测试不使用用户音频，也不把服务端 TTS 的内部原因判为已修复。

## 独立检查

```powershell
& $python client-godot/tests/test_dependency_boundaries.py
& $python client-godot/scripts/check_complexity.py
& $python client-godot/tests/test_complexity_check.py
& $python client-godot/tests/test_check_gate.py
& $python client-godot/tests/test_review_documentation.py
& $python client-godot/tests/test_build_prompt.py
```

门禁编排测试使用临时工程和模拟引擎，覆盖成功、非零、缺依赖、默认 Python、SkipImport 和 ImportOnly，不代替真实引擎检查。文档测试核对自有现行入口、本地链接、版本配置、固定夹具与 `.import` 的 LF 属性；第三方 NOTICE 原文不纳入自有文档改写。

## 图形与冷缓存

```powershell
& $python client-godot/tests/run_dynamics_tests.py --godot $engine --script res://tests/test_dynamics_detail.gd --gpu
& $python client-godot/tests/run_dynamics_tests.py --godot $engine --script res://tests/ui/test_dynamics_reading_position.gd --gpu
& $python client-godot/tests/run_dynamics_tests.py --godot $engine --script res://tests/ui/test_dynamics_review_actions.gd --gpu
```

阅读位置专项覆盖两主题及 1100×800/960×640，不使用固定睡眠当作请求完成判据；必须先确认加载状态及真实可滚动范围。卡片点击专项抓取真实 Godot 节点截图，不能以 HTML 或另绘的 mock 证明产品布局。

冷缓存验收使用不含 `.godot` 的独立项目副本，不删除用户编辑器缓存；热缓存再次执行原工程基础入口。导入瞬态重试仅允许官方入口已有的主题纹理生成竞态，其他错误仍失败。记录完整日志、退出码、通过/跳过情况及工作树基线。真实系统 DPI、多屏、Windows 10、集显、公共服务和长期性能不属于这些本地测试证据。
