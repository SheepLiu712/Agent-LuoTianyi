# Godot 测试入口

测试使用锁定的 Godot 4.7.1 和独立的 Python 环境。默认分为 `check`、`accounts`、`network`、`features` 四组，另有需要真实图形会话的 GPU 与原生窗口验收。测试不会连接公共服务器，也不读取本机真实账号。

## 准备

1. 安装 Godot 4.7.1 standard。脚本会校验 `--version` 输出和可执行文件 SHA-256，版本不符会直接失败。
2. 为测试创建独立 Python 环境，按需要的组安装依赖：
   - `tests/requirements-auth.txt`：账号组、原生加密互操作
   - `tests/requirements-websocket.txt`：网络组
   - `tests/requirements-features.txt`：功能组
   - `tests/requirements-visual.txt`：GPU 截图
   - `tests/requirements-complexity.txt`：复杂度检查
3. 首次使用新检出的代码时，先让 Godot 完成资源导入。

账号、网络、历史、动态和功能 runner 都会为 Godot 进程创建一次性的 `APPDATA` 和 `LOCALAPPDATA`，结束后删除；`run_security_interop.py` 使用临时目录保存互操作输入。测试结果必须同时满足：退出码为 0、输出包含 `: PASS`、不包含 `FAIL:` 或错误标记。不能只根据生成的截图判断通过。

## 默认回归

在 `client-godot` 目录运行：

```powershell
$engine = '<Godot 4.7.1 可执行文件>'
$python = '<已安装测试依赖的 python.exe>'

.\scripts\check.ps1 -Godot $engine -Python $python
.\scripts\check_accounts.ps1 -Godot $engine -Python $python
.\scripts\check_network.ps1 -Godot $engine -Python $python
.\scripts\check_features.ps1 -Godot $engine -Python $python
```

| 分组 | 内容 |
| --- | --- |
| `check` | 首次资源导入、圈复杂度检查、启动检查、主题与界面、角色、离线预览、TLS、音频、日志、历史、存储和设置等模块测试 |
| `accounts` | 原生加密互操作、账号协议、登录状态、账户页、窗口切换、登录界面和依赖边界 |
| `network` | WebSocket 传输、真实聊天、语音聊天和角色触摸上报 |
| `features` | 历史同步与图片、设置、模型、动态和扩展接口 |

`check.ps1` 的参数：

- `-ImportOnly`：只执行首次导入，不运行复杂度和行为检查。
- `-SkipImport`：跳过导入，直接执行复杂度和行为检查。
- `-Python <python.exe>`：指定复杂度检查使用的 Python，默认 `python`。

`check_features.ps1` 的 `-TimeoutSeconds` 只覆盖 `run_feature_tests.py` 的单个用例超时；历史、网络、账号和动态 runner 使用各自的固定超时。`run_feature_tests.py` 默认为普通用例 60 秒、整应用慢用例 180 秒，GPU 模式至少 180 秒。

导入失败、复杂度超限、Godot 进程非零退出、超时或输出出现 `SCRIPT ERROR:`、`Parse Error:`、`FAIL:` 都会使对应入口失败。脚本不会自动安装依赖或跳过失败项。

## 单独运行

Python runner 的通用参数：

```powershell
python .\tests\run_feature_tests.py --godot $engine --script res://tests/test_preferences.gd
python .\tests\run_account_tests.py --godot $engine --script res://tests/test_account_api.gd
python .\tests\run_websocket_tests.py --godot $engine --script res://tests/test_websocket_transport.gd
python .\tests\run_history_tests.py --godot $engine --script res://tests/test_history_sync.gd
python .\tests\run_dynamics_tests.py --godot $engine --script res://tests/test_dynamics.gd
```

- `--script` 指定 `res://tests/` 下的测试脚本。
- `--gpu` 使用原生窗口运行，适用于截图和布局检查。
- `run_feature_tests.py` 还支持 `--timeout <秒>`。
- `run_security_interop.py` 只接受 `--godot`。

各 runner 的固定超时：

| runner | 超时 |
| --- | --- |
| `run_account_tests.py` | 40 秒 |
| `run_websocket_tests.py` | 45 秒 |
| `run_history_tests.py` | 40 秒 |
| `run_dynamics_tests.py` | 60 秒 |
| `run_feature_tests.py` | 普通用例 60 秒，整应用慢用例 180 秒；GPU 模式至少 180 秒 |

