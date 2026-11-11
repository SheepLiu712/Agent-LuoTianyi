# Godot 客户端脚本清单与依赖概览

范围：`client-godot/**/*.gd`（不含 `addons/godot-sqlite` 的第三方 DLL 与 `native/godot-cpp`）。

当前保留 **235** 个 `.gd`，共 **28863** 行；文件级强连通分量 **0**；GDScript 圈复杂度违规 **0**。

## 1. 删除 / 迁移文件清单

| 处理 | 文件 | 理由 |
|---|---|---|
| 删除 | `src/domain/server_history_time.gd` | 全仓无任何 `.gd`/场景/测试入边；严格日历校验已被 `chat_time.gd` 覆盖。 |
| 删除 | `src/platform/native_pcm_decoder.gd` | 6 个方法逐字转发 `PcmStreamDecoder`，唯一入边是 `native_decoder_factory.gd`；已内联为该工厂的内部 `Decoder` 类。 |
| 迁移 | `src/storage/image_file_reader.gd` → `src/platform/image_file_reader.gd` | 纯 FileAccess/图片读取，属平台 I/O；迁移后切断 `platform → storage` 反向依赖。 |
| 迁移 | `src/storage/log_export_target.gd` → `src/platform/log_export_target.gd` | 文件选择结果 DTO，属平台交互；迁移后切断 `platform → storage` 反向依赖。 |
| 新增 | `src/storage/cache_pruner.gd` | 合并 `audio_cache`/`history_images` 的同构配额淘汰，降低重复与复杂度。 |

同时删除上述 4 个旧文件的 `.uid`。未删除任何测试脚本：未接线的脚本均有手工/GPU/导出验收价值，删除会丢覆盖。

## 2. 依赖关系概览

- 入口：`src/application.gd`（主场景）、`src/preview/chat_preview.gd`（预览场景）、各 `scenes/**/*.tscn` 的 `script=`、测试 runner 的 `--script`。
- 方向：`application/composition` → `ui/session/network/media/storage/domain/platform`；`session` → `media/network/domain/storage`；`ui` → `platform/storage/session`；`storage` → `domain`；`platform` 适配器 → 端口/媒体/头像。
- 无文件级循环依赖；迁移后 `platform → storage` 边为 0，包级 `storage ⇄ platform` 环已打断。
- 主要扇入：`error_dialog.gd`(17)、`log_schema.gd`(16)、`godot_storage_service.gd`(16)、`websocket_transport.gd`(16)、`server_address.gd`(16)。
- 主要扇出：`application_services.gd`(29)、`application.gd`(18)、`history_images.gd`(9)、`chat_session.gd`(5)、`sqlite_history_database.gd`(6)。
- 跨层边：`network → storage/log_*` 8 条、`ui → storage` 6 条、`session → storage` 3 条、`storage → platform` 1 条（`client_log` 的运行时环境兜底）；这些是后续可继续收敛的端口化点。

## 3. 保留文件清单

### 3.1 应用 / 组合 / 领域 / 扩展 / 平台

