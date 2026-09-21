# Godot 客户端测试契约与整理映射

2026-09-21用户批准。只整理client_godot测试与入口，不改产品、旧端或服务端协议。本文件替代旧UI搬迁契约中要求测试逐字锁定内部布局、脚本路径和生成公式的部分；保留实际需求与可观察行为。旧架构快照和开发进度中的旧路径仅表示历史事实。

## 职责和调用方式

- 保持SceneTree测试脚本、四组PowerShell检查和独立Python loopback runner，不引入新框架。脚本可独立运行，非零退出或引擎错误不能算通过。
- 基础检查无需Python；账户/网络/功能检查保持既有-Godot/-Python参数。Python runner保持--godot/--script/--gpu及原有GODOT_TEST_SERVER、GODOT_TEST_PYTHON约定，GPU仍显式选择。
- 测试只通过真实模块公开接口观察结果；HTTP/WebSocket、时钟、文件系统等外部边界使用本地夹具。每组独立创建并释放控制器、音频、时钟、信号记录、端口和临时目录。
- 账户协议、会话、表单和Application分层；设置模块与应用草稿汇总分层；评论异常反馈、角色时序、原生窗口操作独立保留。不同层次共同使用同一模块不构成重复。
- support/interop_crypto.py的server_crypto()原样抽取现有服务端generate_keys/get_public_key_pem/decrypt_password函数，返回独立命名空间，不连接数据库。源文件相对仓库位置解析，不依赖当前工作目录。
- support/wave_samples.py的tone(seconds,rate=24000)保持单声道16位PCM WAV、440Hz/8000幅值样本。支持模块不导入runner、不启动服务或持有测试状态；各runner保持独立Handler与成功/失败判断。

## 脚本覆盖迁移

路径相对client_godot/tests。目标先完整保留独有行为，再删除旧脚本和UID；移动目标保留原UID。

| 原脚本/检查 | 整理后归属 | 保留的独有验证 |
| --- | --- | --- |
| test_reply_audio.gd + test_audio_lifecycle.gd | media/test_reply_audio.gd | 流式混音/顺序/静音/口型/停止/reset/日志，以及重复终止幂等、停止保留解码错误、60秒超时、17路拒绝与容量释放后不重启、跨UUID内存上限；混音与生命周期使用独立实例和信号记录 |
| test_audio_cache.gd + storage/test_cache_retention.gd | storage/test_audio_cache.gd | 原缓存完整提交、scope隔离、损坏/不可写、清理；天数负数拒绝、过期/近期/精确边界、旧元数据mtime、锁文件部分失败与重试、接收中流保留、0全清；两组独立目录与时钟 |
| ui/test_editable_scene_children.gd | test_ui_scenes.gd、test_theme_contract.gd | ready前下拉实例来源、SecurityError固定错误、分隔线场景；动态normal/selected样式及选中可区分归入主题 |
| ui/test_settings_layout.gd | ui/test_settings_control_states.gd的GPU分支 | 720×640下Reload滚动可达且不与固定操作栏重叠；沿用加载/失败/重试/保存、六种开关状态和四档内容缩放 |
| ui/test_rounded_dropdown.gd | capture_dropdown_ui.gd | 嵌入、透明背景、角alpha<0.2/内部alpha>0.8及所属视口范围，保留圆角截图；稳定ID headless测试不合并 |
| test_dynamics_window.gd控制器段 | test_dynamics.gd | 发布成功、回复parent保存、翻页后新评论顺序、只读拒绝、非法parent拒绝；独立控制器场景 |
| test_dynamics_window.gd界面段 | test_dynamics_detail.gd | 发布浮层属于动态窗口、HTTP失败保留草稿与错误、脏关闭确认、销毁窗口不销毁控制器；独立控制器/窗口/临时几何文件 |
| run_account_tests/run_feature_tests对run_security_interop的导入 | support/interop_crypto.py | 保持真实服务端加密互操作及随机OAEP；runner不再互相导入 |
| run_feature_tests对run_websocket_tests.tone的导入 | support/wave_samples.py | 相同WAV格式和音频内容；不加载WebSocket runner的其它依赖 |
| check_network重复执行test_reliable_outbox | 仅check.ps1直接执行 | 无Python基础队列覆盖保留，网络组仍覆盖真实WebSocket传输；凭据基础检查与跨语言互操作目的不同，均保留 |

## 场景/主题断言保留与删除理由

| 原断言类别 | 处理与观察入口 |
| --- | --- |
| 场景存在、可无参实例化、根公开名称/类型、setup与%入口、主题 | 保留；固定节点在add_child/ready前检查，setup前实例化契约不变 |
| 控件嵌套完整路径、脚本resource_path、_init参数反射 | 删除；改按公开%入口/方法及实际实例化观察，避免内部重组导致无意义失败 |
| 密码/API Key遮蔽、正文可复制/自动换行、文件选择器原生、必要操作与错误提示 | 保留为%入口属性或对应行为测试；输入placeholder/操作tooltip检查非空而非逐字相等。退出动作和不自动提交提示检查实际弹出的dialog，不锁定展示前会被覆盖的默认title/body |
| 装饰标题/placeholder逐字等价、旧容器边距/间距/尺寸/位置/行内字号快照 | 删除旧搬迁锁定；导航、可达尺寸、窗口关系与内容缩放由现有专门行为/GPU测试验证 |
| 项目统一主题、15px正文、#66CCFF主色、#304553正文、#168AC2焦点/#D9F1FF选中、圆角与实底 | 保留主题需求，read_only及开关真实状态继续由设置GPU测试验证 |
| 全部状态的旧色值/内边距精确表、Windows字体名称数组 | 删除无现行需求的实现快照；保留字体资源可用、关键语义颜色及normal/hover/pressed/disabled/focus可区分 |
| Shader源码字符串、按同一公式重新生成滑块图片逐像素比对 | 删除实现镜像；保留资源加载、滑块各态图标与可见圆形纹理结果检查；下拉圆角GPU像素验收独立保留 |

## 验收与兼容

先记录四组检查和受影响GPU验收基线；合并目标逐项运行，再跑完整四组及设置/下拉/动态GPU回归。比较覆盖映射，不以断言数或脚本数作为通过标准。预计59个test_*.gd变为53个；GPU未注册脚本仍需在入口说明列出。

删除路径不得残留在可执行入口；历史文档不改写已发生事实，增加当前入口索引即可。禁止测试互相import/preload（支持模块除外），禁止共用业务状态。纯测试重构Red不适用，不破坏产品制造失败；局部检查发现新缺陷时另按复现处理。仅本地提交，不改release.json、不打包或覆盖交付物、不纳入热重载DLL差异。
