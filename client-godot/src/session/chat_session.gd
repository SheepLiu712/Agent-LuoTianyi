extends Node
signal message_audio_changed(id: String, state: Dictionary)
signal message_image_changed(id: String, state: Dictionary)
signal changed
signal state_changed(state: Dictionary)
signal expression_requested(command: String)
signal mouth_changed(value: float)
signal user_avatar_changed(texture: Texture2D)
const Audio = preload("res://src/media/reply_audio.gd")
const Attachment = preload("res://src/media/image_attachment.gd")
const MessageUUID = preload("res://src/domain/message_uuid.gd")
const AccountScope = preload("res://src/domain/account_scope.gd")
## 流式正文合并提交窗口：结束包与错误不受此限制。
const STREAM_SAVE_MS := 500
## 服务端认可的触摸部位；其余输入直接丢弃，不计入触摸次数。
const TOUCH_AREAS: Array[String] = ["头", "手", "身体"]
var _transport: Node
var _media: Node
var _logger: RefCounted
var _messages: Array[Dictionary] = []
var _by_id: Dictionary = {}
var _replies: Dictionary = {}
var _finished: Dictionary = {}
var _logged_replies: Dictionary = {}
var _state := {"phase":"idle", "code":"", "thinking":false, "speaking":false}
var _history: Node
var _waiting_history := false
var _pending_history: Dictionary = {}
## 已提交到 local_messages 的待发记录。boundary 放行时只发送这些记录，
## 仍在 save_local 中的记录由保存协程在提交成功后自行发送。
var _committed_local: Dictionary = {}
var _outgoing: Dictionary = {}
var _delivering: Dictionary = {}
var _wire_ids: Dictionary = {}
var _reading: RefCounted
var _images: Node
var _models: Node
var _touch_areas: Array[String] = []
var _touch_count := 0
var _last_touch_ms := -1000
var _typing := false
var _persistence: RefCounted
var _history_root := ""
var _media_migration: Object
var _avatar_source: Node

func _init(transport: Node, logger: RefCounted = null, media: Node = null, history: Node = null, reading: RefCounted = null, images: Node = null, models: Node = null, persistence: RefCounted = null) -> void:
	_transport = transport
	_logger = logger
	_models = models
	_persistence = persistence
	if models != null:
		add_child(models)
		# 模型结果必须能跨短暂断线重试；request_id 保证服务端可幂等处理。
		models.completed.connect(func(response): _transport.send_event("llm_response",response,true,true))
	_media = media if media != null else Audio.new(logger)
	add_child(_media)
	_media.playback_finished.connect(_audio_finished)
	_media.message_audio_changed.connect(func(id,state):
		if _by_id.has(id):
			message_audio_changed.emit(id,state))
	_media.mouth_changed.connect(func(value): mouth_changed.emit(value))
	_media.state_changed.connect(func(state):
		if state.playing:
			_touch_areas.clear()
			_touch_count = 0
		_state.speaking = state.playing
		state_changed.emit(get_state()))
	add_child(transport)
	transport.state_changed.connect(_connection_changed)
	transport.delivery_changed.connect(_delivery_changed)
	transport.event_received.connect(_receive)
	transport.system_error.connect(_system_error)
	_history = history
	if history != null:
		add_child(history)
		history.page_received.connect(_latest_page)
		history.older_page.connect(_history_page)
		history.restore_page.connect(_restore_page)
		if history.has_signal("delivery_reconciled"):
			history.delivery_reconciled.connect(_delivery_reconciled)
		history.boundary_ready.connect(_release_history_sends)
		history.state_changed.connect(func(_value):
			_update_reading()
			state_changed.emit(get_state()))
	_reading = reading
	changed.connect(_update_reading)
	_images = images if images != null else preload("res://src/storage/history_image_source.gd").new()
	add_child(_images)
	_images.changed.connect(func(id,state): message_image_changed.emit(id,state))

func start(session: Dictionary) -> Error:
	stop()
	# 先校验并建立 transport，再启动账号级历史/媒体/模型服务；transport 失败不得留下账号资源。
	var transport_result: Error = _transport.start(session)
	if transport_result != OK:
		_transport.stop()
		return transport_result
	if _models != null:
		_models.start()
	if _reading != null:
		_reading.start(session.get("server",""),session.get("username",""))
	if _images != null:
		_images.start(session)
	var scope_result: Error = _media.set_scope(session.get("server",""),session.get("username",""))
	if scope_result != OK:
		stop()
		return scope_result
	if _history != null:
		_waiting_history = true
		_history.start(_history_session(session))
	return OK


## 历史库根目录由装配层给；作用域始终由账号派生，调用方不必重复拼。
func set_history_root(path: String) -> void:
	_history_root = path


