# Godot 客户端 interface

## ModelStore 与 ModelSettings：按用途的本地模型配置

`ModelStore(security,root="user://models")` RefCounted：`set_scope(server,username)`、`read(type_id) -> Dictionary`、`save(type_id,config,allow_plain=false) -> Dictionary`。目录按规范化服务器/账户哈希，用途文件按 type_id 哈希；只保存 enabled/provider/base_url/model/model_kind/model_capabilities/params 与受保护 api_key。DPAPI entropy 包含服务器/账号/用途；保护失败返回 PLAINTEXT_CONFIRMATION_REQUIRED，只有调用方明确 allow_plain 才写 api_key_plain，不自动降级。原子文件写入；解密失败 config 禁用并返回 KEY_UNAVAILABLE，不冒充空密钥成功。

`ModelSettings(http,store,logger=null)` Node：`start(session)` GET /llm/client-model-types，类型字段 id/name/description/model_kind/requires_json/requires_thinking 校验、ID 唯一。`get_types()`、`get_config(type_id)` 返回副本；`get_state()`/changed 只含 phase/code/count，无密钥；`validate(type_id,config) -> Dictionary` 做纯本地校验；`save(type_id,config,allow_plain=false)` 校验再持久化，成功才替换运行配置；`enabled_types() -> Array[String]` 只广告当前定义内启用且有效用途；`copy_config(source_config,target_id)` 保留目标 kind 与能力要求、返回草稿且重新校验后方可保存。未知用途拒绝。

配置 enabled/provider/base_url/api_key/model/model_kind、model_capabilities.can_use_json/can_enable_thinking、params Dictionary；Base URL 只接受 HTTP(S) 规范化地址，不额外添加 v1。启用时要求 model/key/base_url 非空、kind 匹配和满足要求；params.stream 仅允许 false，拒绝 stream_options，model/messages 参数不能覆盖实际模型与委托正文。保存不发供应商请求。`stop()` 取消类型读取并清空本账号内存配置，不删除文件。

模型设置窗口按动态用途生成表单，保留 JSON 高级参数，切用途保留草稿，可复制其他用途；API Key 遮蔽。保存失败不丢草稿，DPAPI 失败弹明确明文选择，默认取消。窗口继承 DraftWindow、参与统一退出保护；当前 ChatView.settings_requested 增加 kind=models。测试真实 DPAPI/跨实例隔离、保护失败默认不落盘、动态用途、能力/kind 校验和复制不覆盖目标要求；默认不调用收费供应商。

## 相处偏好与设置窗口退出保护

`JsonRequest(timeout=15,limit=8MiB)` Node 的 `send(url,method,data={},headers=[]) -> Dictionary` 异步返回 ok/code/status/data，单实例忙碌返回 BUSY；JSON 必须对象、禁止重定向、TLS 默认验证、无自动重试、错误不回显正文。`cancel()` 结束等待且迟到回调失效。它只承担 HTTP 外部边界，不读取会话或供应商配置。

`PreferencesController(http,logger=null)` Node 拥有请求器。`start(session)` 加载现有 POST /preference/get；`reload()` 仅非忙碌且无草稿时重试；`edit(fields)` 接受 relationship/speaking_style/personality_text/custom_context 四个字符串；`save()` 在加载成功后重读服务器，比较加载后的表单，仅合并用户修改字段，再 POST /preference/overwrite `{username,token,preferences}`。关系 朋友 和风格 活泼可爱 保存空值；canonical personality_traits 数组优先读取，旧 #sym:personality_text 回退；关键词按中英文逗号/顿号/换行拆分，去空并保序，修改性格后同时写两个字段。未知字段和未修改字段保留服务器最新值。成功响应 status=success 才更新基线；加载失败不可保存、保存失败保留草稿。`get_state()` / changed 提供 phase/fields/can_save/dirty/code；`stop()` 取消并清空秘密/草稿，不落盘正文。

`PreferencesWindow(controller)` 非模态，编辑预设和自定义四项，保存/重试及明确状态，不在加载失败时显示可保存默认值。`is_dirty()` 供统一退出保护；窗口关闭默认取消的放弃确认，确认才关闭。Application 维护独立窗口实例，重复打开聚焦；关闭窗口/退出账号/退出程序使用同一草稿检查原则。正常应用关闭先确认，再释放控制器和日志。测试使用真实 loopback HTTP 确认重读合并、默认空值、旧性格兼容、失败保留草稿和取消。

窗口共享 `DraftWindow` 基类：`is_dirty() -> bool` 由具体窗口实现，`open()` 显示聚焦；关闭有草稿时显示默认取消的 ConfirmationDialog，确认后释放窗口（从而释放其草稿）。ChatView.settings_requested(kind) 交给 Application 打开页面；当前 kind=preferences。应用统一退出确认同样默认取消，确认后关闭所有独立设置窗口，再执行退出账号/程序。

## HistoryImages：按可见 UUID 恢复图片

`HistoryImages(root="user://images",logger=null)` Node，`start(session)` 规范化服务器/账户隔离本地文件并取消旧请求；`stop()` 清除内存及取消网络，完整文件保留。`ensure(id)` 在 UI 可见请求时读取缓存、缺失或损坏则 POST /get_image `{username,token,uuid}`；最多 3 个并发请求、15 秒超时、16 MiB 响应上限、禁止重定向，不使用历史 content 路径或 update_image_client_path。PNG/JPEG/WebP 解码成功才可用，限制 8192 边长、1600 万像素；缩略图最长边 480，本地缓存原图供预览。

`get_state(id)` / `changed(id,state)` 返回 status（idle/loading/ready/error）、texture（缩略图或 null）、code；`retry(id)` 显式重试失败，网络无自动重试；`preview(id) -> Texture2D` 从本机已验证文件恢复原图，失败返回 null。文件提交失败仍显示本次图片、报告 CACHE_WRITE_FAILED。内存仅保留最近 24 张缩略图、活动请求/可见控件可持有引用；不淘汰完整图片磁盘文件。退出的迟到请求不产生新账号状态。

ChatSession 构造第六参数 images 可选；提供 `request_message_image(id,retry=false)`、`get_message_image(id)`、`preview_message_image(id)` 及 message_image_changed，只对已显示 type=image 的消息生效。UI 不读图片文件。VirtualMessageList.set_image_state 定向更新气泡的缩略图/加载/重试，点击已有图片通过会话取得原图并打开现有 ImageOverlay。历史语音继续通过消息 UUID 查询已注入 AudioCache，不自动播放或下载。

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

Application 在正常入口最早创建 ClientLog 并记录 client_started，退出树 finish；账户状态与发送/投递记录固定事件、数字和代码。`LogWindow(logger)` 是独立非模态 Window，`open()` 显示并聚焦已有实例；关闭仅隐藏，登录前按钮和 ChatView.log_requested 信号由 Application 打开同一实例。深色等宽终端按级别配色，默认完整当前启动记录，追加记录只追加一行，不反复重建。搜索、模块/级别筛选、历史启动选择、复制可见记录、暂停/恢复跟随；筛选或切换才重新读取。导出选定启动通过原生 FileDialog 选择 ZIP 路径，调用 ClientLog.export_run，失败显示错误，不导出筛选子集。

`EngineLogSink(logger)` 为 Godot Logger 实现，由 Application 注册/移除；仅记录错误类别与引擎错误次数，不保存原始错误消息、堆栈、源码路径或引擎输出，防止错误中夹带正文与凭据。引擎回调可能来自工作线程，经 call_deferred 在主线程写日志，退出后失效。账户和聊天的公开操作不得依赖日志成功。日志写盘失败在账户页/聊天页及日志窗口明确可见，不能只写回失败日志。