也可以直接用 Godot 运行不依赖本地 HTTP/WebSocket 服务的测试：

```powershell
& $engine --headless --path . --script res://tests/test_ui_scenes.gd
```

## GPU 与原生窗口验收

下表包含 GPU、原生窗口和可 headless 的定向测试。标注 `--gpu` 或“不加 `--headless`”的条目必须在真实图形会话中运行；涉及截图、真实窗口和布局像素的检查不能用 headless 结果代替。界面缩放截图也不等于操作系统 DPI 切换。

| 脚本（相对 `tests/`） | 启动方式 | 验证内容 |
| --- | --- | --- |
| `ui/test_settings_control_states.gd` | `run_feature_tests.py --gpu` | 设置读取失败、重试、保存、开关状态、默认/最小尺寸和 100/125/150/200% 界面缩放 |
| `ui/test_settings_export_layout.gd` | 直接 Godot，或对导出的 PCK 运行 | 默认/最小尺寸、五个设置页面、左栏滚动、缓存页换行、退出登录按钮与侧栏位置一致 |
| `ui/test_settings_page_transition.gd` | 直接 Godot，可 headless 或 GPU | 五个页面共用滚动容器、点击标签滚动、滚轮联动选中态 |
| `ui/test_cache_usage_ring.gd` | 直接 Godot，可 headless 或 GPU | 未扫描不读盘、首次扫描和重新扫描、快照恢复、账号隔离、清理后失效、字节比例 |
| `ui/test_audio_settings.gd` | 直接 Godot，可 headless 或 GPU | 三张卡片顺序、清理确认、仅清理语音 |
| `ui/test_settings_prewarm.gd` | 直接 Godot，headless | 隐藏预加载和首次显示都不触发媒体或容量扫描 |
| `ui/test_modal_visual_contract.gd` | 直接 Godot，GPU 时截图 | 确认框和错误框共用样式、无重复关闭按钮、危险按钮层级、三种宿主尺寸、扁平/清透圆角 |
| `ui/test_action_and_icon_styles.gd` | 直接 Godot，GPU 时验证悬停 | 图片和音量图标、聊天发送键、设置底部按钮、动态窗口和详情输入框样式 |
| `ui/test_login_presentation.gd` | `run_feature_tests.py --gpu` | 淡蓝圆角、头像光晕、菜单、服务器框、账号历史、记住状态、四档缩放和小屏 |
| `ui/test_login_style.gd` | 直接 Godot，可 headless | 登录页专用样式、扁平/清透圆角、登录后共享主题不变 |
| `ui/test_bubble_sizing.gd`、`ui/test_image_bubble_sizing.gd` | 直接 Godot，可 headless 或 GPU | 实际排版宽度、90% 上限、图片原比例、长图延迟加载和可见图片锚点 |
| `ui/test_chat_reading_buttons.gd` | 直接 Godot，可 headless 或 GPU | “回到最新”、未读定位、缺失目标翻页重试和自动定位抑制 |
| `ui/test_logout_confirmation.gd` | `run_feature_tests.py --gpu` | 鼠标触发、确认来源、取消焦点、实际退出提示和保存失败保留草稿 |
| `ui/test_chat_timestamps.gd` | `run_feature_tests.py --gpu` | 时间分组、跨日、非法时间、系统消息排除、历史分页、阅读锚点、两种主题和两种窗口尺寸 |
| `ui/test_chat_review_layout.gd` | `run_feature_tests.py --gpu` | 聊天页改版后的导航、输入区、角色区、未读卡片、图片和音量控件 |
| `ui/test_dynamics_review_actions.gd` | `run_feature_tests.py --gpu` | 动态列表滚动分页、失败重试、评论刷新、草稿和阅读位置、发布浮层 |
| `ui/test_dynamics_reading_position.gd` | 默认回归或直接 Godot | 动态详情刷新后的阅读位置 |
| `ui/test_ui_style_application.gd` | `run_feature_tests.py --gpu` | 主题保存、跨窗口切换和重启恢复 |
| `ui/test_native_window_controls.gd` | 直接 Godot，设置 `GODOT_TEST_PYTHON` | 系统拖拽、缩放、最小化/最大化/关闭和 Alt+F4 |
| `ui/test_decision_layout.gd` | 直接 Godot，不加 `--headless` | 内嵌确认框的可见范围和 Esc 取消 |
| `avatar/test_avatar_interaction.gd` | 直接 Godot，不加 `--headless` | 模型网格触摸、视线和反馈 |
| `avatar/test_avatar_render.gd` | 直接 Godot，不加 `--headless` | 图集 mipmap 和登录后角色区非黑屏像素阈值 |
| `capture_release_ui.gd` | `run_feature_tests.py --gpu` | 主界面、最小尺寸、125/150/200% 缩放、设置和日志截图，原生窗口联动 |
| `capture_dynamics_ui.gd` | `run_dynamics_tests.py --gpu` | 动态双栏、发布浮层、缩放和独立任务栏窗口 |
| `capture_voice_ui.gd` | `run_websocket_tests.py --gpu` | 语音界面、角色呈现和内容缩放 |
| `capture_dropdown_ui.gd` | 直接 Godot，不加 `--headless` | 下拉边界、键盘操作、移动时收起、透明圆角和内部实底 |

