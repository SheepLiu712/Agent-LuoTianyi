# 当前客户端业务与存储契约

本文件从旧总表保留仍有效的业务、协议及数据约定，移除了已废弃的UI装配过程。调用参数与平台注入以[平台隔离](platform-isolation.md)为准；账户及气泡以[0.1.3](release-013.md)为准，缓存按天清理/容量和角色交互以[反馈契约](feedback-012.md)为准。窗口、草稿与设置保存以[窗口契约](window-redesign.md)及后续反馈覆盖条目为准。

## ModelStore 与 ModelSettings：按用途的本地模型配置

`ModelStore(security,root="user://models")` RefCounted：`set_scope(server,username)`、`read(type_id) -> Dictionary`、`save(type_id,config,allow_plain=false) -> Dictionary`。目录按规范化服务器/账户哈希，用途文件按 type_id 哈希；只保存 enabled/provider/base_url/model/model_kind/model_capabilities/params 与受保护 api_key。DPAPI entropy 包含服务器/账号/用途；保护失败返回 PLAINTEXT_CONFIRMATION_REQUIRED，只有调用方明确 allow_plain 才写 api_key_plain，不自动降级。原子文件写入；解密失败 config 禁用并返回 KEY_UNAVAILABLE，不冒充空密钥成功。

`ModelSettings(http,store,logger=null)` Node：`start(session)` GET /llm/client-model-types，类型字段 id/name/description/model_kind/requires_json/requires_thinking 校验、ID 唯一。`get_types()`、`get_config(type_id)` 返回副本；`get_state()`/changed 只含 phase/code/count，无密钥；`validate(type_id,config) -> Dictionary` 做纯本地校验；`save(type_id,config,allow_plain=false)` 校验再持久化，成功才替换运行配置；`enabled_types() -> Array[String]` 只广告当前定义内启用且有效用途；`copy_config(source_config,target_id)` 保留目标 kind 与能力要求、返回草稿且重新校验后方可保存。未知用途拒绝。

配置 enabled/provider/base_url/api_key/model/model_kind、model_capabilities.can_use_json/can_enable_thinking、params Dictionary；Base URL 只接受 HTTP(S) 规范化地址，不额外添加 v1。启用时要求 model/key/base_url 非空、kind 匹配和满足要求；params.stream 仅允许 false，拒绝 stream_options，model/messages 参数不能覆盖实际模型与委托正文。保存不发供应商请求。`stop()` 取消类型读取并清空本账号内存配置，不删除文件。

## 相处偏好控制器

`JsonRequest(timeout=15,limit=8MiB)` Node 的 `send(url,method,data={},headers=[]) -> Dictionary` 异步返回 ok/code/status/data，单实例忙碌返回 BUSY；JSON 必须对象、禁止重定向、TLS 默认验证、无自动重试、错误不回显正文。`cancel()` 结束等待且迟到回调失效。它只承担 HTTP 外部边界，不读取会话或供应商配置。

`PreferencesController(http,logger=null)` Node 拥有请求器。`start(session)` 加载现有 POST /preference/get；`reload()` 仅非忙碌且无草稿时重试；`edit(fields)` 接受 relationship/speaking_style/personality_text/custom_context 四个字符串；`save()` 在加载成功后重读服务器，比较加载后的表单，仅合并用户修改字段，再 POST /preference/overwrite `{username,token,preferences}`。关系 朋友 和风格 活泼可爱 保存空值；canonical personality_traits 数组优先读取，旧 #sym:personality_text 回退；关键词按中英文逗号/顿号/换行拆分，去空并保序，修改性格后同时写两个字段。未知字段和未修改字段保留服务器最新值。成功响应 status=success 才更新基线；加载失败不可保存、保存失败保留草稿。`get_state()` / changed 提供 phase/fields/can_save/dirty/code；`stop()` 取消并清空秘密/草稿，不落盘正文。

## HistoryImages：按可见 UUID 恢复图片

`HistoryImages(root="user://images",logger=null)` Node，`start(session)` 规范化服务器/账户隔离本地文件并取消旧请求；`stop()` 清除内存及取消网络，完整文件保留。`ensure(id)` 在 UI 可见请求时读取缓存、缺失或损坏则 POST /get_image `{username,token,uuid}`；最多 3 个并发请求、15 秒超时、16 MiB 响应上限、禁止重定向，不使用历史 content 路径或 update_image_client_path。PNG/JPEG/WebP 解码成功才可用，限制 8192 边长、1600 万像素；缩略图最长边 480，本地缓存原图供预览。

`get_state(id)` / `changed(id,state)` 返回 status（idle/loading/ready/error）、texture（缩略图或 null）、original_size（原图像素尺寸）、code；`retry(id)` 显式重试失败，网络无自动重试；`preview(id) -> Texture2D` 从本机已验证文件恢复原图，失败返回 null。文件提交失败仍显示本次图片、报告 CACHE_WRITE_FAILED。内存仅保留最近 24 张缩略图、活动请求/可见控件可持有引用；不淘汰完整图片磁盘文件。退出的迟到请求不产生新账号状态。

ChatSession 构造第六参数 images 可选；提供 `request_message_image(id,retry=false)`、`get_message_image(id)`、`preview_message_image(id)` 及 message_image_changed，只对已显示 type=image 的消息生效。UI 不读图片文件。VirtualMessageList.set_image_state 定向更新气泡的缩略图/加载/重试，点击已有图片通过会话取得原图并打开现有 ImagePresenter。历史语音继续通过消息 UUID 查询已注入 AudioCache，不自动播放或下载。

## ReadingPosition：本机阅读位置

`ReadingPosition(root="user://reading")` RefCounted：`start(server,username)` 规范化并隔离范围，只读本机 UUID，无聊天正文；`update(messages,history_state)` 接收内存快照与同步状态；`get_state()` 返回 saved_id/target_id/pending/manual/located/reason。无旧位置在首批确定后定位最新；有旧位置找到后定位其下一条，直到全量成功仍找不到则最新并 reason=NOT_FOUND。尚在定位期间不得以当前显示最近记录覆盖旧位置；历史失败保持待定位，跳过本次不覆盖旧位置。

`interact()` 标记用户已滚动/发送，随后目标只提供手动入口；`located()` 表示 UI 已执行一次目标定位或接受手动状态，才可记已读。`report_visible(ids,foreground) -> Error` 仅在前台、定位完成后，以可见集合中最后一条稳定服务端 UUID 单调推进；纯本地用户发送 ID 与临时回复不保存。按已加载顺序比较，不用文本/时间推测。以临时文件原子写 scope.json；失败保留旧磁盘记录并 reason=SAVE_FAILED；作用域切换清空内存。不包含跨设备接口。