验证从实际 Application 登录前按钮打开日志窗口、重复聚焦、关闭后再开及当前启动可读；存储查询测试与窗口筛选/跟随测试不访问公共服务器。引擎错误日志不把人工制造错误计为 Green 命令失败。

## ClientLog 启动归档契约（替代旧三文件轮换）

构造 `ClientLog(directory="user://logs", legacy_max_bytes=2097152)`，第二参数仅保留调用兼容、无截断效果。`record(event, fields={}) -> Error` 保留原有白名单与 UUID 哈希；新增安全 level/module 枚举及数字 count/status/index/duration_ms。事件限字母数字下划线，不能传正文；phase/code 只保留已知状态与错误码，未知值改为 UNKNOWN，不把任意服务器字符串当安全错误码。每条包含时间、相对启动毫秒、级别、模块、事件及固定中文说明；持续 flush。首次记录创建唯一 run ID（时间/PID/随机），当前内存记录不会因写盘失败丢失；`write_failed(error)` 明确报告失败，`entry_added(entry)` 供实时视图。

`get_run_id() -> String`、`list_runs() -> Array[Dictionary]`（id/started/pid/closed/active/complete）和 `read_entries(run_id="") -> Array[Dictionary]` 供日志窗口；空 ID 表示当前启动、返回副本。历史 ID 仅从归档目录枚举、安全校验，不接受路径。未知/损坏行跳过且 complete=false，不将损坏文件当完整。`finish()` 幂等写 client_stopped 并更新关闭标记；关闭后 record 拒绝。无结束标記的退出被标识未正常结束。

每次启动独立 jsonl 与 json 元数据，保留最近 50 次，清理仅删除该格式的完整启动文件；使用 PID 活跃检测保护其他仍在运行的实例，旧 client*.jsonl 不删除。`get_directory()` 保持可用。每条读写结果返回错误，记录存储是否完整；只记录允许的环境信息，不含路径、用户名或凭据。

`export_run(run_id, destination_zip) -> Error` 导出全部选定记录，固定条目 events.jsonl、readable.txt、environment.json，版本来自 release.json；不接受筛选参数、不覆盖已有文件、不上传。写盘失败或损坏记录在摘要 complete=false，禁止宣称完整。测试通过独立目录、重建实例、50 次边界、活跃保护、错误路径和 ZIP 读取验证公开结果。

## 版本化构建

`release.json` 为唯一版本来源：`product=agentluo, version=0.1.0`。`src/release_info.gd` 的静态 `get_info() -> Dictionary` 返回副本，`title() -> String` 返回 agentluo + 版本。Application 原生窗口标题使用该值；不更改既有 user:// 目录。

`scripts/build.ps1 -Godot <path> [-OutputDirectory <root>] [-Package]` 默认构建至 dist/agentluo-<version>/agentluo.exe 和同名 pck。输出版本资源与 licenses；可选 Package 在 artifacts 下创建同名 ZIP，包含唯一顶层目录。已有 ZIP 时构建前失败，不覆盖；版本不自动递增。包内 DLL 保持导出引擎收集结果，不手工省略。构建仍检查锁定引擎版本、导出与独立启动，版本格式拒绝非三段数字。脚本与元数据属于构建配置切片，Red 不适用；实际导出、ZIP 条目与重复打包拒绝验证其行为。

## 统一主题与正式聊天布局

Style.make_theme() 统一账户与聊天控件的背景、文字、按钮、输入焦点、选中及滑块；主按钮/滑块为 #66CCFF，深色文字，悬停/按下/禁用与键盘焦点可辨。Style.primary(button) 应用主按钮变体，Style.avatar(texture_path, size=38) 返回带圆形浅底的头像控件。颜色集中定义，不用各页面覆盖旧青绿色。

正式 ChatView 顶部为头像、标题、连接状态及“更多”MenuButton；PopupMenu 提供“打开日志”(ID 0)、“清理本账号语音缓存”(ID 1)、“退出登录”(ID 2)，以可见菜单操作触发现有行为。未注入日志时相应项禁用。音量与停止当前在线语音移至输入区上方，发送按钮使用统一主题；当前不显示尚未实现的图片/历史/动态与模拟未读。

保持现有 ChatSession/AccountSession 调用、输入行为、快照增量刷新及阅读位置；原生标题栏、登录收起/展开、45:55 分隔、构图不改变。正文纯文本可选择复制。气泡白/浅蓝，头像圆形；以真实截图验收配色，不增加镜像样式实现的单元测试。菜单改动通过已有真实聊天及账户应用测试验证，确认菜单退出确实返回账户页。

## PcmStreamDecoder：增量 WAV 音频

原生 RefCounted 类，由媒体模块在主线程创建；与 WindowsSecurity 共用扩展，无网络或文件副作用。

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

## 工程与构建入口

- `client_godot/project.godot`：Godot 4.7.1 标准版工程；Compatibility，原生标题栏。默认入口为紧凑账户窗口（660×800，最小 480×640），登录后展开为角色与聊天窗口（1200×800，最小 960×640）；离线演示通过 --preview 独立进入。
- `client_godot/scripts/build.ps1 -Godot <exe> [-OutputDirectory <dir>]`：调用方为开发者/CI；默认输出到工程 `dist/`，要求匹配的 Windows x64 导出模板。正常依次导入和 release 导出，失败返回非零，不删除旧产物伪装成功；最终启动本次导出文件验证能正常退出。
- 引擎参数优先于 `GODOT_BIN` 环境变量；两者均缺失报错。不扫描全盘，不静默下载引擎，不接受错误主/次/补丁版本。
- `client_godot/scripts/check.ps1 -Godot <exe>`：执行引擎版本检查、headless 导入及启动检查；任何 GDScript parse/script 错误即失败，即使 Godot 进程本身退出码为 0。
- `client_godot/dependencies.lock.json`：版本化构建输入；包含基线提交、引擎版本/commit、模板版本、依赖下载地址和 SHA-256。尚未取得的产物不编造哈希、不标记为验证通过。
- `client_godot/export_presets.cfg`：固定名 `Windows Desktop` 的 x86_64 release preset，使用外置 PCK，输出文件名 `AgentLuo.exe`。

副作用仅为 Godot 导入缓存、日志和指定目录的构建产物。不会启动服务端、读取旧端凭据、修改生产数据或发出网络请求。启动检查使用 `--headless --quit-after 3`，不打开交互窗口。

## 验证入口

本切片属于工程/构建配置，无有意义的运行时 Red，记录“不适用”。观察构建命令退出码及日志；验证错误引擎路径被拒绝、同版本导入/导出成功、独立产物 headless 启动成功。headless 只证明启动，不证明真实 GPU 渲染或视觉验收。

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

本切片不提供触摸上报、网络事件、音频解码或构图持久化。模型、映射及许可说明随工程打包，旧端资源不修改。打包包含 `.moc3`、JSON、纹理和插件动态库。

### 验证

`godot --headless --path client_godot --script res://tests/test_avatar_driver.gd` 从真实驱动入口验证：完整资源可加载；缺失入口被拒绝且不丢旧模型；表情命令可切换、未知命令无副作用；动作合法/越界；口型范围及恢复。插件缺失属于环境失败，不计 Red。另用真实 GPU 导出包检查透明、遮罩、物理和表情，headless 不代替画面验收。