| 文件 | 行 | 职责 |
|---|---:|---|
| `src/application/account_lifecycle.gd` | 79 | 账号启停编排：按顺序启动/回滚 chat、models、dynamics、avatar、extensions |
| `src/application/ui_style.gd` | 220 | 运行时外观：主题、图标、气泡/面板样式与偏好持久化 |
| `src/application/window_coordinator.gd` | 146 | 设置/动态子窗口的创建复用、关闭确认与草稿收集 |
| `src/composition/application_services.gd` | 95 | 唯一服务装配根：构造存储、网络、会话、媒体与窗口依赖 |
| `src/domain/account_scope.gd` | 7 | 由规范化服务器地址与用户名生成稳定账号隔离 key |
| `src/domain/history_runs.gd` | 26 | 把历史页按已知 UUID 锚点切成插入 run，并检测顺序冲突 |
| `src/domain/message_uuid.gd` | 12 | 生成 RFC4122 v4 UUID |
| `src/domain/server_address.gd` | 94 | 服务器地址规范化、TLS/loopback 判定、主机与端口提取 |
| `src/domain/timeline_slots.gd` | 39 | 在左右边界之间分配 2^20 间隔的 timeline_order，溢出/冲突返回错误 |
| `src/extensions/appearance_service.gd` | 16 | 预留外观能力契约（当前明确不可用） |
| `src/extensions/device_service.gd` | 15 | 预留设备控制契约（当前明确不可用） |
| `src/extensions/world_service.gd` | 16 | 预留双向世界契约（当前明确不可用） |
| `src/platform/cubism_avatar_driver.gd` | 216 | Live2D 具体驱动：模型/映射、表情/动作/口型/视线/眨眼/网格命中 |
| `src/platform/desktop_window_host.gd` | 121 | 桌面窗口宿主：登录/展开形态、几何恢复保存与可见区钳制 |
| `src/platform/external_link_opener.gd` | 5 | 打开项目主页的端口（默认不可用） |
| `src/platform/file_interaction.gd` | 12 | 文件选择端口（默认失败/取消） |
| `src/platform/godot_external_link_opener.gd` | 4 | 用 OS.shell_open 打开项目主页的适配器 |
| `src/platform/godot_file_interaction.gd` | 38 | FileDialog 绑定、图片读取、导出目标创建 |
| `src/platform/godot_input_service.gd` | 21 | DisplayServer IME/剪贴板与 IME 控制器适配器 |
| `src/platform/godot_runtime_environment.gd` | 22 | OS/DisplayServer/Logger/截屏的具体运行时实现 |
| `src/platform/godot_window_system.gd` | 16 | Window 模式/焦点/几何/reparent 的具体实现 |
| `src/platform/image_file_reader.gd` | 14 | 带大小校验的整文件图片读取（平台 I/O） |
| `src/platform/input_service.gd` | 14 | 跨平台系统输入端口：IME、剪贴板、IME 控制器 |
| `src/platform/log_export_target.gd` | 11 | 用户选择的日志导出目标路径 DTO |
| `src/platform/native_decoder_factory.gd` | 33 | 用 ClassDB 创建原生 PcmStreamDecoder，并包装为稳定 RefCounted 接口 |
| `src/platform/password_encryption.gd` | 5 | 密码加密端口（默认不可用） |
| `src/platform/runtime_environment.gd` | 19 | 运行时环境端口：headless/进程/截屏/模糊能力 |
| `src/platform/secret_protection.gd` | 5 | secret 保护端口（默认失败） |
| `src/platform/window_host.gd` | 17 | 顶层窗口宿主端口 |
| `src/platform/window_system.gd` | 13 | 单窗口操作端口（模式/焦点/几何/reparent） |
| `src/platform/windows_password_encryption.gd` | 6 | WindowsSecurity 密码加密适配器 |
| `src/platform/windows_secret_protection.gd` | 20 | WindowsSecurity DPAPI secret 保护适配器 |

### 3.2 会话 / 媒体 / 网络 / 预览

| 文件 | 行 | 职责 |
|---|---:|---|
| `src/media/avatar_image.gd` | 11 | 头像中心正方形裁切并缩放到 256 |
| `src/media/cache_replay.gd` | 135 | 本地缓存语音的流式解码播放与嘴型幅度 |
| `src/media/decoder_factory.gd` | 3 | 解码器工厂端口（默认无解码器） |
| `src/media/image_attachment.gd` | 156 | 图片头解析、格式/大小/尺寸校验并生成纹理 |
| `src/media/reply_audio.gd` | 445 | 语音接收、解码、缓存、在线播放/重放、嘴型与超时控制 |
| `src/network/account_api.gd` | 165 | 账号 HTTP API：登录/注册/重置/自动登录、公钥加密、取消 |
| `src/network/history_api.gd` | 169 | 历史分页 HTTP 客户端：单在途、失败分类、响应校验 |
| `src/network/json_request.gd` | 81 | 通用 JSON HTTP 客户端：URL 白名单、单在途、日志 |
| `src/network/reliable_outbox.gd` | 108 | 发送队列：幂等 ID、退避重试、ACK/NACK、过期不确定 |
| `src/network/websocket_transport.gd` | 300 | 聊天 WebSocket：连接/鉴权/心跳/重连、收发与 ACK 分发 |
| `src/preview/chat_preview.gd` | 174 | 演示聊天场景：demo session、场景切换、图片预览、--capture |
| `src/preview/demo_session.gd` | 43 | 演示消息与场景（scenario/submit/settle） |
| `src/session/account_session.gd` | 291 | 账号状态机：恢复凭据、登录、切换服务器、登出 |
| `src/session/avatar_profile.gd` | 64 | 按账号 scope 读取头像并广播变更 |
| `src/session/chat_session.gd` | 778 | 会话编排：收发、流式回复、表情/语音/图片状态、历史接入 |
| `src/session/dynamics_controller.gd` | 470 | 动态流、评论、未读与定时刷新 |
| `src/session/history_fetcher.gd` | 45 | 历史页单请求抓取；generation 作废旧结果，失败最多重试一次 |
| `src/session/history_sync.gd` | 584 | 本地优先分页编排、缺口/补齐、对账调度；不直接执行 SQL/HTTP |
| `src/session/history_sync_policy.gd` | 53 | 历史分页边界、重试资格、是否继续补齐的纯函数 |
| `src/session/message_persistence.gd` | 223 | 会话层唯一写库门面：命令 payload、行→DTO、丢弃计数 |
| `src/session/model_executor.gd` | 177 | 模型请求执行、超时与近期结果缓存 |
| `src/session/model_settings.gd` | 154 | 模型配置加载/校验/保存/启用集合 |
| `src/session/preferences_controller.gd` | 128 | 关系/表达风格等偏好字段读写 |