## Python 媒体导入只在这里转交，会话层不碰文件系统也不认识具体实现。
func set_media_migration(migration: Object) -> void:
	_media_migration = migration


## 兼容旧装配入口：语义已扩展到语音与图片。
func set_audio_migration(migration: Object) -> void:
	set_media_migration(migration)


## 迁移落盘后让气泡重新问一次缓存：播放条不会因为早先的空结果一直缺席。
func refresh_message_audio(ids: Array) -> void:
	if _media != null:
		_media.forget_audio(ids)


## 图片导入落盘后让气泡重新读取缓存；未加载的 id 由下次 ensure 自然命中。
func refresh_message_images(ids: Array) -> void:
	if _images != null:
		_images.refresh(ids)


func _history_session(session: Dictionary) -> Dictionary:
	var next := session.duplicate(true)
	next.history_root = str(next.get("history_root", _history_root))
	next.scope = AccountScope.key(str(session.get("server", "")), str(session.get("username", "")))
	return next

func set_typing(active: bool, text_length: int = 0) -> Error:
	var next := active and text_length > 0
	if next == _typing and (not next or text_length == 0):
		return OK
	_typing = next
	if _state.phase != "ready":
		return OK
	var length := clampi(text_length, 0, 4096) if next else 0
	var id: String = _transport.send_event("user_typing", {"text_length":length}, false)
	return OK if not id.is_empty() else ERR_UNAVAILABLE

func send_text(text: String) -> String:
	if text.strip_edges().is_empty() or _state.phase in ["idle", "auth_rejected"]:
		return ""
	set_typing(false)
	var message := _make_local_message("text", text)
	return _queue_or_send(message, "user_text", {"message": text})


func send_image(bytes: PackedByteArray, mime: String) -> String:
	if _state.phase in ["idle", "auth_rejected"]:
		return ""
	var attachment := Attachment.from_bytes(bytes, mime)
	if not attachment.ok:
		_system_error(attachment.code, "", _attachment_error_detail(str(attachment.code)))
		return ""
	var payload := {
		"image_base64": Marshalls.raw_to_base64(attachment.bytes),
		"mime_type": attachment.mime,
		"image_client_path": "",
	}
	var id := _queue_or_send(_make_local_message("image", ""), "user_image", payload)
	if id.is_empty():
		return ""
	_images.store_local(id, attachment.bytes)
	_clear_image_error()
	return id


## 本地接纳即落盘：重启后能辨认「未发送 / 结果不确定」，但不重建发送队列。
func _make_local_message(kind: String, text: String) -> Dictionary:
	return {
		"id": MessageUUID.create(),
		"id_source": "local",
		"origin": "local",
		"role": "user",
		"type": kind,
		"text": text,
		"timestamp": Time.get_unix_time_from_system(),
		"status": "pending" if not _waiting_history else "waiting_history",
		"code": "",
		"content_origin": "local",
		"stream_complete": true,
	}


func _queue_or_send(message: Dictionary, event_type: String, payload: Dictionary) -> String:
	if not _waiting_history:
		return _send_now(message, event_type, payload)
	if _pending_history.size() >= 128:
		_system_error("SEND_REJECTED", "", "waiting-history queue is full (128 messages)")
		return ""
	if _too_large(payload):
		_system_error("SEND_REJECTED", "", "message exceeds the 8 MiB payload limit")
		return ""
	message.status = "waiting_history"
	var entry := {"event": event_type, "payload": payload.duplicate(true)}
	_pending_history[message.id] = entry
	_outgoing[message.id] = entry
	var accepted := _accept_local(message)
	_persist_and_deliver(message, entry)
	return accepted


func _send_now(message: Dictionary, event_type: String, payload: Dictionary) -> String:
	var entry := {"event": event_type, "payload": payload.duplicate(true)}
	_outgoing[message.id] = entry
	message.status = "pending"
	var accepted := _accept_local(message)
	# 先落本地尾部，提交成功后才允许网络发送。
	_persist_and_deliver(message, entry)
	return accepted


## 本地尾部提交 → 视 boundary 状态立即发送或继续排队。
func _persist_and_deliver(message: Dictionary, entry: Dictionary) -> void:
	var id := str(message.id)
	if _persistence != null:
		var saved: Dictionary = await _persistence.save_local(message.duplicate(true), entry)
		if not saved.ok:
			_pending_history.erase(id)
			_committed_local.erase(id)
			_mark_failed(message, "CACHE_WRITE_FAILED")
			return
		if _waiting_history:
			_committed_local[id] = true
	if _waiting_history:
		if message.status != "waiting_history":
			message.status = "waiting_history"
			changed.emit()
		return
	_committed_local.erase(id)
	await _deliver(message, entry)