## AvatarFraming：构图与本地保存

`src/avatar/avatar_framing.gd` 是 `RefCounted`，调用者为角色区域。公开 `zoom_by(factor)`、`pan_by(pixel_delta, panel_size)`、`reset()`、`get_transform(panel_size, canvas_size) -> Transform2D`、`save_settings(path) -> Error`、`load_settings(path) -> Error`。

- 默认缩放倍数 1.2，位置为区域中心。倍数限制 0.6～2.4；位移保存为区域宽高比例，分别限制 -0.4～0.4。零尺寸区域不移动、不产生除零。
- 布局缩放基础值为区域对模型 canvas 的等比容纳；面板改变后仍保持保存的相对位置和比例，不保存像素绝对位置。
- 正缩放因子生效；零、负数、NaN、无限值拒绝且不改变状态。无效拖动同理。
- 重置恢复默认构图。保存用 ConfigFile 写当前缩放和归一位移；文件写入错误返回 Error。加载缺失文件返回 `ERR_FILE_NOT_FOUND`，损坏或字段非法返回 `ERR_INVALID_DATA` 并保留现有构图；超界有限值截断到范围。
- 产品设置路径为 `user://avatar_framing.cfg`，它只包含本机窗口构图，不含账户数据。测试使用独立临时路径，不触碰用户配置。
- 角色区域滚轮缩放、右键拖动；左键不调整构图。拖动释放和滚轮操作后保存；保存失败给出可识别状态，不影响当前画面。最小化关闭角色绘制/更新，不暂停整棵场景树。

验证入口：`tests/test_avatar_framing.gd`，检查边界、跨尺寸恢复、重置、缺失/损坏配置与重新实例化后的恢复。本切片不实现触摸上报或账户设置。

## OfflinePreview：可运行视觉样板

独立入口 `scenes/chat_preview.tscn`，由当前开发启动场景装配，始终显示“离线样板 · 未连接服务器”；正式产品菜单不提供此入口。UI 只调用离线控制器和 AvatarDriver，完全不发 HTTP/WebSocket 请求。

`src/preview/demo_session.gd` 是离线样板控制器，继承 RefCounted，供样板 UI 和 headless 测试调用：

- `select_scenario(name: String) -> bool`：接受 `conversation/empty/disconnected/error/thinking`，替换模拟消息并重置模拟状态；未知名称返回 false 且保留数据。
- `get_messages() -> Array[Dictionary]`：返回深拷贝。消息包含 `id/role/text/status`，role 为 assistant/user/system，status 为 received/sending/sent/failed；可选 `image` 为本地资源路径。样例包括长短文字、图片和三种发送状态。
- `submit_text(text: String) -> String`：空白输入或断网/加载失败场景返回空 ID 且不修改消息；正常保留输入正文并追加 sending 消息，返回会话内唯一 ID。不假装得到服务端答复。
- `settle(id: String, success: bool) -> bool`：只将已存在的 sending 消息变为 sent/failed；未知 ID 或重复结束返回 false。
- `changed` 信号通知展示刷新；场景切换后旧 ID 的延迟回调不影响新消息。

视觉布局：原生标题栏、左45%角色、右55%聊天，分隔条可调并单独保存 `user://preview_layout.cfg`。角色沿用 AvatarPanel；浅色实底、青蓝用户气泡、左右头像；消息正文可选择。底部输入支持 Enter/Shift+Enter，IME 合成期间不发送。输入失败保留文字。新消息只在原来位于底部时自动跟随，否则显示“回到最新”。样板消息数有限，不承诺历史分页或千条虚拟列表。

图片样例点击在内部浮层预览，支持缩放与关闭；样板可选择或粘贴单张图片，进入待发送预览，显式发送或取消。图片读取失败保留输入并提示，不写长期缓存。语音按钮只切换明确标注的模拟播放状态并驱动口型，无实际声音，不冒充流式音频验证。表情通过真实 AvatarDriver 切换。

验证：`tests/test_demo_session.gd` 检查空白拒绝、唯一 ID、正文保持、状态转移幂等、坏场景无副作用、场景切换旧回调隔离、读副本不泄露内部状态。实际导出截图核对气泡、真实模型、字体、分隔和底部输入。中文输入法与系统剪贴板需人工操作验收。

## WindowsSecurity：Windows 原生密码与秘密保护

位置 `client_godot/native/windows_security.cpp`，GDExtension 类 `WindowsSecurity`，继承 RefCounted；由应用创建并注入账户/本地存储模块。只使用 Windows CNG/Crypt32，不启动外部进程，不访问磁盘或网络。

所有调用返回 `{ok: bool, data: PackedByteArray, error: String}`；成功 error 为空，失败 data 为空，错误码不包含输入内容。

- `encrypt_password(public_key_pem: String, password: String) -> Dictionary`：接收服务端 `/auth/public_key` 的 SubjectPublicKeyInfo PEM 和 UTF-8 密码，返回 RSA-OAEP 密文字节；OAEP 与 MGF1 均 SHA256，label 为空。调用方用 Base64 编码填入既有 password/new_password 字段。RSA 至少 2048 位，最大 8192 位；公钥字符串不超过 16 KiB；明文字节超出当前 OAEP 上限时返回 `INVALID_INPUT`。无效公钥 `INVALID_KEY`；CNG 失败 `ENCRYPTION_FAILED`。不使用 SHA1 降级。
- `protect_secret(plain: PackedByteArray, scope: PackedByteArray) -> Dictionary`：当前 Windows 用户 DPAPI，禁止交互提示；scope 为规范化服务器/账户标识派生的额外熵，不能跨 scope 解密。plain 与 scope 各 1～65536 字节；失败 `INVALID_INPUT` 或 `PROTECT_FAILED`。
- `unprotect_secret(cipher: PackedByteArray, scope: PackedByteArray) -> Dictionary`：相同用户及 scope 下恢复字节；篡改、不同 scope 或不同用户返回 `UNPROTECT_FAILED`，绝不降级为明文。cipher 最大 128 KiB，scope 同上。

C++ 临时明文缓冲在释放前清零；Windows 句柄和 DPAPI 输出无论成功失败都释放。GDScript 调用者仍负责及时释放自己的密码/密钥引用。此接口只转换字节，原子落盘、自动登录策略和 API key 明文选择由后续存储/业务接口承担。

验证：Godot headless 从 ClassDB 创建真实扩展，验证 DPAPI 往返、不同 scope/篡改拒绝、空值及上限；Python 临时测试进程生成密钥，用仓库 `account.py::decrypt_password` 解密 Godot 产生的 ASCII/中文/边界密码密文，并确认相同明文的密文不同。不使用生产密钥或真实凭据。扩展未加载属于环境失败，不计 Red。

## AccountApi：异步账户请求

位置 `src/network/account_api.gd`，继承 Node；组装根通过构造函数注入 WindowsSecurity 和超时（默认 15 秒）。UI/账户控制器通过 `request(operation, server, fields) -> Dictionary`（异步）调用；公开 `cancel()` 取消当前操作、`normalize_server(address) -> String` 规范化地址。单实例同时只执行一个操作，第二次调用返回 `BUSY`。

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

`src/storage/credential_store.gd`（RefCounted）由 WindowsSecurity 和根目录（默认 `user://accounts`）构造；只接受已规范化的 server 和非空 username。作用域是 JSON `[server, username]` 的 SHA256，目录及 DPAPI entropy 均由此派生。