### 3.3 存储

| 文件 | 行 | 职责 |
|---|---:|---|
| `src/storage/atomic_file.gd` | 26 | tmp→flush→rename 原子写 |
| `src/storage/audio_cache.gd` | 320 | 音频成对缓存、manifest、单条/账号配额与查找 |
| `src/storage/audio_import.gd` | 189 | Python WAV→账号缓存：.part 成对原子写与 marker |
| `src/storage/avatar_store.gd` | 89 | 每账号头像 PNG 读写 |
| `src/storage/cache_pruner.gd` | 34 | 共享缓存配额淘汰：按 mtime 从旧到新删除 |
| `src/storage/client_log.gd` | 632 | 日志运行目录/元数据/JSONL、归档读取、zip 导出与脱敏 |
| `src/storage/credential_store.gd` | 91 | 每服务器加密 token 存取/遗忘与事务日志 |
| `src/storage/engine_log_sink.gd` | 54 | Godot Logger→ClientLog 桥 |
| `src/storage/godot_read_stream.gd` | 13 | FileAccess→ReadStream 适配器 |
| `src/storage/godot_settings_store.gd` | 26 | ConfigFile 设置实现 |
| `src/storage/godot_storage_service.gd` | 100 | 登录 profile cfg、磁盘查询、凭据委托 |
| `src/storage/history_image_codec.gd` | 40 | 历史图片统一解码限额：PNG/JPEG/WebP 字节/边长/像素 |
| `src/storage/history_image_source.gd` | 19 | 图片源接口/空实现（信号 + 下载/缓存方法） |
| `src/storage/history_images.gd` | 245 | 图片下载、本地缓存、预览、来源迁移与配额淘汰 |
| `src/storage/history_migration.gd` | 156 | v1/v2→v3 重建式迁移、备份与外键自检 |
| `src/storage/history_page_writer.gd` | 605 | 历史页/实时/对账写事务、位置分配、去重与交付对账 |
| `src/storage/history_schema.gd` | 369 | 历史库全部 SQL 文本与表/列/索引契约 |
| `src/storage/history_schema_installer.gd` | 26 | 空库 v3 安装，user_version 最后写 |
| `src/storage/image_import.gd` | 60 | Python 图片→账号缓存 |
| `src/storage/log_events.gd` | 83 | HTTP/WS/UI/安全/文件事务事件字段成形 |
| `src/storage/log_schema.gd` | 551 | 日志九类 schema：分类/级别/事件白名单/脱敏/归一化 |
| `src/storage/model_store.gd` | 83 | 每模型配置加密存取（AtomicFile） |
| `src/storage/python_client_locator.gd` | 196 | 只读定位 Python 客户端目录与媒体索引 |
| `src/storage/python_media_migration.gd` | 502 | 选目录→扫描→音频/图片导入编排与进度 |
| `src/storage/python_media_migration_port.gd` | 63 | 媒体迁移 UI 端口（信号 + 语义） |
| `src/storage/read_stream.gd` | 9 | 流读取接口 |
| `src/storage/reading_position.gd` | 85 | 每账号阅读位置原子持久化 |
| `src/storage/release_info.gd` | 8 | 读取 release.json 版本信息 |
| `src/storage/settings_store.gd` | 10 | 通用设置读写接口 |
| `src/storage/sqlite_access.gd` | 126 | SQLite 查/执行/块执行/事务（BEGIN IMMEDIATE） |
| `src/storage/sqlite_history_database.gd` | 393 | 连接生命周期 + 迁移/校验 + 命令白名单分发 |
| `src/storage/sqlite_worker.gd` | 211 | DB 工作线程、Ticket、结果队列与线程日志 |
| `src/storage/storage_service.gd` | 20 | 存储查询接口（未知=-1） |
| `src/storage/timeline_reader.gd` | 74 | timeline_order keyset 分页读（旧→新）+ order_revision |
| `src/storage/wav_metadata.gd` | 264 | WAV 头解析/校验/波形纯数据工具 |
| `src/storage/window_geometry.gd` | 32 | 窗口布局 ConfigFile 持久化 |

