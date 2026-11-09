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
var _state := {"phase":"idle", "code":"", "thinking":false, "speaking":false}
var _history: Node
var _waiting_history := false
var _pending_history: Dictionary = {}
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
var _audio_migration: Object
var _avatar_source: Node

func _init(transport: Node, logger: RefCounted = null, media: Node = null, history: Node = null, reading: RefCounted = null, images: Node = null, models: Node = null, persistence: RefCounted = null) -> void:
	_transport = transport
	_logger = logger
	_models = models
	_persistence = persistence
	if models != null:
		add_child(models)
		models.completed.connect(func(response): _transport.send_event("llm_response",response,false))
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
		history.page_received.connect(_history_page)
		history.older_page.connect(_history_page)
		history.restore_page.connect(_restore_page)
		# 旧夹具可能还没有对账信号；缺了就不接，避免整个 _init 中断。
		if history.has_signal("reconciled"):
			history.reconciled.connect(_reconcile_page)
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


## 语音兜底迁移只在这里转交，会话层不碰文件系统也不认识具体实现。
func set_audio_migration(migration: Object) -> void:
	_audio_migration = migration


## 迁移落盘后让气泡重新问一次缓存：播放条不会因为早先的空结果一直缺席。
func refresh_message_audio(ids: Array) -> void:
	if _media != null:
		_media.forget_audio(ids)


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
		_system_error(attachment.code)
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
		"status": "queued" if not _waiting_history else "waiting_history",
		"code": "",
		"content_origin": "local",
		"stream_complete": true,
	}


func _queue_or_send(message: Dictionary, event_type: String, payload: Dictionary) -> String:
	if not _waiting_history:
		return _send_now(message, event_type, payload)
	if _pending_history.size() >= 128 or _too_large(payload):
		_system_error("SEND_REJECTED")
		return ""
	message.status = "waiting_history"
	_pending_history[message.id] = {"type": event_type, "payload": payload}
	return _accept_local(message)


func _send_now(message: Dictionary, event_type: String, payload: Dictionary) -> String:
	payload["llm_mode"] = {"types": _model_types()}
	var wire := _send_attempt(message.id, event_type, payload)
	if wire.is_empty():
		_system_error("SEND_REJECTED")
		return ""
	message.status = "queued"
	return _accept_local(message)


func _send_attempt(message_id: String, event_type: String, payload: Dictionary) -> String:
	var wire: String = _transport.send_event(event_type, payload, true)
	if wire.is_empty():
		return ""
	_wire_ids[wire] = message_id
	if _persistence != null:
		_persistence.record_attempt(message_id, wire)
	return wire


func _accept_local(message: Dictionary) -> String:
	_messages.append(message)
	_by_id[message.id] = message
	if _persistence != null:
		_persistence.save_live(message.duplicate(true))
	if _logger != null:
		_logger.record("message_queued", {"reply_id": message.id})
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
	if _audio_migration != null:
		_audio_migration.stop()
	_waiting_history = false
	_pending_history.clear()
	_wire_ids.clear()
	if _history != null:
		_history.stop()
	if _reading != null:
		_reading.start("","")
	_transport.stop()
	_media.set_scope("", "")
	_messages.clear()
	_by_id.clear()
	_replies.clear()
	_finished.clear()
	_state = {"phase":"idle", "code":"", "thinking":false, "speaking":false}
	changed.emit()
	state_changed.emit(get_state())

func _connection_changed(connection: Dictionary) -> void:
	if _logger != null:
		_logger.record("connection_state", connection)
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
	if _logger != null:
		_logger.record("message_delivery", {"reply_id":id,"phase":status,"code":code})
	if not _by_id.has(id):
		return
	_by_id[id].status = status
	_by_id[id].code = code
	if _persistence != null:
		_persistence.update_attempt(id, wire_id, status, code)
	changed.emit()
	# 送达结果不确定时主动向服务端核对一次；其余状态不需要。
	if status == "uncertain":
		request_reconcile()

func _system_error(code: String, reply_id: String = "") -> void:
	if _logger != null:
		var fields := {"code":code}
		if not reply_id.is_empty():
			fields.reply_id = reply_id
		_logger.record("system_error", fields)
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
		_system_error("INVALID_RESPONSE")
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
	_media.append_reply_audio(id, payload.audio if payload.get("audio") is String else "", reply.final, reply.audio_error, payload.get("is_ephemeral",false) == true)
	_present_replies()
func _audio_finished(id: String, code: String) -> void:
	if not _replies.has(id):
		return
	_replies[id].played = true
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
	_system_error(reply.get("audio_code", "AUDIO_ERROR"), id)

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
		_system_error("CACHE_CLEAR_FAILED")
	return result

func get_history_state() -> Dictionary:
	return _history.get_state() if _history != null else {"phase":"idle","code":"","count":0,"incomplete":false}

func retry_history() -> void:
	if _history != null:
		_history.retry()

func skip_history() -> void:
	if _history != null:
		_history.skip()