- `save(server, username, token) -> Error`：仅保存 DPAPI 保护后的 login_token，先写临时文件再原子替换；失败返回错误，不保存明文、不读取旧端数据。
- `read(server, username) -> Dictionary`：返回 `{ok, code, token}`，成功 token 为解密后的字符串；缺失 NOT_FOUND，损坏/无法解密 UNAVAILABLE，失败 token 为空。
- `forget(server, username) -> Error`：删除指定作用域自动登录凭据；缺失视为成功。媒体缓存不受影响。

`src/session/account_session.gd`（Node）由 AccountApi、CredentialStore、普通设置文件路径构造，拥有 API 节点；默认设置文件 `user://account.cfg` 只含上次服务器、用户名与 auto_login 布尔值。

- `perform(operation, server, fields, remember=false) -> Dictionary`（异步）：通过 AccountApi 处理账户操作。登录/自动登录成功才进入 signed_in；注册/重置成功保持 signed_out，提示回到登录。重复提交 BUSY；错误保留 UI 草稿。成功记住登录时只保存 login_token，message_token 只在内存。
- `resume() -> Dictionary`（异步）：配置启用自动登录且凭据可解密时尝试一次；成功旋转并保存新 token。明确 AUTH_REJECTED 后清除凭据并关闭自动登录，不自动循环。配置缺失返回 NO_SAVED_LOGIN；无法读取凭据返回 CREDENTIAL_UNAVAILABLE。网络暂时失败不会把 token 误认为鉴权失败。
- `cancel()`：取消在途操作，结束 busy 状态；迟到结果不建立会话。
- `logout() -> Error`：取消在途请求、清空内存会话、清除当前作用域自动登录凭据、禁用自动登录，发送 signed_out 状态；文件删除/保存失败返回实际错误，不伪装清除成功。
- `get_login_defaults() -> Dictionary`：server/username/remember，用于登录表单，不含秘密。`get_session() -> Dictionary`：仅向应用/网络控制器返回当前会话深拷贝（server/username/user_id/login_token/message_token），退出后为空。
- `changed(state: Dictionary)`：只包含 phase（signed_out/busy/signed_in）、code、storage_error，不含 token/密码。写凭据或配置失败不撤销已经成功的在线登录；返回 `storage_error=true`，并关闭自动登录，不自动明文降级。

普通设置同样采用临时文件和原子替换。切换服务器/账户前取消旧操作并清空旧会话；后续网络组装监听 signed_out/busy 关闭连接。本切片尚不创建聊天连接。

验证从以上公开入口使用真实 DPAPI、本地 HTTP fixture、隔离临时目录：跨服务器/账户不可读、重新实例化恢复、token 旋转、401 清理、退出后无会话/凭据、重复取消、保存失败仍可在线登录。测试不触碰真实 user://account.cfg。

## AccountView 与应用账户入口

`src/ui/account_view.gd` 是 Control 视图，由组装根注入 AccountSession，监听 changed 展示状态。主入口默认显示实际账户页面；离线样板只通过开发参数 `--preview` 进入，不放入产品菜单。

- 统一账户页面提供密码登录/注册/邀请码重置三个模式；字段为服务器地址、用户名、密码、确认密码、邀请码及自动登录勾选（按模式显示）。密码默认遮蔽；登录不裁剪用户名/密码；确认密码不一致时在本地拒绝且不发请求。
- 点击提交或密码框 Enter 调用 AccountSession.perform；忙碌时禁用模式、表单、提交并显示取消。失败保留用户输入；成功清空密码/确认密码/邀请码；注册/重置成功返回密码登录模式，保留服务器及新用户名。
- AUTH_REJECTED、超时、公钥/加密错误、响应错误和存储失败均以系统状态展示；不把错误显示成角色发言，不回显 token 或服务端未经校验的正文。
- signed_in 显示账户身份与退出入口；退出调用 logout，清除密码框，并明确报告凭据清除失败。后续聊天场景由组装根按会话状态装配，本视图不创建 WebSocket。
- 组装根创建真实 WindowsSecurity、CredentialStore、AccountApi、AccountSession。正常 GUI 启动尝试一次 resume；headless 构建检查和 `--capture` 截图模式不自动访问配置中的服务器。自动化账户测试注入独立配置路径及本地 HTTP 服务。

验证：`test_account_view.gd` 通过可见表单、按钮和状态文本观察错误密码后保留输入、确认密码拒绝、成功后清空敏感字段与退出状态；使用真实账户控制器和本地 HTTP fixture。导出截图检查默认/最小窗口及中文字段布局。系统 IME 仍由实际 Windows 人工验收。

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

`src/ui/chat_view.gd`（Control）注入 ChatSession，发送/状态/正文使用真实控制器；公开 `logout_requested` 交给应用调用 AccountSession.logout。沿用已确认的气泡、输入控件和主题，正式发送状态不带“演示”。Enter/Shift+Enter/IME 规则不变；只有接受发送后清输入，失败保留。已有气泡更新而不全部重建，保持文字选择；在底部跟随新消息，阅读旧内容保留滚动位置并提供回到最新。提供音量和停止当前语音按钮，不提供尚未接入的图片/历史入口，完整缓存成功后提供消息语音重放。

## ReplyAudio：实际流式播放

`src/media/reply_audio.gd` 为 Node，由组装根创建，构造参数 `(logger=null, clock=Callable(), cache=null)` 可注入 ClientLog 与返回单调毫秒的时钟（默认 Time.get_ticks_msec，测试可控）；ChatSession 构造可接收第三个参数 media，未传则创建真实 ReplyAudio（保留既有调用兼容）。媒体拥有 AudioStreamPlayer/Generator 与每 UUID 的 PcmStreamDecoder，不直接改变气泡或角色。

- `append_reply_audio(id, encoded, final, audio_error=false, ephemeral=false)`：接收每包 Base64 字符串，先解码/缓存。空音频可用于文字回复及终止；坏 Base64、原生失败、服务端 audio_error 产生可识别错误，保留聊天文字，不落盘部分流。
- `play_reply(id)`：允许一个活跃 UUID；可在首片到达后调用，约 80ms 预缓冲或 final 后自动开始实际播放。后续 UUID 先解码，等待会话按顺序调用；每 UUID 采样率来自 WAV，由 Godot 混音器重采样。
- `receive_finished(id, code)` 表示接收结束；`playback_finished(id, code)` 表示播放器排空并等待输出延迟后结束或中断，两者各一次；`mouth_changed(value)` 为实际消耗帧对应 RMS（适当放大截断至 0～1），停止为 -1 恢复表情基础口型。
- `get_state()` 返回 active_id/playing/queued/volume；`state_changed(state)` 通知变化。`set_volume(value)` 接受有限 0～1 并截断；默认 1。`stop_current()` 中止当前声音，后续同 UUID 继续解码验证与缓存，丢弃待播放帧；仍接收文字/终止直到推进下一句；`reset()` 释放全部流，无旧账户完成回调，重复安全。
- 最多 16 个待处理 UUID，累计未读解码帧上限 128 MiB；60 秒未收到续片则 AUDIO_TIMEOUT，恢复队列。格式/容量错误、退出、断线均释放未完成资源。process_mode=ALWAYS，不随角色最小化停绘而暂停声音。
- 记录 audio_received（字节数）、audio_format（格式）、audio_decoded（帧数）、audio_receive_finished、audio_playback_started、audio_playback_finished、audio_underrun 及 audio_error。日志只含安全元数据，不能声称实际扬声器听感已验证。