ChatSession 构造第五参数 reading 可选，正式应用注入；公开 `get_reading_state()`、`note_read_interaction()`、`reading_located()`、`report_visible_messages(ids,foreground)`，UI 不读文件。ChatView 自动定位只一次，已交互则显示“定位未读”按钮；前台窗口焦点与列表可见集合共同上报，后台下载不算已读。验证独立存储目录、首次最新、已读后定位、未找到说明、等待/后台不推进、手动标记、单调性及账号隔离。

## VirtualMessageList：可视消息列表

`VirtualMessageList` 是 ScrollContainer。`set_messages(Array[Dictionary])` 使用 ChatSession 消息快照，按稳定 id 更新；只创建可见范围及有限前后缓冲的气泡节点，1000 条数据不创建 1000 个控件。`scroll_to_message(id) -> bool`、`scroll_to_latest()`、`get_visible_ids() -> Array[String]`、`get_reading_anchor() -> Dictionary`（id/offset）与 `is_at_latest() -> bool` 提供阅读操作。插入历史保留首个可见 id 和相对偏移，原在底部则继续跟随；消息文字未改变不重设 RichTextLabel。改变宽度时重新测量，测量修正仍保持锚点。

`visible_messages(ids)` 在可见集合变化时通知 UI，`interacted` 只表示用户滚动/导航而非程序跳转；`audio_action(id,action)`、`image_opened(texture)` 转发气泡操作；`set_audio_state(id,state)` 只刷新该已渲染消息。ChatView 通过这些入口展示及操作，不读播放器/缓存路径。测试以 1000 条、前插、跳转、宽度变化及可见节点数量/文字选择验证；虚拟高度测量属于内部实现。

## 历史首批边界与全量同步

`HistoryApi(timeout=15)` 为 Node，`fetch_page(session,end_index=-1) -> Dictionary` 异步 GET /history，查询字段 username/count=50/end_index、Authorization: Bearer message_token；真实 username 与 message_token，复用规范化服务器。返回 `{ok,code,status,data}`，无重试/重定向，8 MiB 响应上限；`cancel()` 结束请求并隔离迟到结果。只接受 history 数组和非负整型 start_index；未知字段不传 UI。历史本身不操作播放器。

`HistorySync(api,logger=null)` 为 Node，拥有 api；`start(session)` 重置范围并异步取最新首批，`stop()` 取消并清空范围；`retry()` 重试失败页，`skip()` 仅首批失败有效、释放发送且该登录不再导入历史。`get_state()`/`state_changed(state)` 提供 phase（idle/first_loading/first_failed/loading/failed/complete/skipped）、code、count、start_index、incomplete。`page_received(messages)` 向 ChatSession 提交经校验的 id/role/text/type/timestamp/history=true；`boundary_ready` 仅首批成功或明确跳过发出一次。成功页按 start_index 向前取，首批后的请求不再使用 -1；断线重连不重置此控制器。

UUID 重复去重并显式 incomplete，不用文本/时间猜测身份。非法字段、非整数/不递减边界、数量与索引跨度不符均失败保留已有页，错误 HISTORY_INVALID；首批空记录 start=0 正常完成。旧 image 路径不进入文本，只保留 image 类型与 UUID；未知记录类型显式拒绝，不假装完整。取消/新登录令旧响应失效。

ChatSession 构造新增可选第四参数 history（默认 null 供不含历史的现有契约测试），正式应用注入 HistorySync。start 并行启动传输及历史；历史首批前 send_text 立即建立稳定本地 ID、status=waiting_history，至多 128 条、单包 8 MiB，保留未发正文；成功/跳过后顺序发送并显式映射网络 ID 到本地 ID。等待首批不消耗网络投递龄期；身份拒绝不重新发送。`get_history_state()`、`retry_history()`、`skip_history()` 为 UI 边界。已获取历史放在实时消息前，按 UUID 去重，实时天依正文优先；历史导入不触发声音/表情。stop 同时取消同步、清空排队与 ID 映射；get_state 含 history 子状态。ChatView 显示同步进度、首批/后续失败重试，只有首批失败提供跳过。

验证真实 loopback HTTP + WebSocket：首批延迟时消息尚未送达但可见、认证/心跳正常；固定分页边界、发送后后台页不重复最新历史、首批失败/跳过、后续失败重试、坏页/重复、取消/账号切换与无历史音频/表情。

## 日志窗口与应用生命周期

Application 在正常入口最早创建 ClientLog 并记录 client_started，退出树 finish；账户状态与发送/投递记录固定事件、数字和代码。`LogWindow(logger)` 是独立非模态 Window，`open()` 显示并聚焦已有实例；关闭仅隐藏，登录前菜单和主导航日志入口由 Application 打开同一实例。深色等宽终端按级别配色，默认完整当前启动记录，追加记录只追加一行，不反复重建。搜索、模块/级别筛选、历史启动选择、复制可见记录、暂停/恢复跟随；筛选或切换才重新读取。导出选定启动通过原生 FileDialog 选择 ZIP 路径，调用 ClientLog.export_run，失败显示错误，不导出筛选子集。

`EngineLogSink(logger)` 为 Godot Logger 实现，由 Application 注册/移除；仅记录错误类别与引擎错误次数，不保存原始错误消息、堆栈、源码路径或引擎输出，防止错误中夹带正文与凭据。引擎回调可能来自工作线程，经 call_deferred 在主线程写日志，退出后失效。账户和聊天的公开操作不得依赖日志成功。日志写盘失败在账户页/聊天页及日志窗口明确可见，不能只写回失败日志。

验证从实际 Application 登录前按钮打开日志窗口、重复聚焦、关闭后再开及当前启动可读；存储查询测试与窗口筛选/跟随测试不访问公共服务器。引擎错误日志不把人工制造错误计为 Green 命令失败。

## ClientLog 启动归档契约（替代旧三文件轮换）

构造 `ClientLog(directory="user://logs", legacy_max_bytes=2097152, environment=null)`，第二参数仅保留调用兼容、无截断效果。`record(event, fields={}) -> Error` 保留原有白名单与 UUID 哈希；新增安全 level/module 枚举及数字 count/status/index/duration_ms。事件限字母数字下划线，不能传正文；phase/code 只保留已知状态与错误码，未知值改为 UNKNOWN，不把任意服务器字符串当安全错误码。每条包含时间、相对启动毫秒、级别、模块、事件及固定中文说明；持续 flush。首次记录创建唯一 run ID（时间/PID/随机），当前内存记录不会因写盘失败丢失；`write_failed(error)` 明确报告失败，`entry_added(entry)` 供实时视图。

`get_run_id() -> String`、`list_runs() -> Array[Dictionary]`（id/started/pid/closed/active/complete）和 `read_entries(run_id="") -> Array[Dictionary]` 供日志窗口；空 ID 表示当前启动、返回副本。历史 ID 仅从归档目录枚举、安全校验，不接受路径。未知/损坏行跳过且 complete=false，不将损坏文件当完整。`finish()` 幂等写 client_stopped 并更新关闭标记；关闭后 record 拒绝。无结束标記的退出被标识未正常结束。