func _deliver(message: Dictionary, entry: Dictionary) -> void:
	var id := str(message.id)
	if message.status in ["sending", "sent"] or _delivering.has(id):
		return
	if not _by_id.has(id):
		return
	_delivering[id] = true
	var payload: Dictionary = entry.get("payload", {}).duplicate(true)
	payload["llm_mode"] = {"types": _model_types()}
	var wire: String = _transport.send_event(str(entry.get("event", "")), payload, true)
	if wire.is_empty():
		_delivering.erase(id)
		_system_error("SEND_REJECTED", "", "transport rejected %s (state %s)" % [
			str(entry.get("event", "")), str(_transport.get_state().get("code", ""))])
		_mark_failed(message, "SEND_REJECTED")
		return
	_wire_ids[wire] = id
	message.status = "sending"
	_outgoing[id] = entry
	_delivering.erase(id)
	var persisted: Dictionary = await _persist_state(message, {"attempts_delta": 1})
	if not persisted.ok:
		# 帧已经交给传输层，不能让库里的 pending 在重启后再次自动发送。
		message.status = "failed"
		message.code = "DELIVERY_UNCERTAIN"
		changed.emit()
		await _persist_state(message)
		return
	changed.emit()


func _accept_local(message: Dictionary) -> String:
	_messages.append(message)
	_by_id[message.id] = message
	if _logger != null:
		_logger.record_as("business", "message_queued", {"reply_id": message.id, "phase":"queued", "code":"OK"})
		var text: Variant = message.get("text", "")
		_logger.record_as("system", "state_snapshot", {"level":"DEBUG",
			"data":{"kind":str(message.get("type", "")), "text_chars":str(text).length() if text is String else 0, "has_image":message.get("image") != null}})
	changed.emit()
	return message.id


func _too_large(payload: Dictionary) -> bool:
	var text: Variant = payload.get("message")
	return text is String and text.to_utf8_buffer().size() > 8 * 1024 * 1024 - 1024


func _clear_image_error() -> void:
	if not _state.code in ["INVALID_IMAGE", "IMAGE_FORMAT", "IMAGE_DIMENSIONS", "IMAGE_TOO_LARGE", "SEND_REJECTED"]:
		return
	_state.code = ""
	state_changed.emit(get_state())

func set_image_selecting(active: bool) -> void:
	if _state.phase == "ready": _transport.send_event("user_image_selecting" if active else "user_image_selecting_cancel", {}, false)

func record_touch(areas: Array[String]) -> void:
	if _state.phase != "ready" or _media.get_state().playing:
		_touch_areas.clear()
		_touch_count = 0
		return
	var valid := false
	for area in areas:
		if area in TOUCH_AREAS:
			valid = true
			if not _touch_areas.has(area): _touch_areas.append(area)
	if not valid: return
	_touch_count += 1
	var now := Time.get_ticks_msec()
	if now - _last_touch_ms < 1000: return
	# 触区按协议规范名发送：服务端优先读 touch_area，其余两键是本端统计，服务端忽略。
	_transport.send_event("user_touch", {"touch_area":_touch_areas.duplicate(), "touch_count":_touch_count, "time_since_last_sent_touch":(now - _last_touch_ms) / 1000.0}, false)
	_last_touch_ms = now
	_touch_count = 0
	_touch_areas.clear()

func get_messages() -> Array[Dictionary]:
	return _messages.duplicate(true)


## UI 只读视图：浅拷贝避免每个流式分片都深拷贝整份消息正文。
## 调用方不得修改返回的 Dictionary；需要独立快照时仍用 get_messages()。
func get_messages_view() -> Array[Dictionary]:
	return _messages.duplicate()

func get_state() -> Dictionary:
	var result := _state.duplicate(true)
	result.history = get_history_state()
	return result

## 头像源由装配层给出；这里只转发，不参与消息状态，所以不改动 changed 信号。
func set_avatar(source: Node) -> void:
	if _avatar_source != null and _avatar_source.avatar_changed.is_connected(_avatar_changed):
		_avatar_source.avatar_changed.disconnect(_avatar_changed)
	_avatar_source = source
	if source != null:
		source.avatar_changed.connect(_avatar_changed)
		_avatar_changed(source.get_texture())

func get_user_avatar() -> Texture2D:
	return _avatar_source.get_texture() if _avatar_source != null else null

func _avatar_changed(texture: Texture2D) -> void:
	user_avatar_changed.emit(texture)

func set_volume(value: float) -> void:
	_media.set_volume(value)

func get_audio_state() -> Dictionary:
	return _media.get_state()

func stop_voice() -> void:
	_media.stop_current()