ChatSession 公开 set_volume/get_audio_state/stop_voice，转发媒体 mouth_changed 信号给组装根；get_state 追加 speaking 布尔值。UI 显示播放/错误状态；停止只影响当前声音，后续回复默认仍自动播放。音量使用现有窗口配置保存，拒绝非法配置值。隐藏回复仍播放；临时回复不写缓存。完整音频缓存及重放契约如下。

验证 tests/test_reply_audio.gd 用真实原生解码/AudioStreamGenerator，AudioEffectCapture 观察非零输出及静音/停止；loopback WebSocket 到 ChatSession 验证分片、顺序、隐藏、坏流和断线。默认只用合成音频，实际 Windows 音频驱动另跑并记录，不连接生产服务。

应用沿用左角色右聊天；账户成功显示 ChatView、隐藏账户表单；退出返回账户表单并取消连接。分隔比例保存到 user://window_layout.cfg，窗口缩放保持比例。离线 preview 保持独立。

### 账户窗口展开与默认服务器

- 未登录、登录失败、注册/重置、取消和自动登录等待期间，只显示右侧账户表单；窗口初始 660×800、最小 480×640，不显示角色、聊天及分隔条。
- AccountSession 的 signed_in 才展开为角色/聊天窗口（首次 1200×800，最小 960×640），成功登录再创建角色节点；退出后收回账户窗口并释放角色绘制资源，重新登录按已保存构图加载。重复 busy/signed_out 通知不反复调整窗口。登录后用户调整的普通窗口尺寸在本次运行内保留，重新登录恢复；展开/收起保持窗口中心并限制在当前屏幕可用区域内。
- 源工程的原生启动窗口也使用账户尺寸，避免出现完整窗口后闪缩；独立 --preview 仍使用原 1200×800 样板尺寸。
- AccountSession.get_login_defaults 的 server 在首次使用、配置缺失/损坏、空地址或无效地址时为 `https://www-api.u3493359.nyat.app:11664`（来源 client/config/config.json 的 release_config.base_url）。已保存的有效地址优先，仍可编辑；回退地址时关闭自动登录，不读取旧端配置或凭据、不主动探测默认服务器。
- Application 可由构造参数注入真实 AccountSession 与普通布局文件路径，默认仍由组装根创建服务并使用 user://window_layout.cfg；测试用独立存储路径及 loopback HTTP 服务，不修改用户设置。

验证 tests/test_application_window.gd：通过可见账户表单及真实 AccountSession/AccountApi 观察初始/失败/成功/退出窗口状态；检查自定义地址恢复与空配置回退，默认测试不连接预填地址。实际导出截图检查紧凑表单布局。

## ClientLog：客户端诊断日志

`src/storage/client_log.gd` 为 RefCounted，由应用创建并注入聊天/媒体；构造参数及归档规则见本文开头 ClientLog 启动归档契约，公开 `record(event, fields={}) -> Error` 与 `get_directory() -> String`。

- 按启动写独立 JSON Lines，逐条 flush；旧三文件不再写入或清理。单条不超过 4 KiB；目录/写入失败返回 Error，不阻塞聊天或谎报日志成功。只在主线程记录。
- 每条含 UTC time、单调 elapsed_ms 与固定格式 event。字段采用白名单：连接 phase/code，回复 reply_id 的 SHA256 前 12 位，has_audio/audio_chars/bytes/frames/sample_rate/channels/bits/final/audio_error/queued/volume/latency_ms 等布尔/数字；phase/code 只允许短 ASCII 字母数字下划线。忽略未知字段，不写用户名、密码、token、API key、正文、完整委托提示词或 Base64 音频。
- ChatSession 构造可注入 logger；记录 connection_state、reply_received（是否带音频、编码长度、终止/错误标志）及 system_error，不输出 payload 原文。应用启动记录 client_started。
- `ChatSession.get_log_directory() -> String` 供 ChatView 的“打开日志”按钮使用；无 logger 返回空串、按钮禁用。打开目录只经用户点击，不自动上传日志。

验证 tests/test_client_log.gd 的白名单、回复标识哈希、启动归档和失败返回；现有 loopback 聊天测试检查接收日志并确保合成秘密不出现。日志证明实际收包，不把接收结束等同播放结束。

验证：真实 ChatSession + WebSocketTransport + loopback 服务，观察发送状态、同 UUID 多包/隐藏/临时/音频错误文字、思考、表情顺序、断线和退出；通过 ChatView 可见控件触发发送，验证草稿与真实回复；默认自动化不访问真实账户。

## 完整语音重放与消息控件

ReplyAudio 由 Application 注入 AudioCache，缺少 cache 的既有调用保留在线播放。ChatSession.start 按 server/username 设置范围；stop 关闭范围，断线 reset 仅取消在途流与重放，保留范围及已完成缓存。以下接口为本轮重放切片契约：

- `set_scope(server, username) -> Error`：先 reset，再设置缓存账户范围；空值关闭范围。存储失败不阻止聊天及在线声音。
- `get_message_audio(id) -> Dictionary`：返回 available、duration、waveform（24 个真实幅值）、status（idle/playing/paused）、position（秒）、blocked（在线正在输出）、code；不向 UI 返回磁盘路径。未完整提交不可重放；缓存失败 code=CACHE_WRITE_FAILED。
- `replay(id) -> Error`：在线正在输出返回 ERR_BUSY；没有有效缓存返回 ERR_DOES_NOT_EXIST；同一正在播放 UUID 幂等；另一 UUID 停止旧声并从头开始。分块读取原始缓存交给 PcmStreamDecoder，错误终止并报告 REPLAY_FAILED。
- `pause_replay()` / `resume_replay()` / `stop_replay()`：幂等；暂停冻结混音与进度，继续从原位置，停止/自然结束回 idle、position=0；每次再播放从头开始。不提供寻址接口。
- `clear_cache() -> Error`：停止本地重放，取消当前所有在途流的缓存且不再创建同流文件；在线声音继续，完整文件仅按当前账户手动清理。失败报告 CACHE_CLEAR_FAILED，重新查询实际可用性。
- `message_audio_changed(id, state)`：缓存结果及约 20Hz 的实际重放进度定向通知，不触发聊天 changed。在线输出开始/结束同时通知已有音频控件 blocked 变化。`replay_finished(id, code)` 独立于仅在线使用的 playback_finished，绝不推进在线回复队列。

成功终止包、原生 finish 成功、文件提交成功三个条件同时满足才提供 available。临时标记为粘性，错误/断线/退出 abort 临时文件。写盘失败不影响解码/声音；现有完整缓存退出保留，无自动淘汰。在线实际开始输出时同步抢占播放或暂停的重放。所有嘴型按实际消耗帧，暂停/结束为 -1；重放不发出表情命令。日志增加 replay_started/replay_paused/replay_resumed/replay_stopped/replay_finished/replay_preempted，沿用白名单与 UUID 哈希。

ChatSession 公开同名 get_message_audio/replay/pause_replay/resume_replay/stop_replay/clear_cache 及 message_audio_changed；仅允许当前显示的 assistant 消息发起 replay，不接受任意路径。清理失败通过系统状态报告。UI 只调用 ChatSession。MessageBubble 提供 `set_audio_state(state)`、`audio_action(action)`（play/pause/resume/stop），只更新独立音频行，不重建气泡或设置正文。完整语音行显示重放、时长和非交互波形；播放/暂停时显示进度与停止。不可用时隐藏控件，保存失败显示“语音未能保存”。更多菜单清理须经 ConfirmationDialog 确认，取消不调用 clear_cache。