每次启动独立 jsonl 与 json 元数据，保留最近 50 次，清理仅删除该格式的完整启动文件；使用 PID 活跃检测保护其他仍在运行的实例，旧 client*.jsonl 不删除。`get_directory()` 保持可用。每条读写结果返回错误，记录存储是否完整；只记录允许的环境信息，不含路径、用户名或凭据。

`export_run(run_id, destination_zip) -> Error` 导出全部选定记录，固定条目 events.jsonl、readable.txt、environment.json，版本来自 release.json；不接受筛选参数、不覆盖已有文件、不上传。写盘失败或损坏记录在摘要 complete=false，禁止宣称完整。测试通过独立目录、重建实例、50 次边界、活跃保护、错误路径和 ZIP 读取验证公开结果。

## 版本化构建

`release.json` 为唯一版本来源：`product=agentluo, version=0.1.3`。`src/storage/release_info.gd` 的静态 `get_info() -> Dictionary` 返回副本，`title() -> String` 返回 agentluo + 版本。Application 原生窗口标题使用该值；不更改既有 user:// 目录。

`scripts/build.ps1 -Godot <path> [-OutputDirectory <root>] [-Package]` 默认构建至 dist/agentluo-<version>/agentluo.exe 和同名 pck。输出版本资源与 licenses；可选 Package 在 artifacts 下创建同名 ZIP，包含唯一顶层目录。已有 ZIP 时构建前失败，不覆盖；版本不自动递增。包内 DLL 保持导出引擎收集结果，不手工省略。构建仍检查锁定引擎版本、导出与独立启动，版本格式拒绝非三段数字。脚本与元数据属于构建配置切片，Red 不适用；实际导出、ZIP 条目与重复打包拒绝验证其行为。

## PcmStreamDecoder：增量 WAV 音频

原生 RefCounted 类，由注入的 DecoderFactory 在主线程创建；与 WindowsSecurity 共用扩展，无网络或文件副作用。

- `append(bytes: PackedByteArray) -> Dictionary`：首片及跨片头按 RIFF/WAVE 解析，随后按 data 区接收 PCM；支持未知 data 长度 0xFFFFFFFF。PCM 8/16/24/32 位及 IEEE float32，单/双声道，8000～192000 Hz；单声道复制为左右声道，输出归一浮点。支持对应完整 GUID 的 WAVE_FORMAT_EXTENSIBLE，拒绝压缩格式和其他声道数。
- `finish() -> Dictionary`：标记接收结束；空音频、残缺头、残缺帧或已知 data 长度不足报错。重复 finish 幂等，成功结束后 append 返回 STREAM_FINISHED 且不修改已完成数据。
- `read_frames(max_count: int) -> PackedVector2Array`：取走至多指定数量立体声帧，供 AudioStreamGeneratorPlayback.push_buffer；GDScript 不逐样本解码。
- `get_status() -> Dictionary`：ok/code/sample_rate/channels/bits/queued_frames/decoded_frames/input_bytes/finished。错误码 INVALID_WAV、UNSUPPORTED_FORMAT、TRUNCATED_AUDIO、EMPTY_AUDIO、BUFFER_LIMIT 为粘性错误并释放音频缓冲。
- `get_amplitude(frame_index: int) -> float`：返回指定绝对帧所在约 10ms 窗口的 RMS（0～1）；越界返回 0。调用方使用实际播放进度，不能以收包进度驱动口型。
- `get_waveform(buckets: int = 24) -> PackedFloat32Array`：成功 finish 后，按时间均分为 1～128 桶，各桶取原生 RMS 窗口峰值；不受 read_frames 消耗影响。未结束、失败、空音频或桶数非法返回空数组；极短声音覆盖的窗口可重复用于多个桶。

## AudioCache：按账户保存完整语音

`src/storage/audio_cache.gd` 是 RefCounted，构造 `(root="user://audio", logger=null)`；主线程通过 begin/append/commit 分块写文件，不解码样本。

- `set_scope(server, username) -> Error`：用 AccountApi.normalize_server 规范化地址，与账户一起 SHA256 隔离目录；切换前 abort_all，完整缓存保留。非法账户范围返回 ERR_INVALID_PARAMETER 并禁用缓存；目录不可写返回对应 Error。
- `begin(id) / append(id, bytes) -> Error`：非空 UUID 的 SHA256 为文件名；临时 .part 只写入当前流的原始 WAV/PCM 字节，不攒整段音频。最多 16 个在途文件；已有可用完整缓存 begin 返回 ERR_ALREADY_EXISTS 且不覆盖。append 单次上限 8 MiB，失败取消该临时文件。
- `commit(id, decoder_status, waveform) -> Error`：仅接受成功且 finished、正帧数及合法格式、24 个有限幅值的原生结果；校验字节数与已写数据一致。先关闭/重命名音频，再原子提交元数据作为完整标记。任何失败不公开部分流。原始流保留未知长度 WAV 头，后续必须交给 PcmStreamDecoder 重放，不假定普通 WAV 文件播放器可读。
- `lookup(id) -> Dictionary`：无可用缓存返回空字典；成功返回 path/sample_rate/channels/bits/frames/duration/waveform/bytes。元数据版本、范围、文件存在性和长度经验证，path 由本地命名构造，不信任文件中的路径。不开启或修改聊天正文存储。
- `abort(id)` / `abort_all()`：关闭并移除在途临时文件，幂等；`clear() -> Error` 删除当前范围内自有缓存文件，部分失败返回 Error，不跨账户、不递归删除任意文件。会话层负责先停止重放与阻止当前流再次缓存。

完整缓存仅 clear 手动删除，无容量/时间淘汰。set_scope 清理本目录未完成 .part/.json.tmp，不清理完整文件。记录 cache_committed/cache_error/cache_cleared，不记录账户或原始 UUID。验证独立临时目录中的跨实例恢复、隔离、未完成不可见、非法提交、文件损坏/不可写、清理及波形。

每次 append 上限 8 MiB，WAV 前置头累计上限 1 MiB，未读解码队列上限 128 MiB，单流时长上限 30 分钟。无效数值拒绝；未知辅助 chunk 按声明长度及偶数字节填充跳过。已知 data 结束后的尾部元数据不作为 PCM。每个 UUID 一个解码器，不猜测无头 PCM 中的采样率变化。

验证入口 tests/test_pcm_decoder.gd：跨片头/半帧、未知长度、正常 WAV、声道/采样率/位深、幅值、非法/空/残缺流及资源边界；真实加载 DLL。此接口只解码，不表示声卡已输出。

本文记录工程构建、角色显示与构图、离线视觉样板的公开契约。网络、媒体接口在对应切片中补充，未列接口不视为已实现；完成事实见开发进度。

## AvatarDriver：真实模型显示与控制