func stop() -> void:
	if _typing and _state.phase == "ready":
		_transport.send_event("user_typing", {"text_length":0}, false)
	_typing = false
	_touch_areas.clear()
	_touch_count = 0
	_last_touch_ms = -1000
	if _models != null:
		_models.stop()
	if _images != null:
		_images.stop()
	if _media_migration != null:
		_media_migration.stop()
	# 先让待发消息得到确定的失败状态并落库，再清空映射；
	# 否则 transport.stop() 回调到达时 _wire_ids 已丢失，UI 会永远停在“发送中”。
	_fail_pending_history()
	_transport.stop()
	_waiting_history = false
	_pending_history.clear()
	_committed_local.clear()
	_outgoing.clear()
	_delivering.clear()
	_wire_ids.clear()
	if _history != null:
		_history.stop()
	if _reading != null:
		_reading.start("","")
	_media.set_scope("", "")
	_messages.clear()
	_by_id.clear()
	_replies.clear()
	_finished.clear()
	_logged_replies.clear()
	_state = {"phase":"idle", "code":"", "thinking":false, "speaking":false}
	changed.emit()
	state_changed.emit(get_state())


## 退出时还没获得发送机会的本地消息不能悄悄消失：标记失败并保留在缓存，
## 下次登录由历史库恢复为“发送失败”，而不是永远显示 waiting_history。
func _fail_pending_history() -> void:
	for id in _pending_history:
		if not _by_id.has(id):
			continue
		_by_id[id].status = "failed"
		_by_id[id].code = "SEND_CANCELLED"
		_committed_local.erase(id)
		_persist_status(id)

func _connection_changed(connection: Dictionary) -> void:
	if _logger != null:
		_logger.record_as("business", "connection_state", {"phase":connection.get("phase","unknown"),
			"code":connection.get("code",""), "reason":"connection",
			"level":"WARN" if connection.get("code","") not in ["", "OK"] else "INFO"})
	_state.phase = connection.phase
	_state.code = connection.code
	if connection.phase != "ready":
		_typing = false
		_touch_areas.clear()
		_touch_count = 0
		_state.thinking = false
		for id in _replies:
			_finished[id] = true
		_replies.clear()
		_media.reset()
	state_changed.emit(get_state())

func _delivery_changed(wire_id: String, status: String, code: String) -> void:
	var id := str(_wire_ids.get(wire_id, wire_id))
	var next_state := _delivery_state(status)
	var next_code := code
	if status == "uncertain" and next_code.is_empty():
		next_code = "DELIVERY_UNCERTAIN"
	if _logger != null:
		_logger.record_as("business", "message_delivery", {"reply_id":id,"phase":next_state,"code":next_code,
			"level":"WARN" if next_state == "failed" else "INFO"})
	if not _by_id.has(id):
		return
	_by_id[id].status = next_state
	_by_id[id].code = next_code
	if next_state == "sent":
		_outgoing.erase(id)
	_committed_local.erase(id)
	_persist_state(_by_id[id])
	changed.emit()


## 传输层状态映射到新的本地尾部状态机：不再产生 uncertain。
static func _delivery_state(status: String) -> String:
	match status:
		"sent":
			return "sent"
		"failed", "uncertain":
			return "failed"
		_:
			return "sending"

func _system_error(code: String, reply_id: String = "", detail: String = "") -> void:
	if _logger != null:
		var fields := {"code":code, "detail":detail, "phase":"error", "level":"ERROR"}
		if not reply_id.is_empty():
			fields.reply_id = reply_id
		_logger.record_as("business", "message_error", fields)
	_state.code = code
	state_changed.emit(get_state())

func _receive(event: Dictionary) -> void:
	var payload: Dictionary = event.payload
	if event.type == "agent_state_changed":
		if payload.get("state") in ["thinking", "waiting"]:
			_state.thinking = payload.state == "thinking"
			state_changed.emit(get_state())
	elif event.type == "agent_message":
		_receive_reply(payload, event.get("ts"))
	elif event.type == "llm_request" and _models != null:
		_models.submit(payload)

func _receive_reply(payload: Dictionary, event_timestamp: Variant = null) -> void:
	var id: Variant = payload.get("uuid")
	if not id is String or id.is_empty() or (payload.get("text") != null and not payload.text is String):
		_system_error("INVALID_RESPONSE", "", "agent_message is missing a valid uuid or text")
		return
	_log_reply(id, payload)
	if _finished.has(id):
		return
	if not _replies.has(id):
		_replies[id] = {"text":"", "expression":"", "display":true, "final":false, "audio_error":false, "played":false,"ephemeral":false, "timestamp":_reply_timestamp(event_timestamp)}
	var reply: Dictionary = _replies[id]
	reply.ephemeral = reply.ephemeral or payload.get("is_ephemeral",false) == true
	if reply.final:
		return
	_update_reply(reply, payload)
	_media.append_reply_audio(id, payload.audio if payload.get("audio") is String else "", reply.final,
		reply.audio_error, payload.get("is_ephemeral",false) == true, str(payload.get("error_detail", "")))
	_present_replies()
