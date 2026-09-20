# AgentLuo · Godot Windows 客户端

功能基线：`79ae2c0`。当前为独立开发工程，实际完成范围见 [进度](../docs/开发进程文档/开发进度/Godot-Windows客户端.md)。尚未替换旧端，不读取旧端凭据。

## 构建

使用 Godot **4.7.1 standard / Windows x64**。通过 Godot 的 Manage Export Templates 安装同版本模板，或将锁定模板包中的 Windows x64 文件和 version.txt 放入 `%APPDATA%/Godot/export_templates/4.7.1.stable/`。依赖来源和 SHA-256 见 `dependencies.lock.json`。

```powershell
$env:GODOT_BIN = 'D:\godot\Godot_v4.7.1-stable_win64.exe\Godot_v4.7.1-stable_win64_console.exe'
powershell -NoProfile -ExecutionPolicy Bypass -File client_godot/scripts/check.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File client_godot/scripts/build.ps1
```

也可以显式传入 `-Godot <exe>`。构建脚本不下载依赖、不连接服务端；失败返回非零并保留 `artifacts/` 中的日志。输出 `dist/agentluo-<version>/` 整个目录（EXE、PCK、插件 DLL 和 licenses）必须一起分发。headless 启动检查不代表视觉、GPU 或真机验收。

开发时在 Godot 中导入 `project.godot`。本地数据使用独立的 `%APPDATA%/AgentLuo-Godot`，不写入安装目录。

## Live2D 构建

工程附带锁定的 Windows x64 插件二进制和 shader。重建时检出 lock 中的 gd_cubism commit 及其 godot-cpp submodule，按上游文档将 Cubism SDK 5-r.1 放入插件源码 `thirdparty/`，使用 VS2022 C++ Build Tools、Python 3.11.9 和 SCons 4.7.0：

```powershell
python client_godot/scripts/build_cubism.py --source '<gd_cubism源码目录>'
```

脚本检查源码版本，在当前进程处理 Windows OEM 编码兼容问题，输出二进制 SHA-256；重建工具链变化时应复验并更新 lock，不能无声替换。许可和素材来源见 `licenses/`。

独立模型场景：`res://scenes/avatar/avatar_preview.tscn`。当前主入口显示真实账户表单；传入 `-- --preview` 才加载独立离线样板 `res://scenes/preview/chat_preview.tscn`。Godot 4.7.1 官方 release 模板禁止命令行覆盖主场景，验证不得依赖该能力。

## 体验离线样板

运行 `dist/agentluo-<version>/agentluo.exe -- --preview`。角色区滚轮缩放、右键拖动，底部按钮重置；中间分隔条调整宽度，以上设置会保存。左上切换真实模型表情；右上切换日常聊天、空白、断网、加载失败和思考状态。

聊天文本可选择复制；Enter 本地模拟发送，Shift+Enter 换行。图片按钮或 Ctrl+V 粘贴图片先打开预览，点击发送才追加演示消息；缩略图可再次打开。查看旧消息时发送不会强制滚到底部，使用“回到最新”。模拟口型按钮没有声音；样板不连接真实账户、消息或音频服务。

`check.ps1` 覆盖角色、构图、离线消息控制器和主场景键盘输入回归。真实 Windows IME、剪贴板、多档 DPI、拖动手感和集显性能尚需人工验收。此导出目录是视觉检查产物，不是最终安装程序。

截取账户页：`agentluo.exe -- --capture=<绝对PNG路径>`；截取样板增加 `--preview`，可再增加 `--scenario=empty/disconnected/error/thinking`。截图和 headless 检查不会自动登录真实账户。

## Windows 凭据扩展

`WindowsSecurity` 使用 CNG RSA-OAEP/SHA256 和当前用户 DPAPI。源码位于 `native/`，不需要额外运行时 DLL；编译使用上述锁定 godot-cpp 和 VS2022 工具链。

```powershell
python client_godot/scripts/build_security.py --godot-cpp '<锁定的godot-cpp目录>'
python client_godot/tests/run_security_interop.py --godot $env:GODOT_BIN
```