### 3.4 UI / 头像 / 根

| 文件 | 行 | 职责 |
|---|---:|---|
| `src/application.gd` | 503 | 应用组合根：主窗口两态、服务装配、子窗口、日志/性能采样、退出持久化 |
| `src/avatar/avatar_driver.gd` | 12 | Live2D 驱动抽象接口与默认空状态 |
| `src/avatar/avatar_framing.gd` | 53 | 头像缩放/平移变换与布局持久化 |
| `src/avatar/avatar_panel.gd` | 176 | 角色面板：加载模型、点击命中、拖拽平移、滚轮缩放、未读动态标题 |
| `src/avatar/avatar_preview.gd` | 17 | 独立头像冒烟场景与 --capture 入口 |
| `src/avatar/touch_ripple.gd` | 7 | 点击涟漪动画后自毁 |
| `src/ui/account_view.gd` | 409 | 登录/注册/重置表单、焦点链、IME、本机账号历史与服务地址弹层 |
| `src/ui/audio_settings_page.gd` | 327 | 设置窗语音/存储页：清缓存、导入 Python 媒体、显示磁盘占用 |
| `src/ui/chat_time.gd` | 68 | 消息时间戳→时间分隔标记（秒解析、分钟标签） |
| `src/ui/chat_view.gd` | 428 | 聊天主视图：输入/发送/图片附件、历史状态、未读定位、音量、错误播报 |
| `src/ui/composer_input.gd` | 39 | TextEdit 子类：Enter 发送、Tab 逃逸、Ctrl+V 贴图、IME 组合保护 |
| `src/ui/composer_resize_handle.gd` | 65 | 输入区上沿拖动带，只发 drag_delta/drag_committed |
| `src/ui/decision_dialog.gd` | 43 | 确认/取消（可选保存并关闭）模态窗 + Esc |
| `src/ui/draft_window.gd` | 20 | 动态窗基类：初始隐藏、关闭脏检查 |
| `src/ui/dropdown_item.gd` | 6 | 下拉行按钮，setup() 注入 label/id/disabled |
| `src/ui/dynamic_comment_row.gd` | 45 | 单条动态评论行，注入数据与回复回调 |
| `src/ui/dynamic_detail.gd` | 286 | 动态详情：正文、评论分页、评论/回复草稿、相对时间 |
| `src/ui/dynamics_post_row.gd` | 40 | 动态列表行（头像/作者/类型+时间/摘要/未读点） |
| `src/ui/dynamics_window.gd` | 341 | 动态中心窗：列表+详情分栏、未读/刷新/分页、发布浮层、布局持久化 |
| `src/ui/error_dialog.gd` | 115 | 全局错误弹窗：跨窗口懒加载、队列串行、去重、焦点归还 |
| `src/ui/frost_surface.gd` | 6 | 毛玻璃 ColorRect，不支持模糊时移除材质 |
| `src/ui/image_presenter.gd` | 34 | 图片预览窗生命周期：复用/重挂/样式/关闭确认 |
| `src/ui/image_thumb_button.gd` | 33 | 图片入口按钮：鼠标与 Enter/Space 统一激活、焦点描边 |
| `src/ui/image_window.gd` | 116 | 图片预览窗：缩放/适应/原图/确认发送/最小化联动 |
| `src/ui/log_window.gd` | 196 | 日志窗：批次/类别/级别/模块/归属筛选、搜索、复制、导出 zip |
| `src/ui/message_audio.gd` | 41 | 单条语音行：播放/暂停/停止、波形、时间、错误提示 |
| `src/ui/message_bubble.gd` | 200 | 单条消息气泡：测宽、系统消息、头像、图片/语音子控件、送达状态 |
| `src/ui/message_waveform.gd` | 25 | 波形条容器：按 values/progress 调子条高度与颜色 |
| `src/ui/modal_stack.gd` | 15 | 同一父窗只允许一个 exclusive 子窗的降级逻辑 |
| `src/ui/model_page.gd` | 183 | 模型用途配置页：卡片、JSON 参数校验、保存/测试、明文确认 |
| `src/ui/model_purpose_card.gd` | 67 | 单个模型用途卡片（字段/能力开关/复制/测试/脏通知） |
| `src/ui/popup_trigger.gd` | 27 | 按下即关闭/切换弹层的竞态处理 |
| `src/ui/preferences_page.gd` | 104 | 相处偏好页（关系/表达风格预设 + 自由文本） |
| `src/ui/profile_page.gd` | 67 | 头像设置页（选图/恢复默认/即时落盘） |
| `src/ui/publish_overlay.gd` | 68 | 发布动态浮层（草稿、脏确认、Tab 焦点环） |
| `src/ui/settings_window.gd` | 202 | 统一设置窗：五页签聚合保存、脏检查、关闭确认、保存浮层 |
| `src/ui/style_page.gd` | 68 | 界面/图标风格页（扁平/清透、svg/emoji） |
| `src/ui/toast_overlay.gd` | 132 | 居中浮层提示（淡入淡出、常驻、鼠标穿透） |
| `src/ui/unified_dropdown.gd` | 172 | 共享稳定 ID 下拉/动作菜单（构建、定位、键盘、点外关闭） |
| `src/ui/virtual_message_list.gd` | 356 | 虚拟化消息列表：高度缓存、锚点恢复、时间标记、可见集合、上翻分页 |
| `src/ui/window_chrome.gd` | 18 | 窗口外壳薄封装（attach/login_mode/configure/layout/tick） |