func _audio_finished(id: String, code: String) -> void:
	if not _replies.has(id):
		return
	_replies[id].played = true
	var detail := str(_media.get_message_audio(id).get("detail", ""))
	if not detail.is_empty():
		_replies[id].audio_detail = detail
	if not code.is_empty() and code != "STOPPED":
		_replies[id].audio_error = true
		_replies[id].audio_code = "REMOTE_AUDIO_ERROR" if code == "REMOTE_AUDIO_ERROR" else "AUDIO_ERROR"
	_present_replies.call_deferred()

func _present_replies() -> void:
	for id in _replies.keys():
		var reply: Dictionary = _replies[id]
		_present_message(id, reply)
		if not reply.expression.is_empty():
			expression_requested.emit(reply.expression)
			reply.expression = ""
		_report_reply_audio_error(id, reply)
		if not reply.played:
			_media.play_reply(id)
			break
		_finished[id] = true
		_replies.erase(id)

## 正式回复按服务器 UUID 原位更新，临时消息只进内存。
func _present_message(id: String, reply: Dictionary) -> void:
	if not reply.display or reply.text.is_empty():
		return
	var message: Dictionary = _upsert_reply_message(id, reply)
	_save_reply(message, reply)
	changed.emit()


func _upsert_reply_message(id: String, reply: Dictionary) -> Dictionary:
	if not _by_id.has(id):
		var message := {"id":id, "id_source":"server", "origin":"live", "role":"assistant", "type":"text",
			"text":reply.text, "timestamp":reply.timestamp, "status":"received", "code":"",
			"is_ephemeral":reply.ephemeral, "content_origin":"live", "stream_complete":reply.final}
		_by_id[id] = message
		_messages.append(message)
		return message
	var existing: Dictionary = _by_id[id]
	existing.text = reply.text
	existing.is_ephemeral = reply.ephemeral
	existing.stream_complete = reply.final
	return existing


## 流式正文最多每 500 毫秒落一次；结束包立即落；临时消息从不落。
func _save_reply(message: Dictionary, reply: Dictionary) -> void:
	if _persistence == null or message.is_ephemeral:
		return
	var now := Time.get_ticks_msec()
	if not message.stream_complete and now - int(reply.get("saved_ms", 0)) < STREAM_SAVE_MS:
		return
	reply.saved_ms = now
	_persistence.save_live(message.duplicate(true))


func _report_reply_audio_error(id: String, reply: Dictionary) -> void:
	if not reply.audio_error or reply.get("error_reported", false):
		return
	reply.error_reported = true
	_system_error(reply.get("audio_code", "AUDIO_ERROR"), id, str(reply.get("audio_detail", "")))

func _reply_timestamp(raw: Variant) -> float:
	if (raw is int or raw is float) and is_finite(float(raw)) and raw > 0:
		return float(raw) / 1000.0
	return Time.get_unix_time_from_system()

func _exit_tree() -> void:
	stop()

func get_message_audio(id: String) -> Dictionary:
	return _media.get_message_audio(id)

func replay(id: String) -> Error:
	if not _by_id.has(id) or _by_id[id].role != "assistant":
		return ERR_DOES_NOT_EXIST
	return _media.replay(id)

func pause_replay() -> void:
	_media.pause_replay()

func resume_replay() -> void:
	_media.resume_replay()

func stop_replay() -> void:
	_media.stop_replay()

func clear_cache(older_than_days: int = 0) -> Error:
	var result: Error = _media.clear_cache(older_than_days)
	if result != OK:
		_system_error("CACHE_CLEAR_FAILED", "", error_string(result))
	return result

func get_history_state() -> Dictionary:
	return _history.get_state() if _history != null else {"phase":"idle","code":"","count":0,"incomplete":false}

func retry_history() -> void:
	if _history != null:
		_history.retry()

func skip_history() -> void:
	if _history != null:
		_history.skip()


func reset_history_storage() -> void:
	if _history != null:
		_history.reset_storage()


func _release_history_sends() -> void:
	_waiting_history = false
	var queued := _pending_history.duplicate()
	_pending_history.clear()
	for id in queued:
		# restore_page 可能已经用历史窗口替换了视图；缺失条目不能按下标访问。
		if not _by_id.has(id):
			_committed_local.erase(id)
			continue
		# save_local 尚未提交：保存协程会在成功后看到 boundary 已释放并自行发送。
		if _persistence != null and not _committed_local.has(id):
			continue
		_committed_local.erase(id)
		await _deliver(_by_id[id], queued[id])
	changed.emit()