func _release_history_sends() -> void:
	_waiting_history = false
	for id in _pending_history:
		var pending: Dictionary = _pending_history[id]
		pending.payload.llm_mode = {"types":_model_types()}
		var wire: String = _transport.send_event(pending.type,pending.payload,true)
		if wire.is_empty():
			_by_id[id].status = "failed"
			_by_id[id].code = "SEND_REJECTED"
		else:
			_wire_ids[wire] = id
			_by_id[id].status = "queued"
			if _persistence != null:
				_persistence.record_attempt(id, wire)
		_persist_status(id)
	_pending_history.clear()
	changed.emit()


## 本地缓存先显示：整窗口替换，不累加，避免重复进入已展示的消息。
func _restore_page(messages: Array[Dictionary]) -> void:
	_messages.clear()
	_by_id.clear()
	for message in messages:
		_messages.append(message)
		_by_id[message.id] = message
	_request_missing_audio(messages)
	changed.emit()


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
	if _persistence == null or not _by_id.has(id):
		return
	_persistence.save_live(_by_id[id].duplicate(true))

func _history_page(messages: Array[Dictionary]) -> void:
	var prepend: Array[Dictionary] = []
	for message in messages:
		if _by_id.has(message.id):
			# 历史以 UUID 为唯一身份，不做文本/时间匹配；搬入历史位置时保留实时内容。
			var existing: Dictionary = _by_id[message.id]
			existing.timestamp = message.timestamp
			_messages.erase(existing)
			prepend.append(existing)
		else:
			_by_id[message.id] = message
			prepend.append(message)
	_messages = prepend + _messages
	_request_missing_audio(messages)
	changed.emit()


## 增量迁移的触发点：只针对刚进入视野的这一页里、属于对方的消息。
## 后台补齐的页不经过这里（history_sync 不为它发信号），所以不会偷偷扫盘。
func _request_missing_audio(messages: Array[Dictionary]) -> void:
	if _audio_migration == null:
		return
	var ids: Array = []
	for message in messages:
		if str(message.get("role", "")) != "assistant":
			continue
		var id := str(message.get("id", ""))
		if not id.is_empty():
			ids.append(id)
	if not ids.is_empty():
		_audio_migration.request_ids(ids)

## 对账只走历史控制器：会话层不发 HTTP、不写库。
func request_reconcile() -> void:
	if _history != null and _history.has_method("request_reconcile"):
		_history.request_reconcile()


## 对账页按「页内已有 id 当锚点」并入内存，顺序与库里的 timeline_order 一致。
## 已存在的 id 只移动游标，绝不覆盖正文与状态（本地未确认消息、在途流式回复）。
func _reconcile_page(messages: Array[Dictionary], position: String) -> void:
	if _state.phase in ["idle", "auth_rejected"]:
		return
	var cursor := 0 if position == "head" else _reconcile_anchor(messages)
	var added := 0
	for message in messages:
		if _by_id.has(message.id):
			cursor = maxi(cursor, _message_index(str(message.id)) + 1)
			continue
		_by_id[message.id] = message
		_messages.insert(cursor, message)
		cursor += 1
		added += 1
	if added == 0:
		return
	changed.emit()


## 无锚点时的起点：tail 追加到末尾，head 插到最前；
## 有锚点时从页内第一个已知消息开始，它前面的未知块落在它之前。
func _reconcile_anchor(messages: Array[Dictionary]) -> int:
	for message in messages:
		var index := _message_index(str(message.id))
		if index >= 0:
			return index
	return _messages.size()


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

func report_visible_messages(ids: Array[String], foreground: bool) -> void:
	if _reading != null and _reading.report_visible(ids,foreground) != OK:
		_system_error("SAVE_FAILED")

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
	if _logger != null:
		var fields := {"reply_id":id, "has_audio":payload.get("audio") is String and not payload.audio.is_empty(),
			"audio_chars":payload.audio.length() if payload.get("audio") is String else 0,
			"final":payload.get("is_final_package", true), "audio_error":payload.get("audio_error", false)}
		if payload.get("audio_error", false) == true:
			fields.code = payload.error_code if payload.get("error_code") in ["TTS_EMPTY", "TTS_STREAM_ERROR", "TTS_CANCELLED"] else "REMOTE_AUDIO_ERROR"
		_logger.record("reply_received", fields)

func _update_reply(reply: Dictionary, payload: Dictionary) -> void:
	if payload.get("text") is String and not payload.text.is_empty():
		reply.text = payload.text
	if payload.get("expression") is String and not payload.expression.is_empty():
		reply.expression = payload.expression
	if payload.get("display_in_chat", true) == false:
		reply.display = false
	reply.audio_error = reply.audio_error or payload.get("audio_error", false) == true
	if payload.get("audio_error", false) == true:
		reply.audio_code = "REMOTE_AUDIO_ERROR"
	reply.final = reply.final or payload.get("is_final_package", true) == true or reply.audio_error