验证 tests/test_voice_replay.gd 从 ReplyAudio 观察真实混音、暂停进度、恢复、停止/切换、自然结束、抢占、终止后缓存、临时/错误/写盘失败、清理抑制与跨实例恢复；loopback test_voice_chat.gd 从 ChatSession 与可见控件验证按钮、消息不重复、表情不重发、文字选择不被进度刷新破坏。默认只用合成声音，WASAPI、真实服务听感分别记录。

## ModelExecutor：异步非流式模型委托

`ModelExecutor(settings,logger=null,timeout=120)` Node，`start()` 开始当前账号执行代次，`stop()` 取消所有请求、清空请求 ID 去重和结果，不发迟到响应。`submit(payload)` 接收现有 llm_request，`completed(response)` 产生 request_id/content/usage 或 request_id/error；重复 ID 不再次调用供应商，完成后可重发同一结果。在当前登录保留 ID 集，最多 4096 个不同委托、8 个并发，容量满返回 MODEL_BUSY 而不遗忘旧 ID。`enabled_types()` 转交当前有效用途列表。

执行先检查用途启用、kind、JSON/thinking 能力，校验 prompt/params/flags/image 字段；使用提交时配置深拷贝。OpenAI 兼容 POST Base URL/chat/completions，非流式、Bearer API Key、120 秒、不自动重试。默认 max_tokens=4096/temperature=0.7/top_p=0.9，再覆盖服务端 params、再本地 params，最后锁定 model/messages/stream=false；thinking 与 JSON 请求强制对应参数。stream=true/非 bool 或 stream_options 拒绝。文本为 system prompt，图像为 user text+image_url detail=auto；校验 choices[0].message.content 为字符串，JSON 请求必须是可解析 JSON；供应商错误正文不回显，只回传识别码，usage 只保留数字 token 统计。

`test_config(type_id,config)` 异步返回 ok/code，纯配置校验后使用固定短输入调用同一执行路径，结果不含生成正文；不改变运行配置、不发送聊天历史。ModelWindow(settings,executor=null) 提供手动测试按钮，明确可能消耗额度且默认取消，确认才调用；退出账号取消测试。模型窗口关闭丢弃草稿，执行中的测试使用快照。ChatSession 构造增加可选 models 执行器（由 ChatSession 持有），登录 start、退出 stop；llm_request 分派，completed 以 llm_response 瞬时事件回传；user_text 的 llm_mode.types 来自执行器，历史屏障释放也遵守此规则。

测试从真实 loopback HTTP 供应商和 WS 观察文本/VLM、参数保护、重复请求只调用一次、JSON 失败、安全错误、超时、取消与在途配置快照；日志只记阶段/耗时/安全代码及哈希用途 ID，不记录提示词/输出/密钥。

## DynamicsController：动态读取、分页及手动已读

`DynamicsController(logger=null,timeout=15)` Node，由 Application 持有，`start(session)` 查询未读并每30秒重查；`stop()` 取消请求、清空账号数据并隔离旧代回调。`get_state()` 返回 phase/code/unread/unread_code/has_more/busy；`get_posts()` 返回副本，`get_comments(id)` 返回 items/has_more/busy/code/loaded。`changed` 用于列表/评论，`unread_changed(count)` 单独通知徽标；未读轮询不自动刷新列表、不清草稿、不标已读。

`refresh()` 加载首批10条，`load_more()` 使用服务端不透明 next_cursor；`load_comments(id,more=false)` 每页20条。GET /dynamics、/{id}/comments、/unread 使用 username query + Bearer message_token；对 cursor URI 编码。校验分页字段及显示字段、ID 去重，拒绝不前进/空的有后续页；失败保留已显示内容及原 cursor，可重试。刷新不自动标已读。`refresh_unread()` 失败保留原数量；`mark_read()` 只有 POST /dynamics/read 返回 ok=true 后清零，忙碌轮询期间不提交，避免旧响应覆盖结果。

只保存内存列表/评论，不新增正文数据库。服务端负责私有动态/评论隔离；客户端只展示当前账号返回数据。日志只记录安全阶段/错误/数量。测试使用本地 HTTP 的10/20条边界、分页去重/异常、未读失败保留、显式标读、取消与重新登录。

## 动态写入与非模态窗口

DynamicsController 新增 `publish(content)`、`comment(id,content,parent_comment_id="")`，异步返回 ok/code；空文本拒绝；评论必须属于已加载且允许评论动态，回复目标必须属于已加载的该动态评论。POST 使用既有 content/parent_comment_id 字段；无幂等键、不自动重试，单个写请求在途返回 BUSY。超时显示可能已发送，保留草稿由用户核实后自行重试。成功响应 item 校验后插入内存列表/评论，不自动标已读；其他分页边界保留。退出返回 CANCELLED、不能影响新账号。

动态窗口的现行呈现与草稿契约见下文“0.1.1 双栏动态窗口”；0.1.0 单列折叠卡片已被替换。

ChatView 增加 `set_dynamics_unread(count)` 更新顶部常驻按钮（大于99为99+），按钮 settings_requested("dynamics") 由 Application 打开。未读轮询只更新徽标/窗口状态，不重建卡片或打断编辑。Application 登录 start、退出 stop。测试从真实 HTTP 和可见 UI 验证发布/回复、不可评论、失败保留、关闭确认和顶部入口；不向公共服务器写入测试动态。

## 角色资源描述与稳定身份

AvatarDriver 增加 `load_character(descriptor_path) -> Error`；描述是当前随包 JSON，包含 character_id/resource_id/model_path/mapping_path 四个非空字符串。稳定身份 luotianyi 与具体 original 模型资源分离；模型自身 Cubism FileReferences.Motions/HitAreas 提供动作及命中区域资源映射，mapping_path 提供表情及基础口型映射。描述/映射/模型预检和插件候选加载全部成功后才替换当前角色；失败保持原模型/表达/身份。`get_status()` 增加 character_id/resource_id，原 load_avatar(model_path,mapping_path=默认映射) 兼容原测试与样板，不宣称换装 UI 或触摸业务已新增。

AvatarPanel 读取当前角色描述，不写死模型入口。当前文件选择适配边界为 UI 的 Godot 原生 FileDialog（诊断包输出），业务只接收用户选定输出路径；生命周期由 Application 管理，子页面不重连。WindowsSecurity 只提供既有凭据能力，PcmStreamDecoder 是独立原生类与源文件；当前共同打包一个 DLL，不表示已有 Android/iOS 实现。

### 0.1.0 验收边界补充

模型用途定义更新导致本地配置结构/kind/能力不满足时，加载仍显示用途，禁用该用途并给出 INVALID_CONFIG；格式损坏的字段使用安全默认配置，不能在表单或广告阶段引发脚本错误。模型未启用时不向服务端广告。动态评论按服务端 created_at/id 升序合并，发评论后继续分页不能把更早评论排到新评论之后；列表读取与同窗口写入互斥避免旧加载响应覆盖刚写入结果。动态加载成功清除加载提示、失败保留草稿；这是当前界面行为修正。

## UnifiedDropdown：统一选择器与动作菜单