### 3.5 测试 / 工具 / 插件

| 文件 | 行 | 职责 |
|---|---:|---|
| `addons/godot-sqlite/godot-sqlite.gd` | 14 | godot-sqlite EditorPlugin 空壳（插件入口，不能单独删） |
| `scripts/build_tianyi_icon.gd` | 58 | 一次性头像生成器（产物溯源保留） |
| `tests/application/test_account_lifecycle.gd` | 58 | 回归：account lifecycle |
| `tests/application/test_default_user_storage.gd` | 26 | 回归：default user storage |
| `tests/application/test_extension_contracts.gd` | 82 | 回归：extension contracts |
| `tests/application/test_platform_degradation.gd` | 44 | 回归：platform degradation |
| `tests/application/test_service_graph.gd` | 42 | 回归：service graph |
| `tests/avatar/test_avatar_interaction.gd` | 86 | 回归：avatar interaction |
| `tests/avatar/test_eye_restoration.gd` | 36 | 回归：eye restoration |
| `tests/avatar/test_touch_delivery.gd` | 53 | 回归：touch delivery |
| `tests/capture_dropdown_ui.gd` | 103 | GPU/原生截图验收：dropdown ui |
| `tests/capture_dynamics_ui.gd` | 85 | GPU/原生截图验收：dynamics ui |
| `tests/capture_release_ui.gd` | 131 | GPU/原生截图验收：release ui |
| `tests/capture_voice_ui.gd` | 84 | GPU/原生截图验收：voice ui |
| `tests/media/test_avatar_image.gd` | 46 | 回归：avatar image |
| `tests/media/test_capability_failures.gd` | 42 | 回归：capability failures |
| `tests/media/test_image_attachment.gd` | 61 | 回归：image attachment |
| `tests/media/test_reply_audio.gd` | 174 | 回归：reply audio |
| `tests/run_client_behavior_comparison.gd` | 357 | 回归：run client behavior comparison |
| `tests/session/test_audio_incremental.gd` | 90 | 回归：audio incremental |
| `tests/session/test_history_paging.gd` | 376 | 回归：history paging |
| `tests/session/test_login_profiles.gd` | 172 | 回归：login profiles |
| `tests/session/test_message_persistence.gd` | 199 | 回归：message persistence |
| `tests/session/test_message_reconcile.gd` | 154 | 回归：message reconcile |
| `tests/session/test_message_timestamps.gd` | 76 | 回归：message timestamps |
| `tests/session/test_model_result_cache.gd` | 34 | 回归：model result cache |
| `tests/session/test_reply_audio_errors.gd` | 172 | 回归：reply audio errors |
| `tests/session/test_send_persistence_order.gd` | 63 | 回归：send persistence order |
| `tests/storage/test_audio_cache.gd` | 174 | 回归：audio cache |
| `tests/storage/test_avatar_store.gd` | 79 | 回归：avatar store |
| `tests/storage/test_login_storage.gd` | 93 | 回归：login storage |
| `tests/storage/test_python_media_migration.gd` | 264 | 回归：python media migration |
| `tests/storage/test_sqlite_database.gd` | 401 | 回归：sqlite database |
| `tests/storage/test_sqlite_migration.gd` | 145 | 回归：sqlite migration |
| `tests/storage/test_sqlite_runtime.gd` | 156 | 回归：sqlite runtime |
| `tests/storage/test_sqlite_transaction_log.gd` | 66 | 回归：sqlite transaction log |
| `tests/storage/test_sqlite_worker.gd` | 105 | 回归：sqlite worker |
| `tests/storage/test_storage_service.gd` | 32 | 回归：storage service |
| `tests/support/audio_samples.gd` | 21 | 回归：audio samples |
| `tests/support/native_reply_audio.gd` | 3 | 回归：native reply audio |
| `tests/test_account_api.gd` | 78 | 回归：account api |
| `tests/test_account_session.gd` | 74 | 回归：account session |
| `tests/test_account_view.gd` | 117 | 回归：account view |
| `tests/test_application_drafts.gd` | 138 | 回归：application drafts |
| `tests/test_application_window.gd` | 154 | 回归：application window |
| `tests/test_avatar_driver.gd` | 54 | 回归：avatar driver |
| `tests/test_avatar_framing.gd` | 44 | 回归：avatar framing |
| `tests/test_client_log.gd` | 194 | 回归：client log |
| `tests/test_demo_session.gd` | 42 | 回归：demo session |
| `tests/test_dropdown.gd` | 47 | 回归：dropdown |
| `tests/test_dynamics.gd` | 155 | 回归：dynamics |
| `tests/test_dynamics_detail.gd` | 274 | 回归：dynamics detail |
| `tests/test_history_media.gd` | 113 | 回归：history media |
| `tests/test_history_sync.gd` | 92 | 回归：history sync |
| `tests/test_live_chat.gd` | 120 | 回归：live chat |
| `tests/test_log_integration.gd` | 88 | 回归：log integration |
| `tests/test_log_schema.gd` | 67 | 回归：log schema |
| `tests/test_log_window.gd` | 124 | 回归：log window |
| `tests/test_model_execution.gd` | 127 | 回归：model execution |
| `tests/test_model_settings.gd` | 86 | 回归：model settings |
| `tests/test_pcm_decoder.gd` | 161 | 回归：pcm decoder |
| `tests/test_preferences.gd` | 71 | 回归：preferences |
| `tests/test_preview_input.gd` | 85 | 回归：preview input |
| `tests/test_reading_position.gd` | 82 | 回归：reading position |
| `tests/test_reliable_outbox.gd` | 120 | 回归：reliable outbox |
| `tests/test_theme_contract.gd` | 151 | 回归：theme contract |
| `tests/test_ui_scenes.gd` | 216 | 回归：ui scenes |
| `tests/test_virtual_history.gd` | 79 | 回归：virtual history |
| `tests/test_voice_chat.gd` | 198 | 回归：voice chat |
| `tests/test_voice_replay.gd` | 157 | 回归：voice replay |
| `tests/test_websocket_transport.gd` | 81 | 回归：websocket transport |
| `tests/test_windows_security.gd` | 90 | 回归：windows security |
| `tests/ui/test_audio_settings.gd` | 73 | 回归：audio settings |
| `tests/ui/test_bubble_sizing.gd` | 113 | 回归：bubble sizing |
| `tests/ui/test_cache_usage_ring.gd` | 41 | 回归：cache usage ring |
| `tests/ui/test_chat_reading_buttons.gd` | 144 | 回归：chat reading buttons |
| `tests/ui/test_chat_review_layout.gd` | 278 | 回归：chat review layout |
| `tests/ui/test_chat_timestamps.gd` | 161 | 回归：chat timestamps |
| `tests/ui/test_comment_feedback.gd` | 36 | 回归：comment feedback |
| `tests/ui/test_composer_resize.gd` | 160 | 回归：composer resize |
| `tests/ui/test_decision_layout.gd` | 26 | 回归：decision layout |
| `tests/ui/test_dynamics_reading_position.gd` | 250 | 回归：dynamics reading position |
| `tests/ui/test_dynamics_review_actions.gd` | 266 | 回归：dynamics review actions |
| `tests/ui/test_error_dialog.gd` | 64 | 回归：error dialog |
| `tests/ui/test_image_bubble_sizing.gd` | 141 | 回归：image bubble sizing |
| `tests/ui/test_image_keyboard.gd` | 123 | 回归：image keyboard |
| `tests/ui/test_image_sending.gd` | 75 | 回归：image sending |
| `tests/ui/test_image_window.gd` | 57 | 回归：image window |
| `tests/ui/test_login_presentation.gd` | 307 | 回归：login presentation |
| `tests/ui/test_logout_confirmation.gd` | 151 | 回归：logout confirmation |
| `tests/ui/test_main_navigation.gd` | 41 | 回归：main navigation |
| `tests/ui/test_model_cards.gd` | 76 | 回归：model cards |
| `tests/ui/test_native_window_controls.gd` | 44 | 回归：native window controls |
| `tests/ui/test_profile_page.gd` | 103 | 回归：profile page |
| `tests/ui/test_settings_control_states.gd` | 183 | 回归：settings control states |
| `tests/ui/test_settings_export_layout.gd` | 36 | 回归：settings export layout |
| `tests/ui/test_system_message_presentation.gd` | 21 | 回归：system message presentation |
| `tests/ui/test_toast_bubble.gd` | 109 | 回归：toast bubble |
| `tests/ui/test_ui_style.gd` | 226 | 回归：ui style |
| `tests/ui/test_ui_style_application.gd` | 197 | 回归：ui style application |
| `tests/ui/test_unified_settings.gd` | 82 | 回归：unified settings |
| `tests/ui/test_visual_surfaces.gd` | 32 | 回归：visual surfaces |
| `tests/ui/test_window_chrome.gd` | 43 | 回归：window chrome |