位置 `client_godot/src/avatar/avatar_driver.gd`，继承 `Node2D`。调用方为角色场景及后续媒体控制器。所有调用在 Godot 主线程执行；驱动独占插件对象，其他模块不得直接调用 gd_cubism。

| 调用 | 正常行为 | 失败行为 |
| --- | --- | --- |
| `load_avatar(model_path: String) -> Error` | 加载完整 model3.json 及资源，初始化表情、动作和口型；再次成功加载替换旧模型 | 文件缺失返回 `ERR_FILE_NOT_FOUND`；插件不可用返回 `ERR_UNAVAILABLE`；资源无效返回 `ERR_INVALID_DATA`；预检失败保留原模型 |
| `apply_expression(command: String) -> bool` | 接受现有中文命令或模型表情 ID；启动表情并更新基础口型 | 未加载或未知命令返回 false，保留当前表情 |
| `play_motion(group: String, index: int = 0) -> bool` | 播放已存在的动作，用正常优先级 | 未加载、未知动作或索引越界返回 false |
| `set_mouth_openness(value: float)` | 0～1 用作当前说话口型；负数释放覆盖，恢复当前表情的基础口型 | 未加载时无操作；大于 1 截断为 1 |
| `get_status() -> Dictionary` | 返回 `loaded`、`canvas_size`、`expression`、`motion_groups`、`mouth_openness`，供布局、可用性展示和验收 | 未加载时 `loaded=false`、canvas 零、列表为空 |

模型失败必须在 UI 提示，不能以静态头像冒充加载成功。默认表情为 `normal`。现有口型映射负值表示由表情保持，不强制写入负值。驱动在模型效果处理阶段叠加口型；不从独立线程更新模型。

触摸及视线行为以[反馈契约](feedback-012.md)为准；驱动不处理网络或音频解码。模型、映射及许可说明随工程打包，旧端资源不修改。打包包含 `.moc3`、JSON、纹理和插件动态库。

### 验证

`godot --headless --path client_godot --script res://tests/test_avatar_driver.gd` 从真实驱动入口验证：完整资源可加载；缺失入口被拒绝且不丢旧模型；表情命令可切换、未知命令无副作用；动作合法/越界；口型范围及恢复。插件缺失属于环境失败，不计 Red。另用真实 GPU 导出包检查透明、遮罩、物理和表情，headless 不代替画面验收。

## AvatarFraming：构图与本地保存

`src/avatar/avatar_framing.gd` 是 `RefCounted`，调用者为角色区域。公开 `zoom_by(factor)`、`pan_by(pixel_delta, panel_size)`、`reset()`、`get_transform(panel_size, canvas_size) -> Transform2D`、`save_settings() -> Error`、`load_settings() -> Error`，构造时注入 SettingsStore。

- 默认缩放倍数 1.2，位置为区域中心。倍数限制 0.6～2.4；位移保存为区域宽高比例，分别限制 -0.4～0.4。零尺寸区域不移动、不产生除零。
- 布局缩放基础值为区域对模型 canvas 的等比容纳；面板改变后仍保持保存的相对位置和比例，不保存像素绝对位置。
- 正缩放因子生效；零、负数、NaN、无限值拒绝且不改变状态。无效拖动同理。
- 重置恢复默认构图。通过 SettingsStore 保存当前缩放和归一位移，Godot 实现保留旧 ConfigFile 格式；文件写入错误返回 Error。加载缺失文件返回 `ERR_FILE_NOT_FOUND`，损坏或字段非法返回 `ERR_INVALID_DATA` 并保留现有构图；超界有限值截断到范围。
- 产品设置路径为 `user://avatar_framing.cfg`，它只包含本机窗口构图，不含账户数据。测试使用独立临时路径，不触碰用户配置。
- 角色区域滚轮缩放、右键拖动；左键不调整构图。拖动释放和滚轮操作后保存；保存失败给出可识别状态，不影响当前画面。最小化关闭角色绘制/更新，不暂停整棵场景树。

验证入口：`tests/test_avatar_framing.gd`，检查边界、跨尺寸恢复、重置、缺失/损坏配置与重新实例化后的恢复。构图存储不负责触摸上报或账户设置。

## OfflinePreview：可运行视觉样板

独立入口 `scenes/preview/chat_preview.tscn`，由当前开发启动场景装配，始终显示“离线样板 · 未连接服务器”；正式产品菜单不提供此入口。UI 只调用离线控制器和 AvatarDriver，完全不发 HTTP/WebSocket 请求。

`src/preview/demo_session.gd` 是离线样板控制器，继承 RefCounted，供样板 UI 和 headless 测试调用：

- `select_scenario(name: String) -> bool`：接受 `conversation/empty/disconnected/error/thinking`，替换模拟消息并重置模拟状态；未知名称返回 false 且保留数据。
- `get_messages() -> Array[Dictionary]`：返回深拷贝。消息包含 `id/role/text/status`，role 为 assistant/user/system，status 为 received/sending/sent/failed；可选 `image` 为本地资源路径。样例包括长短文字、图片和三种发送状态。
- `submit_text(text: String) -> String`：空白输入或断网/加载失败场景返回空 ID 且不修改消息；正常保留输入正文并追加 sending 消息，返回会话内唯一 ID。不假装得到服务端答复。
- `settle(id: String, success: bool) -> bool`：只将已存在的 sending 消息变为 sent/failed；未知 ID 或重复结束返回 false。
- `changed` 信号通知展示刷新；场景切换后旧 ID 的延迟回调不影响新消息。

视觉布局：原生标题栏、左45%角色、右55%聊天，分隔条可调并单独保存 `user://preview_layout.cfg`。角色沿用 AvatarPanel；浅色实底、青蓝用户气泡、左右头像；消息正文可选择。底部输入支持 Enter/Shift+Enter，IME 合成期间不发送。输入失败保留文字。新消息只在原来位于底部时自动跟随，否则显示“回到最新”。样板消息数有限，不承诺历史分页或千条虚拟列表。

图片样例通过共用图片窗口预览，支持缩放与关闭；样板可选择或粘贴单张图片，进入待发送预览，显式发送或取消。图片读取失败保留输入并提示，不写长期缓存。语音按钮只切换明确标注的模拟播放状态并驱动口型，无实际声音，不冒充流式音频验证。表情通过真实 AvatarDriver 切换。

验证：`tests/test_demo_session.gd` 检查空白拒绝、唯一 ID、正文保持、状态转移幂等、坏场景无副作用、场景切换旧回调隔离、读副本不泄露内部状态。实际导出截图核对气泡、真实模型、字体、分隔和底部输入。中文输入法与系统剪贴板需人工操作验收。

## WindowsSecurity：Windows 原生密码与秘密保护

位置 `client_godot/native/windows_security.cpp`，GDExtension 类 `WindowsSecurity`，继承 RefCounted；由 Windows 能力实现创建，经 PasswordEncryption/SecretProtection 向调用者提供统一接口。只使用 Windows CNG/Crypt32，不启动外部进程，不访问磁盘或网络。