## 本地缓存先显示：用历史窗口替换服务端视图，但保留等待历史期间用户已产生的
## 本地消息。它们可能已经/正在发送，不能因为一次缓存刷新而从界面消失。
func _restore_page(messages: Array[Dictionary]) -> void:
	var next_messages: Array[Dictionary] = []
	var next_by_id := {}
	_merge_history_page(messages, next_messages, next_by_id)
	_append_local_tail(next_messages, next_by_id)
	_messages = next_messages
	_by_id = next_by_id
	_adopt_restored_local(messages)
	_request_missing_audio(_messages)
	changed.emit()


## 重启后恢复本地尾部的发送意图：pending 与 waiting_history 继续等待 boundary，
## failed 保留原状态供用户手动重试；sending 已由存储层转成 failed。
func _adopt_restored_local(messages: Array[Dictionary]) -> void:
	for message in messages:
		if str(message.get("id_source", "")) != "local":
			continue
		var payload: Variant = message.get("payload", {})
		if not payload is Dictionary or not payload.has("event"):
			continue
		var id := str(message.id)
		_outgoing[id] = payload
		if str(message.get("status", "")) in ["pending", "waiting_history"]:
			_pending_history[id] = payload
			# 这行本来就来自 local_messages，boundary 放行时可以直接发送。
			_committed_local[id] = true

func _merge_history_page(messages: Array[Dictionary], next_messages: Array[Dictionary], next_by_id: Dictionary) -> void:
	for message in messages:
		var id := str(message.get("id", ""))
		if id.is_empty() or next_by_id.has(id):
			continue
		if _by_id.has(id):
			var existing: Dictionary = _by_id[id]
			if existing.get("timestamp") == null:
				existing.timestamp = message.get("timestamp")
			next_messages.append(existing)
			next_by_id[id] = existing
		else:
			next_messages.append(message)
			next_by_id[id] = message

func _append_local_tail(next_messages: Array[Dictionary], next_by_id: Dictionary) -> void:
	# 缓存窗口之外的本地消息保留在末尾，维持用户看到的时间顺序。
	for message in _messages:
		var id := str(message.get("id", ""))
		if id.is_empty() or next_by_id.has(id):
			continue
		if str(message.get("id_source", "")) != "local" and not _pending_history.has(id):
			continue
		next_messages.append(message)
		next_by_id[id] = message


func load_older_history() -> void:
	if _history != null:
		_history.load_older()


func unsaved_count() -> int:
	return 0 if _persistence == null else int(_persistence.unsaved_count())


## 关闭前的准备：停止新增网络请求，并收口流式待写。
func prepare_close() -> void:
	set_typing(false)
	if _history != null:
		_history.pause_catchup(true)


func close_persistence() -> Dictionary:
	if _persistence == null:
		return {"ok": true, "code": "OK", "data": {}}
	return await _persistence.flush()


func _persist_status(id: String) -> void:
	if not _by_id.has(id):
		return
	_persist_state(_by_id[id])


func _persist_state(message: Dictionary, patch: Dictionary = {}) -> Dictionary:
	var ok := {"ok": true, "code": "OK", "data": {}}
	if _persistence == null:
		return ok
	var next := patch.duplicate(true)
	next["state"] = str(message.get("status", "pending"))
	next["error_code"] = str(message.get("code", ""))
	next["content"] = str(message.get("text", ""))
	next["stream_complete"] = bool(message.get("stream_complete", true))
	return await _persistence.update_local(str(message.id), next)


## 重试与首次发送共用的“先提交本地意图”：失败时绝不触碰网络。
func _save_intent(message: Dictionary, entry: Dictionary) -> Dictionary:
	if _persistence == null:
		return {"ok": true, "code": "OK", "data": {}}
	return await _persistence.save_local(message.duplicate(true), entry)


func _mark_failed(message: Dictionary, code: String) -> void:
	message.status = "failed"
	message.code = code
	changed.emit()
	_persist_state(message)

func _history_page(messages: Array[Dictionary]) -> void:
	var prepend: Array[Dictionary] = []
	for message in messages:
		if _by_id.has(message.id):
			# 历史以 UUID 为唯一身份，不做文本/时间匹配；搬入历史位置时保留实时内容。
			var existing: Dictionary = _by_id[message.id]
			existing.timestamp = message.timestamp
			existing.id_source = "server"
			_messages.erase(existing)
			prepend.append(existing)
		else:
			_by_id[message.id] = message
			prepend.append(message)
	_messages = prepend + _messages
	_request_missing_audio(messages)
	changed.emit()