互操作测试 Python 需 `cryptography` 和 `fastapi`，仅测试时需要；测试隔离执行仓库 account.py 中原样的密钥生成/解密函数，避免其数据库及供应商导入副作用。它不验证整个 HTTP 服务。

若 MSVC 响应文件不能解析源码目录中的中文，可以 `New-Item -ItemType Junction -Path client_godot/native/godot-cpp -Value '<真实目录>'` 建立本地目录联接，然后以该联接路径传入 `--godot-cpp`。构建仍检查源码 commit；联接和对象文件不进入 Git 或导出包。

账户模块的本地 HTTP/凭据回归：在独立 Python 环境安装 `tests/requirements-auth.txt`，运行 `scripts/check_accounts.ps1 -Godot <exe> -Python <python.exe>`。测试只监听 127.0.0.1 随机端口，使用合成账户；客户端运行不依赖 Python。

聊天传输与界面回归：测试 Python 安装 `tests/requirements-websocket.txt`，运行 `scripts/check_network.ps1 -Godot <exe> -Python <python.exe>`。真实 Godot WebSocketPeer 连接随机端口的本地 fixture，覆盖认证、心跳、断线和稳定 ID 重试、真实输入框收发和退出清理；不连接真实账户服务器。`contracts/chat/reply_events.json` 由 Godot 收包链路与旧 Python 客户端实际解析器共同消费。

默认入口登录后进入真实文字聊天，图片、历史、语音等以进度文档中的实际完成范围为准；离线样板中的模拟能力不代表正式功能已经接入。

## 回复语音与诊断

正式聊天自动播放服务端 WAV/PCM 分片；同 UUID 聚合，后续回复等前一句实际播完再呈现。支持口型、音量保存、停止当前语音、错误及断线清理；完整语音以临时文件接收、成功终止及原生验证后提交，提供消息重放/暂停/继续/停止，波形来自原生 RMS，进度来自混音器消耗帧。在线语音抢占重放；停止在线声音不取消后续接收和缓存。原生 `PcmStreamDecoder` 与 `WindowsSecurity` 共用 DLL，按上面的 `build_security.py` 命令重建，需分发完整目录。

登录前按钮或左侧“日志”打开独立终端窗口，默认实际目录 `%APPDATA%/AgentLuo-Godot/logs`；每次启动独立 JSONL/元数据，保留最近50次并保护仍运行实例，当前启动不截断。可搜索、筛选、复制与导出完整脱敏诊断 ZIP，不上传。用哈希 reply_id 关联 `reply_received → audio_received → audio_format/audio_decoded → audio_receive_finished → audio_playback_started/finished`（接收/播放可交错）。`audio_error` 的 code 定位错误，`audio_underrun` 记录供给不足；不会写入正文、token、密钥或 Base64。

`check.ps1` 增量解码及真实混音测试默认使用合成音频；`check_network.ps1` 还验证 loopback WebSocket 到播放器链路、顺序、隐藏音频、停止及断线。Windows 输出驱动验证可运行：

```powershell
& $env:GODOT_BIN --headless --audio-driver WASAPI --verbose --path client_godot --script res://tests/test_reply_audio.gd
```

该命令会向本机默认音频设备播放短合成音；AudioEffectCapture 检查非零混音输出及静音，不等同人工听感或真实服务验收。

未登录时仅显示 660×800 账户窗口，登录成功后展开角色和聊天，退出再收起。默认服务器沿用旧端 release_config.base_url；已保存的自定义地址优先。账户回归含窗口切换测试，原生窗口验证可运行 `run_account_tests.py --godot <exe> --script res://tests/test_application_window.gd --gpu`，仍仅连接本地 HTTP fixture。

语音缓存在 user://audio 按规范化服务器、账户与 UUID 隔离，退出及重启保留，只能手动清理，无自动容量/时间淘汰。设置中的“语音缓存”有确认窗口；清理同时取消在途流的缓存写入，保留正在输出的声音与聊天文字。登录后全量同步历史，按 UUID 恢复新端本账号完整缓存的重放入口；不导入旧端缓存。日志记录 cache_committed/cache_error、replay_started/paused/resumed/stopped/finished/preempted，不写音频原文。