所有调用返回 `{ok: bool, data: PackedByteArray, error: String}`；成功 error 为空，失败 data 为空，错误码不包含输入内容。

- `encrypt_password(public_key_pem: String, password: String) -> Dictionary`：接收服务端 `/auth/public_key` 的 SubjectPublicKeyInfo PEM 和 UTF-8 密码，返回 RSA-OAEP 密文字节；OAEP 与 MGF1 均 SHA256，label 为空。调用方用 Base64 编码填入既有 password/new_password 字段。RSA 至少 2048 位，最大 8192 位；公钥字符串不超过 16 KiB；明文字节超出当前 OAEP 上限时返回 `INVALID_INPUT`。无效公钥 `INVALID_KEY`；CNG 失败 `ENCRYPTION_FAILED`。不使用 SHA1 降级。
- `protect_secret(plain: PackedByteArray, scope: PackedByteArray) -> Dictionary`：当前 Windows 用户 DPAPI，禁止交互提示；scope 为规范化服务器/账户标识派生的额外熵，不能跨 scope 解密。plain 与 scope 各 1～65536 字节；失败 `INVALID_INPUT` 或 `PROTECT_FAILED`。
- `unprotect_secret(cipher: PackedByteArray, scope: PackedByteArray) -> Dictionary`：相同用户及 scope 下恢复字节；篡改、不同 scope 或不同用户返回 `UNPROTECT_FAILED`，绝不降级为明文。cipher 最大 128 KiB，scope 同上。

C++ 临时明文缓冲在释放前清零；Windows 句柄和 DPAPI 输出无论成功失败都释放。GDScript 调用者仍负责及时释放自己的密码/密钥引用。此接口只转换字节，原子落盘、自动登录策略和 API key 明文选择由后续存储/业务接口承担。

验证：Godot headless 从 ClassDB 创建真实扩展，验证 DPAPI 往返、不同 scope/篡改拒绝、空值及上限；Python 临时测试进程生成密钥，用仓库 `account.py::decrypt_password` 解密 Godot 产生的 ASCII/中文/边界密码密文，并确认相同明文的密文不同。不使用生产密钥或真实凭据。扩展未加载属于环境失败，不计 Red。

## AccountApi：异步账户请求

位置 `src/network/account_api.gd`，继承 Node；组装根通过构造函数注入 PasswordEncryption 和超时（默认 15 秒）。UI/账户控制器通过 `request(operation, server, fields) -> Dictionary`（异步）调用；公开 `cancel()` 取消当前操作；纯 `ServerAddress.normalize(address) -> String` 规范化地址。单实例同时只执行一个操作，第二次调用返回 `BUSY`。

返回统一 `{ok: bool, code: String, status: int, data: Dictionary}`；成功 code 为 `OK`、data 为校验后的账户结果。失败 code 为 `INVALID_INPUT/BUSY/CANCELLED/TIMEOUT/NETWORK_ERROR/INVALID_RESPONSE/PUBLIC_KEY_ERROR/ENCRYPTION_ERROR/HTTP_ERROR/AUTH_REJECTED`；status 为 HTTP 状态，无响应为 0。错误不回显请求字段或未经处理的响应正文；UI 根据 code/status 显示明确反馈。未登录成功前不发布会话。

| operation | fields | 既有协议与成功字段 |
| --- | --- | --- |
| login | username,password,request_token(bool) | GET /auth/public_key 后 POST /auth/login；user_id/login_token/message_token 均为非空 String |
| register | username,password,invite_code | GET 公钥后 POST /auth/register；非空 message/user_id |
| reset | invite_code,new_username,new_password | GET 公钥后 POST /auth/reset_account；非空 message/username |
| auto_login | username,token | POST /auth/auto_login；非空 user_id/login_token/message_token |

- 每次密码请求重新获取公钥，避免服务端重启/切换服务器后缓存错钥；不裁剪用户名或密码。只发送当前操作需要的字段，不透传未知字段。密码由原生层加密，再 Base64 编码。
- 地址首尾空白和尾部 `/` 去除；无协议补 https；scheme/host 小写、默认端口去除，保留可选路径前缀。仅接受 http/https、合法端口、域名/IPv4/方括号 IPv6；拒绝 userinfo、query、fragment、反斜杠及路径内空白。无效返回空串。TLS 始终校验证书，不跟随重定向。
- HTTPRequest 异步执行，单响应最多 64 KiB；JSON 非对象、缺字段、字段类型错误或 token 为空均返回 INVALID_RESPONSE。鉴权 401 返回 AUTH_REJECTED，其他非 200 为 HTTP_ERROR；公钥响应非成功为 PUBLIC_KEY_ERROR（取消/超时保持原错误）。无自动重试，防止账户写操作重复。
- cancel() 可重复；取消公共密钥获取或提交后都结束等待，并使迟到回调不再建立会话。退出树也取消。此模块不保存 token、不触发 WebSocket、不写日志或本地配置。

验证 `tests/test_account_api.gd` 与本地 Python HTTP 测试服务：真实 CNG 加密可解密、四种字段转换、401/503、错误公钥/JSON、空 token、超时、取消、并发拒绝、地址规范化与服务器切换。测试绑定 127.0.0.1 随机端口，不接生产服务。

## CredentialStore 与 AccountSession：账户生命周期

`src/storage/credential_store.gd`（RefCounted）由 SecretProtection 和根目录（默认 `user://accounts`）构造；只接受已规范化的 server 和非空 username。作用域是 JSON `[server, username]` 的 SHA256，目录及 DPAPI entropy 均由此派生。

- `save(server, username, token) -> Error`：仅保存 DPAPI 保护后的 login_token，先写临时文件再原子替换；失败返回错误，不保存明文、不读取旧端数据。
- `read(server, username) -> Dictionary`：返回 `{ok, code, token}`，成功 token 为解密后的字符串；缺失 NOT_FOUND，损坏/无法解密 UNAVAILABLE，失败 token 为空。
- `forget(server, username) -> Error`：删除指定作用域自动登录凭据；缺失视为成功。媒体缓存不受影响。

账户生命周期和登录资料以[0.1.3契约](release-013.md)为准。

## ReliableOutbox：消息投递队列

位置 `src/network/reliable_outbox.gd`（RefCounted），调用方为 WebSocketTransport。时钟以调用参数的单调毫秒值注入，测试不用真实等待。