Python 原生驱动需要设置：

```powershell
$env:GODOT_TEST_PYTHON = $python
```

Windows 音频输出检查：

```powershell
& $engine --headless --audio-driver WASAPI --path . --script res://tests/media/test_reply_audio.gd
```

该命令会向默认音频设备播放短合成音，并检查混音输出不为零；它不代表人工听感或真实语音服务验证。

## Python 自检

```powershell
python .\tests\test_dependency_boundaries.py
python .\tests\test_review_documentation.py
python .\tests\test_check_gate.py
python .\tests\test_build_prompt.py
python .\tests\test_complexity_check.py
```

| 脚本 | 内容 |
| --- | --- |
| `test_dependency_boundaries.py` | 检查实际代码中的依赖方向，以及普通界面和业务代码是否直接创建平台或存储实现 |
| `test_review_documentation.py` | 检查文档链接、命令中的目录名、版本字段和模拟数据 |
| `test_check_gate.py` | 用假引擎验证 `check.ps1` 的复杂度检查顺序和失败传播 |
| `test_build_prompt.py` | 用临时工程验证版本输入、三段/四段同步、重复打包和错误配置 |
| `test_complexity_check.py` | 验证复杂度检查器的边界和解析行为 |

CI 的 `godot-static` 作业运行上述五个脚本和 `check_complexity.py`，不启动 Godot。

## 复杂度检查

正式入口在行为检查前执行：

```powershell
python .\scripts\check_complexity.py
python .\scripts\check_complexity.py --format json
```

阈值固定为 10，等于 10 合法。覆盖 `src/` 和 `tests/` 的 GDScript，`scripts/` 和 `tests/` 的 Python，`scripts/` 的 PowerShell，自有 `native/` 源码和 `SConstruct`，以及 `assets/` 的 shader。第三方插件、`native/godot-cpp`、生成物和二进制不参与检查。

GDScript 使用 gdtoolkit AST；Python 使用标准 AST；PowerShell 使用本机 AST，优先 PowerShell 7，否则使用 Windows PowerShell 5.1；C++ 使用 tree-sitter-cpp 和 Lizard；shader 先做结构解析，再用 Lizard 计数。解析失败、依赖缺失或超限都会使入口失败，不能用“跳过”绕过。

复杂度通过不代表行为通过；仍需运行受影响的四组回归和 GPU/原生窗口测试。

## 编写约定

- 测试之间不互相导入入口；共享工具放在 `tests/support/`。
- 本地 HTTP/WebSocket 服务只监听回环地址，不写入公共服务，不使用真实账号或真实付费模型。
- `tests/fixtures/chat/reply_events.json` 由 `run_websocket_tests.py` 读取，先交给旧 Python 客户端解析器校验，再作为 WebSocket 消息发送给 Godot，用于跨端协议验证。
- 失败、取消、账号隔离和资源释放场景各自创建对象、时钟、信号记录和临时目录，不依赖前置测试的遗留状态。
- 移动 `.gd` 文件时一起移动 `.uid`；删除已被替代的测试时，删除对应 UID 和执行入口。
- 截图和日志输出到 `artifacts/`，不提交到 Git。
- 未实测的平台、系统设置或外部服务必须在测试说明中明确写出。

## 已知边界

- GPU 测试需要真实图形会话；界面缩放截图不能代替系统 DPI、多显示器或 Windows 10 验证。
- 账号、网络和功能组使用本地模拟服务，不连接公共服务器。
- 真实语音服务、真实模型供应商、长时间运行和集成显卡性能需要单独验收。

## 相关文档

- [客户端说明](../README.md)
- [使用说明](../PREVIEW.md)
