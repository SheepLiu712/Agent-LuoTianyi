# Godot 测试入口

当前有53个`test_*.gd`：50个由四组headless检查编排，3个仅用于图形/原生窗口验收。另有4个`capture_*.gd`视觉入口。目录表示模块职责，GPU能力由运行方式区分；未列入默认组不代表过时。

完整契约及旧脚本迁移对照见[测试契约](../../docs/项目说明/项目架构与接口（spec）/接口文档/client_godot/testing.md)，完成事实见[进度](../../docs/开发进程文档/开发进度/Godot测试精简与解耦.md)。历史文档中的旧文件名不再作为当前运行入口。

## 默认回归

在仓库根目录运行，使用锁定的Godot 4.7.1控制台版本；Python依赖沿用requirements-auth/websocket/features/visual.txt。建议通过单独APPDATA目录隔离验收数据，并保留Python依赖所在路径。

```powershell
$engine = '<Godot控制台exe绝对路径>'
$python = '<已安装测试依赖的python.exe>'
& ./client_godot/scripts/check.ps1 -Godot $engine
& ./client_godot/scripts/check_accounts.ps1 -Godot $engine -Python $python
& ./client_godot/scripts/check_network.ps1 -Godot $engine -Python $python
& ./client_godot/scripts/check_features.ps1 -Godot $engine -Python $python
```

| 分组 | 当前内容 |
| --- | --- |
| check | 导入、启动、离线样板及28个Godot测试，共31项；无需Python，包含可靠队列与凭据基础检查 |
| accounts | 原服务端加密互操作及4个账户协议/会话/UI/Application测试 |
| network | 4个WebSocket/真实聊天/语音/触摸上报测试；不重复直接执行可靠队列测试 |
| features | 3个历史/图片、8个设置/退出/模型、3个动态测试，共14个 |

各组可独立运行，不依赖前一组生成状态；首次使用新检出应先完成Godot资源导入。`scripts/common.ps1`和各Python runner保留各自错误/超时判定，不能仅根据生成截图认定通过。

合并目标可单独执行：

```powershell
& $engine --headless --path client_godot --script res://tests/media/test_reply_audio.gd
& $engine --headless --path client_godot --script res://tests/storage/test_audio_cache.gd
& $python client_godot/tests/run_dynamics_tests.py --godot $engine --script res://tests/test_dynamics.gd
& $python client_godot/tests/run_dynamics_tests.py --godot $engine --script res://tests/test_dynamics_detail.gd
```

## GPU与原生验收

必须在真实图形会话运行。以下是现行入口，按需要分别执行，不将内容缩放当作系统DPI验收。

| 脚本（相对tests） | 启动方式 | 验证内容 |
| --- | --- | --- |
| ui/test_settings_control_states.gd | run_feature_tests.py --gpu | 延迟/失败读取、重试、保存、六态开关、默认/最小及100/125/150/200%缩放；包含原最小布局Reload滚动验收 |
| ui/test_logout_confirmation.gd | run_feature_tests.py --gpu | 鼠标触发、确认来源、取消焦点、实际退出提示、保存失败留稿 |
| capture_release_ui.gd | run_feature_tests.py --gpu | Application主界面、设置/日志、原生联动及合成语音样本链路 |
| capture_dynamics_ui.gd | run_dynamics_tests.py --gpu | 双栏/发布浮层/缩放及Windows独立任务栏窗口 |
| capture_voice_ui.gd | run_websocket_tests.py --gpu | 真实语音UI/角色呈现与内容缩放 |
| capture_dropdown_ui.gd | 直接Godot --script，不加--headless | 下拉边界/键盘/移动收起、透明圆角像素及内部实底 |
| avatar/test_avatar_interaction.gd | 直接Godot --script，不加--headless | 真实模型网格触摸、视线及反馈 |
| ui/test_decision_layout.gd | 直接Godot --script，不加--headless | 内嵌确认框可见范围与Esc取消 |
| ui/test_native_window_controls.gd | 直接Godot --script，并设置GODOT_TEST_PYTHON | 操作其创建的测试窗口，验证系统拖拽/缩放/三键与Alt+F4 |

Python runner入口统一带`--godot $engine --script res://tests/<脚本> --gpu`。下拉示例：`& $engine --path client_godot --script res://tests/capture_dropdown_ui.gd`。原生驱动的Python路径：`$env:GODOT_TEST_PYTHON = $python`。

显式Windows音频驱动：`& $engine --headless --audio-driver WASAPI --path client_godot --script res://tests/media/test_reply_audio.gd`。它播放合成声音并检查真实混音，不代表主观听感或公共TTS服务验收。

## 解耦与覆盖维护

- 用例不导入其他测试入口；可复用夹具只放support。各HTTP/WebSocket Handler保持领域职责，不做万能模拟服务。
- 加密夹具仍使用原服务端实际函数；WebSocket仍读取旧客户端实际wire解析器。这是跨端协议互验，不是测试启动顺序依赖。
- 场景测试只约束公开入口、ready前控件和必要语义；输入/操作提示非空，关键退出提示从实际显示状态验证，不锁定内部布局或运行时覆盖的旧默认文案。
- 失败、取消、账号隔离及资源释放场景独立创建对象/时钟/信号记录/临时目录。不要为减少文件数把不同层的测试串成依赖前置步骤的大流程。
- 移动`.gd`时一起移动其UID；删除已替代测试时删除对应UID和执行入口。现行命令同步更新，历史完成记录保留并链接本页。
- 图形检查输出在artifacts；本次整理的前后日志在artifacts/test-cleanup。未实测的平台或外部服务必须明确记录。