重放回归：`--headless --audio-driver WASAPI --path client_godot --script res://tests/test_voice_replay.gd`。真实 UI/角色截图：`tests/run_websocket_tests.py --godot <exe> --script res://tests/capture_voice_ui.gd --gpu`，只连接 loopback、使用合成语音，输出默认/最小/暂停/125%及150%内容缩放截图到 artifacts。内容缩放检查不能替代操作系统 DPI 切换与跨显示器验收。

## agentluo 版本化交付与功能验证

release.json 是版本单一来源，界面/诊断/目录/ZIP 使用同一版本。`scripts/build.ps1 -Package` 导出 `dist/agentluo-<version>/agentluo.exe` 并生成 `artifacts/agentluo-<version>.zip`；存在同名交付 ZIP 时拒绝覆盖。重建不自动升级版本。保留旧包作为回退，数据仍在 AgentLuo-Godot。

历史、相处模式、模型配置/委托及动态回归：`scripts/check_features.ps1 -Godot <exe> -Python <python.exe>`。测试依赖另包括 aiohttp；所有默认 fixture 仅监听 loopback，无公共服务写入或收费供应商。新增界面 GPU 截图：`tests/run_feature_tests.py --godot <exe> --script res://tests/capture_release_ui.gd --gpu`。

应用持有聊天/模型/动态控制器，Window 仅展示和编辑；未来页面切换不重连。角色入口 `assets/live2d/character.json` 分离身份与模型资源，加载失败保留原模型；实际平台能力仍是 Windows。详细使用说明见 PREVIEW.md，实际验收记录见开发进度，不将预留移动端/换装/箱庭视为已交付。

当前开发版的动态为独立任务栏窗口，45:55列表/详情分区，完整正文、平铺私人评论、行内回复和内嵌发布浮层；关闭聚合检查所有草稿。正式下拉共享稳定ID组件。原生验收：`tests/run_dynamics_tests.py --godot <exe> --gpu --script res://tests/capture_dynamics_ui.gd`；菜单GPU验收：Godot `--path client_godot --script res://tests/capture_dropdown_ui.gd`。这些测试验证真实HWND、缩放截图和本地接口，不验证公共服务或系统DPI切换。


## 窗口重设计（当前开发分支）

所有可见UI由Godot控件场景绘制，脚本只做行为和数据绑定，包括确认按钮和24段语音波形；桌面窗框与三键使用系统原生实现。左侧导航集中聊天、动态、统一设置、日志、账号；设置保存全部修改，失败项留稿。主窗退出统一检查聊天/设置/动态草稿，不自动保存或发送。动态和日志独立于主窗最小化，设置跟随主窗；全局图片窗跟随当前来源。几何持久化但文字草稿只保留到本次运行结束。

契约见[窗口重设计接口](../docs/项目说明/项目架构与接口（spec）/接口文档/client_godot/window-redesign.md)，实际验证见[窗口重设计进度](../docs/开发进程文档/开发进度/Godot客户端窗口重设计.md)。用户反馈后恢复系统标题栏、拖拽/缩放，内部下拉采用Godot圆角控件；背景磨砂仅采样应用自己的画面，正文实底，日志内容区深色。系统文件选择器继续使用原生控件。

原生鼠标/键盘验收（会操作其创建的测试窗口）：

```powershell
$env:GODOT_TEST_PYTHON = 'D:\anaconda\python.exe'
& $env:GODOT_BIN --path client_godot --script res://tests/ui/test_native_window_controls.gd
```

`capture_release_ui.gd` 另生成主界面、最小尺寸、125/150/200%内容缩放、设置与日志截图，比较磨砂/实底的短时帧间隔，并用真实HWND核查动态/日志独立、设置跟随主窗。结果在artifacts，不等同系统DPI、多屏、Windows10或集显认证。版本仍由release.json决定，本轮源代码变更不自动覆盖已有发布包。

设置最小尺寸的可见滚动验收：Godot `--path client_godot --script res://tests/ui/test_settings_layout.gd`，需要真实图形会话；验证720×640下表单底部可滚动到达且不覆盖保存/关闭栏。该测试不在headless检查中运行。