- `enqueue(type, payload, durable, now_ms) -> String`：分配稳定 client_msg_id 并复制 payload；上限 128 个在途事件，单包 UTF-8 JSON 不超过 8 MiB，拒绝返回空串。packet 顶层含 type/payload/client_msg_id/ts/reply_to。durable 用于 user_text（含 proactive）、user_image；typing/touch/image selecting/cancel 为瞬时事件。
- `take_ready(now_ms, connected) -> Array[Dictionary]`：先处理到期，再返回可以发送的包；持久消息按入队顺序最多一条等待 ACK，瞬时事件独立发送，不阻塞持久队列。未连接时瞬时事件丢弃；持久事件保留到重连或到达龄期。
- `acknowledge(reply_to, payload, now_ms)`：旧格式无 ok:false 视为成功；负 ACK 仅 retryable 严格 true 时重试。成功或终止后忽略重复 ACK、未知 ID。收到 ACK 前已经发送过的消息，即使正在退避也可接受确认。
- `disconnected(now_ms)`：将已发未确认的持久事件安排重试，瞬时事件丢弃。`stop(code="TRANSPORT_STOPPED")`：结束全部在途事件并释放 payload；不可在重新登录后继续发送旧账户的事件。
- `delivery_changed(id, state, code)`：queued/sending/sent/failed/uncertain；失败未知送达使用 uncertain + DELIVERY_UNCERTAIN，不自动生成新 ID。

ACK 超时 10 秒，图片选择/取消为 5 秒。持久消息首发后最多重试 8 次，退避 1/2/4/8/16/30/30/30 秒；若排队龄期达到 240 秒或下一次重试将达到龄期上限，即结束为 DELIVERY_UNCERTAIN。正常 NACK 的 code 只保留字符串错误码，不传原始 message 给日志。瞬时事件不重试。依据 client/src/delivery_policy.py 及 ws_transport.py。

验证 `tests/test_reliable_outbox.gd`：成功/旧格式/重复 ACK，非重试 NACK，ACK 丢失和可重试 NACK 保留 ID，重试与龄期边界，瞬时事件不挡文本，断线和显式停止。

## WebSocketTransport：认证连接与事件传输

`src/network/websocket_transport.gd` 为 Node，由应用创建并注入单调毫秒时钟 Callable（默认 Time.get_ticks_msec）。拥有 WebSocketPeer 和 ReliableOutbox，在主线程逐帧 poll；不阻塞 UI，不保存凭据，不写原始网络日志。

- `start(session: Dictionary) -> Error`：接受 server/username/message_token；规范化 HTTP(S) 地址为 WS(S) 的 `/chat_ws`，保留路径前缀。无效输入返回 ERR_INVALID_PARAMETER；启动替换旧连接和投递队列。连接后发送 `user_auth`，使用 message_token 和 capabilities:[negative_ack_v1]；只有 `auth_ok` 才进入 ready，`system_ready` 本身不算认证成功。
- `send_event(type, payload, durable=false) -> String`：通过 ReliableOutbox 返回稳定 ID；ready/connecting/authenticating/reconnecting 可接受，idle/auth_rejected 拒绝返回空串。持久消息可等待重连；瞬时事件离线终止。UI 仍经消息控制器调用，不直接生成协议包。
- `get_state() -> Dictionary` 与 `state_changed(state)`：返回 phase（idle/connecting/authenticating/ready/reconnecting/auth_rejected）和 code，不含身份秘密。`delivery_changed(id,state,code)` 转发投递状态；`event_received(event)` 交付已校验 type/payload 的业务事件；`system_error(code)` 只报告错误码，不把 error 伪装角色消息。
- `stop()`：关闭 socket、清理内存凭据、终止队列及心跳；重复调用安全，退出树自动调用。后续显式 start 可使用新的会话。
- 明确 `auth_error` 或认证期 `error` 后停止同凭据自动/手动重连，以规范化服务器/用户名/token 的 SHA256 指纹记住拒绝；相同凭据 start 返回 ERR_UNAUTHORIZED，更新凭据才可继续。不把临时网络断开当鉴权拒绝。
- 连接期限 8 秒、打开后认证期限 5 秒；断开/超时按 2/4/8/16/30 秒退避，认证成功后复位。ready 后立即心跳，之后每 10 秒 hb_ping（ping_id 递增）；hb_pong 不产生角色事件，沿用旧端无独立 pong 超时规则。
- `server_ack` 按顶层 reply_to 交给 outbox；包大小上限 8 MiB，二进制帧、非对象 JSON 或缺少 type/payload 对象视为 INVALID_RESPONSE 并断线重连。TLS 使用 Godot 默认验证；每帧最多处理 64 包，防止网络洪峰独占界面。

验证：本地 Python websockets fixture + 真实 Godot WebSocketPeer；检查 URL、user_auth/message_token/capabilities、auth_ok、立即心跳、ACK/业务事件、连接断开后同 ID 重试、拒绝凭据不重连、更新凭据恢复、认证超时、退出清理；单调时钟注入用于加速退避和心跳，不访问生产服务。

认证阶段收到 WebSocket 关闭码 1008 同样视为 AUTH_REJECTED，禁止同凭据重连；这是服务端认证期限/尝试次数耗尽的实际关闭语义。Godot peer 在同次 poll 收到最终数据帧与关闭帧时可能已清空入站队列，因此不能仅依赖最后一帧 auth_error；普通关闭与 1013 仍按网络退避处理。

## ChatSession 与 ChatView：真实文字聊天

`src/session/chat_session.gd`（Node）由真实 WebSocketTransport 构造并拥有其生命周期；应用在账户 signed_in 时调用 `start(account_session) -> Error`，退出或账户切换调用 `stop()`。UI 使用下列接口，不发送协议包：

- `send_text(text) -> String`：拒绝纯空白/未登录，正常保留正文，发送 user_text，llm_mode.types 默认空列表；返回网络的稳定 ID，立即产生 user 消息，不等待回复。重连期间可排队；无法入队返回空串且保留输入。
- `get_messages() -> Array[Dictionary]` 返回深拷贝；消息含 id/role/text/status/code（queued/sending/sent/failed/uncertain 或 received）。投递状态更新原消息，不增加气泡；DELIVERY_UNCERTAIN 明确显示“无法确认送达”，不提供换 ID 自动重发。
- `get_state() -> Dictionary` 与 `state_changed(state)` 提供连接 phase/code、thinking 和系统提示；`changed` 表示消息内容/状态改变；`expression_requested(command)` 由应用连接 AvatarDriver。stop 关闭传输并清空消息、回复 UUID 和账户状态，不泄漏给下一账户。
- 接收 agent_state_changed 的 thinking/waiting；agent_message 按 payload.uuid 合并。重复分片不增加气泡，非空 text 更新同 UUID 的正文，空尾包不清文字；display_in_chat=false 不出气泡，is_ephemeral 保留显示语义且禁止该流持久缓存。
- 按 UUID 首次到达顺序展示文本/表情/声音，前一回复实际播放结束前后续回复暂存；is_final_package 表示接收结束，实际播放结束才推进下一句。audio_error 保留文字并结束声音。断线释放未完成回复等待及播放器，保留已显示文字。
- 无效回复（缺 uuid/text 类型错误）只产生安全系统提示；网络 error/auth_error 不进入天依消息。重复终止包忽略，不重放表情。