`UnifiedDropdown(action_menu=false)` 继承 Button。`set_items(items:Array)->Error` 接收{id:String,label:String,disabled?:bool}及{separator:true}，非空ID唯一，非法整批拒绝；返回副本的 `get_items()` 用于状态观察。`set_selected_id(id)->bool` 静默选择有效启用项；`get_selected_id()->String`。更新列表保留仍有效的选择，否则选择首个启用项；动作模式不改按钮标题。`set_item_enabled(id,enabled)` 更新禁用状态。用户鼠标/键盘选择发出 `activated(id:String)`，选择器先更新选择再通知；代码设置选择不发通知。

`open_menu()`、`close_menu()`、`is_menu_open()` 管理展示，disabled按钮不展开。弹层白底圆角10、细边轻阴影、约42px行高，浅灰悬停、主题蓝焦点和选中标记。原生弹层限制在当前屏幕可用区域内，优先向下、空间不足向上，长列表滚动。方向键跳过禁用项与分隔线，Enter选择、Esc/点外部关闭；父窗口移动/调整/最小化/关闭自动收起。弹层内部由组件拥有，页面不操作PopupMenu对象。

迁移账户模式、聊天更多、偏好预设、模型用途/复制、日志级别/模块/启动选择。账户和菜单使用固定语义ID，模型/日志使用服务端类型ID/启动ID；不可按显示文字反推操作。原业务控制器协议不变。组件测试键盘/禁用/稳定ID/可见弹层行为，既有账户/聊天/设置/日志回归验证迁移。

## 0.1.1 动态完整刷新
DynamicsController.refresh_comments(id) 异步从第一页按20条读取到末页，期间 busy=true 禁止同动态分页/写入；所有页校验完成才原子合并已有评论（保留本次已成功提交的评论），按时间排序。失败保留内容与原分页游标、code可重试；取消及跨账号旧响应不生效；重复游标循环为INVALID_RESPONSE。每次请求沿用既有超时。refresh() 首页新动态优先合并此前列表，保留已选择的旧动态，分页仍用最新首页游标去重。publish/comment 成功返回新增 item_id，失败返回空 item_id；不改变服务端协议。测试从真实HTTP验证末页、失败保留及取消。

## 0.1.1 双栏动态窗口（取代上文单列卡片呈现）
`DynamicsWindow(controller,layout_path="user://dynamics-window.cfg")` 继续继承 DraftWindow，公开 open/is_dirty 保持兼容；force_native=true、transient=false、普通系统窗口，1000×780/最小900×640，布局文件只存尺寸与左右比例，默认45:55。每次创建无选中，select_post(id)->bool/get_selected_id()->String 是视图选择边界，未知ID拒绝。左侧10条自动分页；右侧由 DynamicDetail(controller,post) 呈现完整正文/普通留言/升序平铺评论及单个行内回复。Detail 的 update_post(post)、update_comments()、is_dirty() 供窗口刷新与草稿检查；不是网络适配器。视图仅通过控制器获取和写入数据。
每条动态的 Detail 与滚动位置在窗口存续期间保留；切换隐藏旧详情，不销毁草稿，旧响应只更新对应详情。取消回复转为无目标的评论草稿，文字保留；再次选回复带到新对象下。普通留言与回复分别保留。发送期间禁用对应输入，成功清空提交内容，失败保留。不可评论同时禁止普通/回复输入。时间助手仅用于显示，北京时间解释无时区字段，异常回显原文。
列表/评论滚到底自动加载，错误停止自动请求并显示重试；手动刷新保留选择、草稿和阅读位置，评论调用 refresh_comments 全量重新校验。未读独立提示有新的动态或评论，不推断目标。
发布通过 PublishWindow(controller) 非模态原生子窗，published(id) 只在成功时通知父窗选择新动态。父窗 is_dirty 合并所有详情与发布窗草稿/在途写入；确认放弃后一起销毁，应用退出/登出沿用相同检查。草稿不持久保存。
验证：真实loopback UI 首次无选中、选择切换、回复取消、读写失败保留、独立发布、关闭聚合确认；原生窗口所有者/任务栏资格/最小化独立和截图另行验证。

DynamicDetail.refresh_comments() 由窗口调用，转交完整分页刷新并保留错误重试状态；同UI模块共享 avatar_path(item) 与 relative_time(raw) 展示助手，无网络或持久化副作用。Application 将动态布局路径与其他窗口配置放在同一注入数据目录，测试使用独立临时目录。

构建打包契约：build.ps1 -Package 仅在ZIP已包含完整导出目录后发布最终版本名，存在正式包拒绝覆盖。临时归档失败返回失败，不打印交付成功或留下同名残缺正式包；验证测试检查CRC、版本、根目录及所有源文件逐字节一致。Windows短暂文件占用属于打包失败，不得误报可交付。

## 界面场景化：主题与材质资源（0.1.2 起）

界面场景化的首个切片只收敛样式来源，不改视图节点树，也不改任何公开方法与信号。

`res://theme/app_theme.tres` 是唯一主题来源，内容等价于原 `Style.make_theme()`：`SystemFont` 字体族 `Microsoft YaHei UI`/`Microsoft YaHei`、默认字号 15；`Label`/`Button`/`OptionButton`/`LineEdit`/`TextEdit`/`RichTextLabel`/`PopupMenu`/`CheckBox` 字体色 `#304553`（`RichTextLabel` 另含默认色），`TextEdit` 占位色 `#9aaeb8`、`LineEdit` 占位色 `#8299a6`；`Button`/`OptionButton`/`MenuButton` 的 normal `#eef6fb`、hover `#dff3ff`、pressed `#b7e6ff`、disabled `#edf1f4`（圆角 8、内边距 9）与 focus 描边，字体四态 `#304553`、禁用 `#9aabb7`；`PrimaryButton` 为 `Button` 变体（normal `#66ccff`、hover `#8ad8ff`、pressed `#43b8f0`，圆角 9、内边距 10）；`TextEdit`/`LineEdit` normal 白底（圆角 8、内边距 12）、focus 描边、选区 `#b7e6ff`、光标 `#304553`；`PopupMenu` 面板白底（圆角 10、内边距 8）、hover `#dff3ff`（圆角 6、内边距 6）、`v_separation` 12；`HSlider` 轨道 `#dcecf5`、已填充区与高亮 `#66ccff`（圆角 2、内边距 2）、focus 描边与三个 grabber 圆点图标。焦点样式为透明底、圆角 8、`#66ccff` 两像素描边。

`project.godot` 的 `gui/theme/custom` 指向该资源，作为全项目默认主题；视图场景根可显式挂同一资源，独立原生 `Window` 因此不再各自构造主题。

`Style.make_theme()` 保留为对该资源的薄壳（`load` 并返回同一 `Theme`），不再在代码里构造主题；调用方原有的节点级 `add_theme_stylebox_override` 与 `theme_type_variation` 行为不变，外观不因共享同一 `Theme` 实例而改变。

`res://assets/ui/round_avatar.gdshader` 承担 `Style.avatar()` 的圆形遮罩（透明遮罩 + 浅底 `vec3(0.91,0.97,1.0)` 混合，半径 0.47→0.5 平滑过渡）；`res://assets/ui/slider_dot.png`、`slider_dot_highlight.png`、`slider_dot_disabled.png` 是 HSlider 的三个 grabber 圆点，像素与原 16×16 逐像素公式一致（中心 (7.5,7.5)、半径 ≤ 6，颜色分别为 `#66ccff`、`#43b8f0`、`#b7c6d0`）。