## 首屏最新页并入缓存窗口：库里的 timeline_order 已经是权威顺序，已存在的 UUID
## 只原位更新时间，未知行贴到页内下一个锚点之前。整页前插会把更新的本地发送记录和
## 后续回复挤到这一页之前，重启后看起来就像旧消息一直停在最新位置。
func _latest_page(messages: Array[Dictionary]) -> void:
	var pending: Array[Dictionary] = []
	for message in messages:
		if not _by_id.has(message.id):
			pending.append(message)
			continue
		var existing: Dictionary = _by_id[message.id]
		existing.timestamp = message.timestamp
		existing.id_source = "server"
		_insert_pending(pending, _message_index(str(message.id)))
		pending.clear()
	_insert_pending(pending, _latest_tail())
	_request_missing_audio(messages)
	changed.emit()


## 页内未知的连续一段贴在下一个已知锚点之前；没有后续锚点时落到窗口尾部。
func _insert_pending(pending: Array[Dictionary], index: int) -> void:
	var cursor := maxi(index, 0)
	for message in pending:
		_by_id[message.id] = message
		_messages.insert(cursor, message)
		cursor += 1


## 无锚点时：窗口里已有服务器消息，说明最新页排在缓存之后；只有本机记录
## （首屏跳过或历史失败）时，服务器历史仍在本机记录之前。
func _latest_tail() -> int:
	for message in _messages:
		if str(message.get("id_source", "server")) != "local":
			return _messages.size()
	return 0


## 增量迁移的触发点：只针对刚进入视野的这一页里、属于对方的消息。
## 后台补齐的页不经过这里（history_sync 不为它发信号），所以不会偷偷扫盘。
func _request_missing_audio(messages: Array[Dictionary]) -> void:
	if _media_migration == null:
		return
	var ids: Array = []
	for message in messages:
		if str(message.get("role", "")) != "assistant":
			continue
		var id := str(message.get("id", ""))
		if not id.is_empty():
			ids.append(id)
	if not ids.is_empty():
		_media_migration.request_ids(ids)

## 新的发送状态机不再需要主动对账；历史页会直接确认并移除本地副本。
func request_reconcile() -> void:
	return


## 服务器历史已确认的本地副本：只移除仍是 local 身份的行，
## 已并入服务器页的同 id 消息必须保留。
func _delivery_reconciled(ids: Array) -> void:
	if ids.is_empty():
		return
	var removed := false
	for index in range(_messages.size() - 1, -1, -1):
		var message: Dictionary = _messages[index]
		var id := str(message.id)
		if not ids.has(id):
			continue
		if str(message.get("id_source", "")) != "local":
			continue
		_by_id.erase(id)
		_pending_history.erase(id)
		_committed_local.erase(id)
		_outgoing.erase(id)
		_messages.remove_at(index)
		removed = true
	if removed:
		changed.emit()


## 用户手动重试：只接受本地失败记录，sending/sent 永不重发。
func retry_message(id: String) -> bool:
	if not _by_id.has(id):
		return false
	var message: Dictionary = _by_id[id]
	if str(message.get("id_source", "")) != "local" or str(message.get("status", "")) != "failed":
		return false
	var entry: Variant = _outgoing.get(id, _entry_from_message(message))
	if not entry is Dictionary or not entry.has("event"):
		return false
	_outgoing[id] = entry
	message.code = ""
	if _waiting_history:
		message.status = "waiting_history"
		_pending_history[id] = entry
		changed.emit()
		var queued: Dictionary = await _save_intent(message, entry)
		if not queued.ok:
			_pending_history.erase(id)
			_committed_local.erase(id)
			_mark_failed(message, str(queued.code))
			return false
		if not _waiting_history:
			# boundary 在保存期间释放，而这条记录当时还没提交；现在补发。
			_committed_local.erase(id)
			await _deliver(message, entry)
			return true
		_committed_local[id] = true
		changed.emit()
		return true
	message.status = "pending"
	changed.emit()
	var saved: Dictionary = await _save_intent(message, entry)
	if not saved.ok:
		_mark_failed(message, str(saved.code))
		return false
	await _deliver(message, entry)
	return true


## 删除本地失败记录；服务器确认过的历史不允许从这里删除。
func delete_message(id: String) -> bool:
	if not _by_id.has(id) or str(_by_id[id].get("id_source", "")) != "local":
		return false
	if _persistence != null:
		var deleted: Dictionary = await _persistence.delete_local(id)
		if not deleted.ok:
			return false
	_by_id.erase(id)
	_pending_history.erase(id)
	_committed_local.erase(id)
	_outgoing.erase(id)
	for wire in _wire_ids.keys():
		if str(_wire_ids[wire]) == id:
			_wire_ids.erase(wire)
	for index in range(_messages.size() - 1, -1, -1):
		if str(_messages[index].id) == id:
			_messages.remove_at(index)
			break
	changed.emit()
	return true