## ReplyAudio：实际流式播放

`src/media/reply_audio.gd` 为 Node，由组装根创建，构造参数 `(logger=null, clock=Callable(), cache=null, decoder_factory=null)` 可注入 ClientLog 与返回单调毫秒的时钟（默认 Time.get_ticks_msec，测试可控）；ChatSession 构造可接收第三个参数 media，未传则创建缺少解码能力的 ReplyAudio；正式组装显式注入真实工厂。媒体拥有 AudioStreamPlayer/Generator 与每 UUID 的 PcmStreamDecoder，不直接改变气泡或角色。

- `append_reply_audio(id, encoded, final, audio_error=false, ephemeral=false)`：接收每包 Base64 字符串，先解码/缓存。空音频可用于文字回复及终止；坏 Base64、原生失败、服务端 audio_error 产生可识别错误，保留聊天文字，不落盘部分流。
- `play_reply(id)`：允许一个活跃 UUID；可在首片到达后调用，约 80ms 预缓冲或 final 后自动开始实际播放。后续 UUID 先解码，等待会话按顺序调用；每 UUID 采样率来自 WAV，由 Godot 混音器重采样。
- `receive_finished(id, code)` 表示接收结束；`playback_finished(id, code)` 表示播放器排空并等待输出延迟后结束或中断，两者各一次；`mouth_changed(value)` 为实际消耗帧对应 RMS（适当放大截断至 0～1），停止为 -1 恢复表情基础口型。
- `get_state()` 返回 active_id/playing/queued/volume；`state_changed(state)` 通知变化。`set_volume(value)` 接受有限 0～1 并截断；默认 1。`stop_current()` 中止当前声音，后续同 UUID 继续解码验证与缓存，丢弃待播放帧；仍接收文字/终止直到推进下一句；`reset()` 释放全部流，无旧账户完成回调，重复安全。
- 最多 16 个待处理 UUID，累计未读解码帧上限 128 MiB；60 秒未收到续片则 AUDIO_TIMEOUT，恢复队列。格式/容量错误、退出、断线均释放未完成资源。process_mode=ALWAYS，不随角色最小化停绘而暂停声音。
- 记录 audio_received（字节数）、audio_format（格式）、audio_decoded（帧数）、audio_receive_finished、audio_playback_started、audio_playback_finished、audio_underrun 及 audio_error。日志只含安全元数据，不能声称实际扬声器听感已验证。

ChatSession 公开 set_volume/get_audio_state/stop_voice，转发媒体 mouth_changed 信号给组装根；get_state 追加 speaking 布尔值。UI 显示播放/错误状态；停止只影响当前声音，后续回复默认仍自动播放。音量使用现有窗口配置保存，拒绝非法配置值。隐藏回复仍播放；临时回复不写缓存。完整音频缓存及重放契约如下。

验证 tests/media/test_reply_audio.gd 用真实原生解码/AudioStreamGenerator，AudioEffectCapture 观察非零输出及静音/停止；loopback WebSocket 到 ChatSession 验证分片、顺序、隐藏、坏流和断线。默认只用合成音频，实际 Windows 音频驱动另跑并记录，不连接生产服务。

## 完整语音重放与消息控件

ReplyAudio 由 Application 注入 AudioCache，缺少 cache 的既有调用保留在线播放。ChatSession.start 按 server/username 设置范围；stop 关闭范围，断线 reset 仅取消在途流与重放，保留范围及已完成缓存。以下接口为本轮重放切片契约：

- `set_scope(server, username) -> Error`：先 reset，再设置缓存账户范围；空值关闭范围。存储失败不阻止聊天及在线声音。
- `get_message_audio(id) -> Dictionary`：返回 available、duration、waveform（24 个真实幅值）、status（idle/playing/paused）、position（秒）、blocked（在线正在输出）、code；不向 UI 返回磁盘路径。未完整提交不可重放；缓存失败 code=CACHE_WRITE_FAILED。
- `replay(id) -> Error`：在线正在输出返回 ERR_BUSY；没有有效缓存返回 ERR_DOES_NOT_EXIST；同一正在播放 UUID 幂等；另一 UUID 停止旧声并从头开始。分块读取原始缓存交给 PcmStreamDecoder，错误终止并报告 REPLAY_FAILED。
- `pause_replay()` / `resume_replay()` / `stop_replay()`：幂等；暂停冻结混音与进度，继续从原位置，停止/自然结束回 idle、position=0；每次再播放从头开始。不提供寻址接口。
- `clear_cache(older_than_days=0) -> Error`：停止本地重放；0表示全清并取消在途缓存，正数按天清理且保留接收中缓存；在线声音继续，仅清理当前账户。失败报告 CACHE_CLEAR_FAILED，重新查询实际可用性。
- `message_audio_changed(id, state)`：缓存结果及约 20Hz 的实际重放进度定向通知，不触发聊天 changed。在线输出开始/结束同时通知已有音频控件 blocked 变化。`replay_finished(id, code)` 独立于仅在线使用的 playback_finished，绝不推进在线回复队列。

成功终止包、原生 finish 成功、文件提交成功三个条件同时满足才提供 available。临时标记为粘性，错误/断线/退出 abort 临时文件。写盘失败不影响解码/声音；现有完整缓存退出保留，无自动淘汰。在线实际开始输出时同步抢占播放或暂停的重放。所有嘴型按实际消耗帧，暂停/结束为 -1；重放不发出表情命令。日志增加 replay_started/replay_paused/replay_resumed/replay_stopped/replay_finished/replay_preempted，沿用白名单与 UUID 哈希。

ChatSession 公开同名 get_message_audio/replay/pause_replay/resume_replay/stop_replay/clear_cache 及 message_audio_changed；仅允许当前显示的 assistant 消息发起 replay，不接受任意路径。清理失败通过系统状态报告。UI 只调用 ChatSession。MessageBubble 提供 `set_audio_state(state)`、`audio_action(action)`（play/pause/resume/stop），只更新独立音频行，不重建气泡或设置正文。完整语音行显示重放、时长和非交互波形；播放/暂停时显示进度与停止。不可用时隐藏控件，保存失败显示“语音未能保存”。设置缓存页清理须经场景确认框确认，取消不调用 clear_cache。

验证 tests/test_voice_replay.gd 从 ReplyAudio 观察真实混音、暂停进度、恢复、停止/切换、自然结束、抢占、终止后缓存、临时/错误/写盘失败、清理抑制与跨实例恢复；loopback test_voice_chat.gd 从 ChatSession 与可见控件验证按钮、消息不重复、表情不重发、文字选择不被进度刷新破坏。默认只用合成声音，WASAPI、真实服务听感分别记录。

## ModelExecutor：异步非流式模型委托