从哪个 interface 验证：`tests/test_theme_contract.gd` 断言资源存在、条目值与字面规格逐项一致、`make_theme()` 返回的主题与磁盘资源等价、Grabber 圆点像素与公式一致，并断言项目默认主题指向该资源；`scripts/check.ps1` 的导入与启动步骤验证资源可被实际导入。

## 界面场景化：视图场景与 setup() 注入（0.1.2 起）

视图场景放在 `res://scenes/ui/`（窗口与视图组件），入口场景仍留在 `res://scenes/` 根（`main.tscn` 与离线样板）。场景是提交里的文本 `.tscn`，不依赖在编辑器里手工搭建。

视图场景契约：根节点类型等于该视图原来的基类（窗口类为 `Window`，`src/ui/draft_window.gd` 的子类沿用这条继承链），根节点挂原脚本；根显式设 `theme = res://theme/app_theme.tres`，独立原生窗口因此不再各自构造主题；节点名、层级、文案、尺寸、颜色、间距、`theme_override_*` 与 `theme_type_variation` 全部写在场景里，脚本只保留行为、信号、原生坐标换算、自绘与业务逻辑，不再用 `new()` 建树。场景里承担公开语义、会被外部代码或测试按名字查找的节点同时设 `unique_name_in_owner`，脚本统一用 `%Name` 绑定，不再由代码 `name =` 命名。

依赖注入契约：视图不再有带参数的 `_init`。依赖改由公开方法 `setup(...)` 注入，调用顺序固定 `instantiate() → setup() → add_child()`，保证 `_ready()` 执行时依赖已就位；`setup()` 只保存依赖，不建节点、不发起 IO。消费点用 `preload("res://scenes/...tscn")` 常量引用场景。

首个场景化视图是 `res://scenes/ui/publish_window.tscn`：根节点 `PublishWindow`（`Window`）挂 `src/ui/publish_window.gd`，依赖由 `setup(controller)` 注入。原 `_init(controller)` 里的 `title`「发布动态」、`visible = false`、`force_native`、`transient`、`size`（520×350）、`min_size`（400×300），以及 `PanelContainer` + `VBoxContainer` 内的标题「分享此刻的想法」（20 号字）、`PublishDraft`（`TextEdit`，占位「想和天依分享些什么？」、按边界换行、纵向扩展）、状态 `Label`（智能按词换行）与 `PublishButton`（`Button`，「发布文字动态」，`PrimaryButton` 变体）全部改由场景提供；脚本保留 `published(id)` 信号、`open()`、`is_dirty()`（正在写或草稿非空）与 `_publish()` 的发布、清空、关闭及失败文案行为，公开面不变。

`src/ui/draft_window.gd` 保持纯脚本基类，不节点化：`open()`、`is_dirty()` 与「关闭前丢弃确认」仍由它提供，`Discard` 确认对话框仍由基类代码创建；草稿窗口类各自提供 `.tscn`，根节点挂各自脚本并沿用这条继承链，因此 `super._ready()` 仍会构造确认框。

场景属性与 `_init()` 的先后关系（实测契约）：`PackedScene` 实例化时先赋值场景里序列化的属性，再挂上根节点脚本并执行 `_init()`，因此 `_init()` 中的赋值会覆盖场景中的同名属性。为让场景成为属性唯一来源，`src/ui/draft_window.gd` 的 `_init()` 只保留 `visible = false`（四个草稿窗口的开窗默认值，与各自场景一致），不再赋值 `transient`（`Window.transient` 默认即为 `false`），发布窗口的 `transient = true` 因此由 `scenes/ui/publish_window.tscn` 生效。后续视图的场景根脚本同样不得在 `_init()` 里赋值由场景接管的属性。
从哪个 interface 验证：`tests/test_ui_scenes.gd` 逐场景断言场景存在、根节点类型、根脚本、关键节点名与 `unique_name_in_owner`、脚本暴露 `setup()` 且不再要求 `_init` 参数，并断言本片从代码搬到场景的属性值不变；`tests/test_dynamics_window.gd`、`tests/test_dynamics_detail.gd`、`tests/test_application_drafts.gd` 从发布窗口的公开行为（草稿保留、发布成功选中新动态并关闭）回归。
### preferences_window 与 model_window（0.1.2 第三片）

`res://scenes/ui/preferences_window.tscn`：根 `Window`（名 `PreferencesWindow`）挂 `src/ui/preferences_window.gd`，依赖由 `setup(controller)` 注入。场景提供 `MarginContainer`（四边 22）→ `VBoxContainer`（间距 12）内的标题「和天依相处的方式」（22 号字）、两组「14 号标签 + `HBoxContainer`（`%RelationshipField` / `%SpeakingStyleField` + 预设插入位）」、`%PersonalityField` 与 `%CustomContextField`（`TextEdit`，纵向最小高度 80 / 120，边界换行）、`%Status`（智能按词换行）以及 `%Reload`「重新加载」与 `%Save`「保存相处模式」（`PrimaryButton`）操作行；原 `_init(controller)` 的 `title`、`size`（600×620）、`min_size`（480×520）改由场景提供，`is_dirty()`、`_edit()`、`_update()` 与全部状态文案行为不变。

`res://scenes/ui/model_window.tscn`：根 `Window`（名 `ModelWindow`）挂 `src/ui/model_window.gd`，依赖由 `setup(settings, executor)` 注入。场景提供 `MarginContainer`（四边 18）→ `ScrollContainer`（禁用横向滚动）→ `VBoxContainer`（间距 10）内的标题、选择器插入位、`%Requirements`、`%Enabled`「启用此用途的本地模型」、四组「14 号标签 + 输入框」（`%provider`、`%base_url`、`%api_key`（密文）、`%ModelName`）、`%Json`「声明支持 JSON 输出」、`%Thinking`「声明支持 thinking」、「高级 JSON 参数（非流式）」标签与 `%Params`（纵向最小高度 120，边界换行）、`%CopyRow`（复制插入位 + `%CopyButton`「复制该用途配置」）、`%SaveButton`「保存当前用途」（`PrimaryButton`）、`%TestButton`「手动测试当前配置」、`%Status`，以及窗口下的 `%PlainDialog`「密钥保护失败」与 `%TestDialog`「测试可能消耗供应商额度」；`_select`、`_edit`、`_config`、`_save`、`_copy_selected`、`_test` 与全部提示文案不变。

`executor` 注入为 `null` 时（测试与未接入执行器的场景），`_ready()` 立即释放 `%TestButton` 与 `%TestDialog` 并把对应成员置空，节点集合与改造前一致；注入非空时二者参与布局与信号连接。

`UnifiedDropdown` 尚未节点化，窗口场景在需要非末位插入的位置提供一个不可见 `Control` 标记节点（`%SelectorSlot`、`%CopySlot`、`%RelationshipPresets`、`%SpeakingStylePresets`）：脚本把代码实例化的下拉加入父容器后用 `move_child` 移到标记所在位置并释放标记。标记不可见，`Container` 布局会忽略不可见的 `Control`，因此插入前后的布局与既有实现一致。

从哪个 interface 验证：`tests/test_ui_scenes.gd` 按同一张表断言两个场景的存在性、根节点名与类型、根脚本、关键节点 `unique_name_in_owner` 与 `%Name` 解析、`setup()` 暴露且 `_init` 无参数，以及从代码搬入场景的属性、字号与样式盒取值；`tests/test_preferences.gd`、`tests/test_model_settings.gd`、`tests/test_application_drafts.gd` 从窗口的公开行为（脏草稿关窗确认、草稿参与关闭守卫、菜单打开独立窗口）回归。