## 4. 改动与验证

- 复杂度：`python scripts/check_complexity.py --root client-godot` → `0 violations, 0 parse errors`。
- 拆分：`account_api.request`、`audio_cache/history_images` 配额淘汰、`composer_input._gui_input`、`log_window._matches`、3 个测试的超限 `run/_initialize`。
- 依赖调整：`account_view` 的 IME 控制移入 `input_service` 端口；平台 I/O DTO 迁出 storage；`native_pcm_decoder` 内联进工厂。
- 测试接线：`tests/session/test_send_persistence_order.gd` 加入 `scripts/check.ps1`。
- 回归：SQLite/缓存/账号/日志/输入/语音/历史媒体/依赖边界等定向测试通过；GPU/原生截图脚本保留为手工入口。

### 复杂度拆分对照

| 原函数 | 原 CC | 拆分后 |
|---|---:|---|
| `account_api.request` | 11 | `request` + `_payload_for` |
| `audio_cache._prune_scope_bytes` | 12 | `CachePruner.prune` + `_file_size` |
| `history_images._prune_scope_bytes` | 11 | 复用 `CachePruner.prune` |
| `composer_input._gui_input` | 12 | `_is_submit_key` / `_move_focus` / `_is_paste_image` |
| `log_window._matches` | 11 | `_filters_match` / `_selected_matches` / `_search_matches` |
| `test_avatar_interaction.run` | 11 | `_exercise_avatar` + 4 个检查函数 |
| `test_windows_security._initialize` | 13 | 5 个分项检查函数 |
| `test_chat_review_layout.run` | 11 | `_hide_if_present` |