`ModelExecutor(settings,logger=null,timeout=120)` Node，`start()` 开始当前账号执行代次，`stop()` 取消所有请求、清空请求 ID 去重和结果，不发迟到响应。`submit(payload)` 接收现有 llm_request，`completed(response)` 产生 request_id/content/usage 或 request_id/error；重复 ID 不再次调用供应商，完成后可重发同一结果。在当前登录保留 ID 集，最多 4096 个不同委托、8 个并发，容量满返回 MODEL_BUSY 而不遗忘旧 ID。`enabled_types()` 转交当前有效用途列表。

执行先检查用途启用、kind、JSON/thinking 能力，校验 prompt/params/flags/image 字段；使用提交时配置深拷贝。OpenAI 兼容 POST Base URL/chat/completions，非流式、Bearer API Key、120 秒、不自动重试。默认 max_tokens=4096/temperature=0.7/top_p=0.9，再覆盖服务端 params、再本地 params，最后锁定 model/messages/stream=false；thinking 与 JSON 请求强制对应参数。stream=true/非 bool 或 stream_options 拒绝。文本为 system prompt，图像为 user text+image_url detail=auto；校验 choices[0].message.content 为字符串，JSON 请求必须是可解析 JSON；供应商错误正文不回显，只回传识别码，usage 只保留数字 token 统计。

`test_config(type_id,config)` 异步返回 ok/code，纯配置校验后使用固定短输入调用同一执行路径，结果不含生成正文；不改变运行配置、不发送聊天历史。ModelPage.setup(settings,executor=null) 提供手动测试按钮，明确可能消耗额度且默认取消，确认才调用；退出账号取消测试。设置窗口关闭遵循统一草稿确认，执行中的测试使用快照。ChatSession 构造增加可选 models 执行器（由 ChatSession 持有），登录 start、退出 stop；llm_request 分派，completed 以 llm_response 瞬时事件回传；user_text 的 llm_mode.types 来自执行器，历史屏障释放也遵守此规则。

测试从真实 loopback HTTP 供应商和 WS 观察文本/VLM、参数保护、重复请求只调用一次、JSON 失败、安全错误、超时、取消与在途配置快照；日志只记阶段/耗时/安全代码及哈希用途 ID，不记录提示词/输出/密钥。

## DynamicsController：动态读取、分页及手动已读

`DynamicsController(logger=null,timeout=15)` Node，由 Application 持有，`start(session)` 查询未读并每30秒重查；`stop()` 取消请求、清空账号数据并隔离旧代回调。`get_state()` 返回 phase/code/unread/unread_code/has_more/busy；`get_posts()` 返回副本，`get_comments(id)` 返回 items/has_more/busy/code/loaded。`changed` 用于列表/评论，`unread_changed(count)` 单独通知徽标；未读轮询不自动刷新列表、不清草稿、不标已读。

`refresh()` 加载首批10条，`load_more()` 使用服务端不透明 next_cursor；`load_comments(id,more=false)` 每页20条。GET /dynamics、/{id}/comments、/unread 使用 username query + Bearer message_token；对 cursor URI 编码。校验分页字段及显示字段、ID 去重，拒绝不前进/空的有后续页；失败保留已显示内容及原 cursor，可重试。刷新不自动标已读。`refresh_unread()` 失败保留原数量；`mark_read()` 只有 POST /dynamics/read 返回 ok=true 后清零，忙碌轮询期间不提交，避免旧响应覆盖结果。

只保存内存列表/评论，不新增正文数据库。服务端负责私有动态/评论隔离；客户端只展示当前账号返回数据。日志只记录安全阶段/错误/数量。测试使用本地 HTTP 的10/20条边界、分页去重/异常、未读失败保留、显式标读、取消与重新登录。

## 动态写入与非模态窗口

DynamicsController 新增 `publish(content)`、`comment(id,content,parent_comment_id="")`，异步返回 ok/code；空文本拒绝；评论必须属于已加载且允许评论动态，回复目标必须属于已加载的该动态评论。POST 使用既有 content/parent_comment_id 字段；无幂等键、不自动重试，单个写请求在途返回 BUSY。超时显示可能已发送，保留草稿由用户核实后自行重试。成功响应 item 校验后插入内存列表/评论，不自动标已读；其他分页边界保留。退出返回 CANCELLED、不能影响新账号。

## 角色资源描述与稳定身份

AvatarDriver 增加 `load_character(descriptor_path) -> Error`；描述是当前随包 JSON，包含 character_id/resource_id/model_path/mapping_path 四个非空字符串。稳定身份 luotianyi 与具体 original 模型资源分离；模型自身 Cubism FileReferences.Motions/HitAreas 提供动作及命中区域资源映射，mapping_path 提供表情及基础口型映射。描述/映射/模型预检和插件候选加载全部成功后才替换当前角色；失败保持原模型/表达/身份。`get_status()` 增加 character_id/resource_id，原 load_avatar(model_path,mapping_path=默认映射) 兼容原测试与样板，不宣称换装 UI 或触摸业务已新增。

## UnifiedDropdown：统一选择器与动作菜单

`UnifiedDropdown` 场景继承 Button，action_menu 默认 false。`set_items(items:Array)->Error` 接收{id:String,label:String,disabled?:bool}及{separator:true}，非空ID唯一，非法整批拒绝；返回副本的 `get_items()` 用于状态观察。`set_selected_id(id)->bool` 静默选择有效启用项；`get_selected_id()->String`。更新列表保留仍有效的选择，否则选择首个启用项；动作模式不改按钮标题。`set_item_enabled(id,enabled)` 更新禁用状态。用户鼠标/键盘选择发出 `activated(id:String)`，选择器先更新选择再通知；代码设置选择不发通知。

`open_menu()`、`close_menu()`、`is_menu_open()` 管理展示，disabled按钮不展开。弹层白底圆角10、细边轻阴影、约42px行高，浅灰悬停、主题蓝焦点和选中标记。嵌入弹层限制在所属视口可见区域内，优先向下、空间不足向上，长列表滚动。方向键跳过禁用项与分隔线，Enter选择、Esc/点外部关闭；父窗口移动/调整/最小化/关闭自动收起。弹层内部由组件拥有，页面不操作PopupMenu对象。


## 0.1.1 动态完整刷新
DynamicsController.refresh_comments(id) 异步从第一页按20条读取到末页，期间 busy=true 禁止同动态分页/写入；所有页校验完成才原子合并已有评论（保留本次已成功提交的评论），按时间排序。失败保留内容与原分页游标、code可重试；取消及跨账号旧响应不生效；重复游标循环为INVALID_RESPONSE。每次请求沿用既有超时。refresh() 首页新动态优先合并此前列表，保留已选择的旧动态，分页仍用最新首页游标去重。publish/comment 成功返回新增 item_id，失败返回空 item_id；不改变服务端协议。测试从真实HTTP验证末页、失败保留及取消。