static func _entry_from_message(message: Dictionary) -> Dictionary:
	if str(message.get("type", "text")) != "text":
		return {}
	return {"event": "user_text", "payload": {"message": str(message.get("text", ""))}}


func _message_index(id: String) -> int:
	for index in _messages.size():
		if str(_messages[index].id) == id:
			return index
	return -1


func get_reading_state() -> Dictionary:
	return _reading.get_state() if _reading != null else {"pending":true,"manual":false,"located":false,"target_id":"","reason":""}

func note_read_interaction() -> void:
	if _reading != null:
		_reading.interact()

func reading_located() -> void:
	if _reading != null:
		_reading.located()


## “回到最新”优先于未读定位：消费目标后，后续自动定位不得再把用户拉回旧消息。
func dismiss_unread() -> void:
	if _reading != null:
		_reading.dismiss()


func report_visible_messages(ids: Array[String], foreground: bool) -> void:
	if _reading != null:
		var error: Error = _reading.report_visible(ids,foreground)
		if error != OK:
			_system_error("SAVE_FAILED", "", error_string(error))

func _update_reading() -> void:
	if _reading != null:
		_reading.update(_messages,get_history_state())

func request_message_image(id: String, retry: bool = false) -> void:
	var message: Dictionary = _by_id.get(id, {})
	if _images == null or message.get("type") != "image":
		return
	if str(message.get("id_source", "server")) == "local":
		_images.ensure_local(id)
	elif retry:
		_images.retry(id)
	else:
		_images.ensure(id)

func get_message_image(id: String) -> Dictionary:
	return _images.get_state(id) if _images != null else {"status":"idle","texture":null,"original_size":Vector2i.ZERO,"code":""}

func preview_message_image(id: String) -> Texture2D:
	return _images.preview(id) if _images != null and _by_id.get(id,{}).get("type") == "image" else null

func _model_types() -> Array:
	return _models.enabled_types() if _models != null else []

func _log_reply(id: String, payload: Dictionary) -> void:
	if _logger == null or _logged_replies.has(id):
		return
	var final: bool = payload.get("is_final_package", true) == true
	var audio_error: bool = payload.get("audio_error", false) == true
	if not final and not audio_error:
		return
	_logged_replies[id] = true
	_logger.record_as("business", "message_reply_received", _reply_log_fields(id, payload, final, audio_error))

func _reply_log_fields(id: String, payload: Dictionary, final: bool, audio_error: bool) -> Dictionary:
	var has_audio: bool = payload.get("audio") is String and not payload.audio.is_empty()
	var detail := str(payload.get("error_detail", "")) if audio_error else ""
	return {"reply_id":id, "has_audio":has_audio, "audio_chars":payload.audio.length() if has_audio else 0,
		"final":final, "audio_error":audio_error, "phase":"received",
		"code":_reply_code(payload, audio_error), "detail":detail,
		"level":"WARN" if audio_error else "INFO"}

func _reply_code(payload: Dictionary, audio_error: bool) -> String:
	if not audio_error:
		return "OK"
	if payload.get("error_code") in ["TTS_EMPTY", "TTS_STREAM_ERROR", "TTS_CANCELLED"]:
		return str(payload.error_code)
	return "REMOTE_AUDIO_ERROR"

func _update_reply(reply: Dictionary, payload: Dictionary) -> void:
	if payload.get("text") is String and not payload.text.is_empty():
		reply.text = payload.text
	if payload.get("expression") is String and not payload.expression.is_empty():
		reply.expression = payload.expression
	if payload.get("display_in_chat", true) == false:
		reply.display = false
	_update_reply_audio(reply, payload)
	if payload.get("is_final_package", true) == true:
		reply.final = true

func _update_reply_audio(reply: Dictionary, payload: Dictionary) -> void:
	if payload.get("audio_error", false) != true:
		return
	reply.audio_error = true
	reply.audio_code = "REMOTE_AUDIO_ERROR"
	reply.final = true
	if payload.get("error_detail") is String:
		reply.audio_detail = payload.error_detail

func _attachment_error_detail(code: String) -> String:
	match code:
		"IMAGE_TOO_LARGE":
			return "image exceeds the 6 MiB attachment limit"
		"IMAGE_FORMAT":
			return "unsupported image format"
		"IMAGE_DIMENSIONS":
			return "image dimensions exceed the attachment limits"
		"INVALID_IMAGE":
			return "image could not be decoded"
	return "image attachment rejected: %s" % code
