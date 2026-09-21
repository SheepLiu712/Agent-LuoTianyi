extends Node
signal message_audio_changed(id: String, state: Dictionary)
signal message_image_changed(id: String, state: Dictionary)
signal changed
signal state_changed(state: Dictionary)
signal expression_requested(command: String)
signal mouth_changed(value: float)
const Audio = preload("res://src/media/reply_audio.gd")
const Attachment = preload("res://src/media/image_attachment.gd")
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

func _init(transport: Node, logger: RefCounted = null, media: Node = null, history: Node = null, reading: RefCounted = null, images: Node = null, models: Node = null) -> void:
	_transport = transport
	_logger = logger
	_models = models
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
		history.boundary_ready.connect(_release_history_sends)
		history.state_changed.connect(func(_value):
			_update_reading()
			state_changed.emit(get_state()))
	_reading = reading
	changed.connect(_update_reading)
	_images = images if images != null else preload("res://src/storage/history_images.gd").new("user://images", logger)
	add_child(_images)
	_images.changed.connect(func(id,state): message_image_changed.emit(id,state))

func start(session: Dictionary) -> Error:
	stop()
	if _models != null:
		_models.start()
	if _reading != null:
		_reading.start(session.get("server",""),session.get("username",""))
	if _images != null:
		_images.start(session)
	_media.set_scope(session.get("server",""),session.get("username",""))
	var result: Error = _transport.start(session)
	if result == OK and _history != null:
		_waiting_history = true
		_history.start(session)
	return result

func send_text(text: String) -> String:
	if text.strip_edges().is_empty() or _state.phase in ["idle","auth_rejected"]:
		return ""
	var id: String
	if _waiting_history:
		if _pending_history.size() >= 128 or text.to_utf8_buffer().size() > 8*1024*1024-1024:
			_system_error("SEND_REJECTED")
			return ""
		id = "local-" + Crypto.new().generate_random_bytes(16).hex_encode()
		_pending_history[id] = {"type":"user_text","payload":{"message":text}}
	else:
		id = _transport.send_event("user_text", {"message":text, "llm_mode":{"types":_model_types()}}, true)
	if id.is_empty():
		_system_error("SEND_REJECTED")
		return ""
	var message := {"id":id, "role":"user", "text":text, "status":"waiting_history" if _waiting_history else "queued", "code":""}
	_messages.append(message)
	_by_id[id] = message
	if _logger != null:
		_logger.record("message_queued", {"reply_id":id})
	changed.emit()
	return id

func send_image(bytes: PackedByteArray, mime: String) -> String:
	if _state.phase in ["idle", "auth_rejected"]: return ""
	var attachment := Attachment.from_bytes(bytes, mime)
	if not attachment.ok:
		_system_error(attachment.code)
		return ""
	var payload := {"image_base64":Marshalls.raw_to_base64(bytes), "mime_type":mime, "image_client_path":"", "llm_mode":{"types":_model_types()}}
	var id: String
	if _waiting_history:
		if _pending_history.size() >= 128:
			_system_error("SEND_REJECTED")
			return ""
		id = "local-" + Crypto.new().generate_random_bytes(16).hex_encode()
		_pending_history[id] = {"type":"user_image", "payload":payload}
	else:
		id = _transport.send_event("user_image", payload, true)
	if id.is_empty():
		_system_error("SEND_REJECTED")
		return ""
	var message := {"id":id,"role":"user","type":"image","text":"","status":"waiting_history" if _waiting_history else "queued","code":""}
	_messages.append(message)
	_by_id[id] = message
	_images.store_local(id, bytes)
	if _state.code in ["INVALID_IMAGE", "IMAGE_FORMAT", "IMAGE_DIMENSIONS", "IMAGE_TOO_LARGE", "SEND_REJECTED"]:
		_state.code = ""
		state_changed.emit(get_state())
	if _logger != null: _logger.record("message_queued", {"reply_id":id})
	changed.emit()
	return id

func set_image_selecting(active: bool) -> void:
	if _state.phase == "ready": _transport.send_event("user_image_selecting" if active else "user_image_selecting_cancel", {}, false)

func record_touch(areas: Array[String]) -> void:
	if _state.phase != "ready" or _media.get_state().playing:
		_touch_areas.clear()
		_touch_count = 0
		return
	var valid := false
	for area in areas:
		if area in ["头", "手", "身体"]:
			valid = true
			if not _touch_areas.has(area): _touch_areas.append(area)
	if not valid: return
	_touch_count += 1
	var now := Time.get_ticks_msec()
	if now - _last_touch_ms < 1000: return
	_transport.send_event("user_touch", {"touchArea":_touch_areas.duplicate(), "touchCount":_touch_count, "timeSinceLastSentTouch":(now - _last_touch_ms) / 1000.0}, false)
	_last_touch_ms = now
	_touch_count = 0
	_touch_areas.clear()

func get_messages() -> Array[Dictionary]:
	return _messages.duplicate(true)

func get_state() -> Dictionary:
	var result := _state.duplicate(true)
	result.history = get_history_state()
	return result

func set_volume(value: float) -> void:
	_media.set_volume(value)

func get_audio_state() -> Dictionary:
	return _media.get_state()

func stop_voice() -> void:
	_media.stop_current()

func stop() -> void:
	_touch_areas.clear()
	_touch_count = 0
	_last_touch_ms = -1000
	if _models != null:
		_models.stop()
	if _images != null:
		_images.stop()
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
		_touch_areas.clear()
		_touch_count = 0
		_state.thinking = false
		for id in _replies:
			_finished[id] = true
		_replies.clear()
		_media.reset()
	state_changed.emit(get_state())

func _delivery_changed(id: String, status: String, code: String) -> void:
	id = _wire_ids.get(id,id)
	if _logger != null:
		_logger.record("message_delivery", {"reply_id":id,"phase":status,"code":code})
	if _by_id.has(id):
		_by_id[id].status = status
		_by_id[id].code = code
		changed.emit()

func _system_error(code: String) -> void:
	if _logger != null:
		_logger.record("system_error", {"code":code})
	_state.code = code
	state_changed.emit(get_state())

func _receive(event: Dictionary) -> void:
	var payload: Dictionary = event.payload
	if event.type == "agent_state_changed":
		if payload.get("state") in ["thinking", "waiting"]:
			_state.thinking = payload.state == "thinking"
			state_changed.emit(get_state())
	elif event.type == "agent_message":
		_receive_reply(payload)
	elif event.type == "llm_request" and _models != null:
		_models.submit(payload)

func _receive_reply(payload: Dictionary) -> void:
	var id: Variant = payload.get("uuid")
	if not id is String or id.is_empty() or (payload.get("text") != null and not payload.text is String):
		_system_error("INVALID_RESPONSE")
		return
	if _logger != null:
		_logger.record("reply_received", {"reply_id":id, "has_audio":payload.get("audio") is String and not payload.audio.is_empty(),
			"audio_chars":payload.audio.length() if payload.get("audio") is String else 0,
			"final":payload.get("is_final_package", true), "audio_error":payload.get("audio_error", false)})
	if _finished.has(id):
		return
	if not _replies.has(id):
		_replies[id] = {"text":"", "expression":"", "display":true, "final":false, "audio_error":false, "played":false,"ephemeral":false}
	var reply: Dictionary = _replies[id]
	reply.ephemeral = reply.ephemeral or payload.get("is_ephemeral",false) == true
	if reply.final:
		return
	if payload.get("text") is String and not payload.text.is_empty():
		reply.text = payload.text
	if payload.get("expression") is String and not payload.expression.is_empty():
		reply.expression = payload.expression
	if payload.get("display_in_chat", true) == false:
		reply.display = false
	reply.audio_error = reply.audio_error or payload.get("audio_error", false) == true
	reply.final = reply.final or payload.get("is_final_package", true) == true or reply.audio_error
	_media.append_reply_audio(id, payload.audio if payload.get("audio") is String else "", reply.final, reply.audio_error, payload.get("is_ephemeral",false) == true)
	_present_replies()

func _audio_finished(id: String, code: String) -> void:
	if not _replies.has(id):
		return
	_replies[id].played = true
	if not code.is_empty() and code != "STOPPED":
		_replies[id].audio_error = true
		_system_error("AUDIO_ERROR")
	_present_replies.call_deferred()

func _present_replies() -> void:
	for id in _replies.keys():
		var reply: Dictionary = _replies[id]
		if reply.display and not reply.text.is_empty():
			if not _by_id.has(id):
				var message := {"id":id, "role":"assistant", "text":reply.text, "status":"received", "code":"","is_ephemeral":reply.ephemeral}
				_by_id[id] = message
				_messages.append(message)
			else:
				_by_id[id].text = reply.text
				_by_id[id].is_ephemeral = reply.ephemeral
			changed.emit()
		if not reply.expression.is_empty():
			expression_requested.emit(reply.expression)
			reply.expression = ""
		if reply.audio_error:
			_system_error("AUDIO_ERROR")
		if not reply.played:
			_media.play_reply(id)
			break
		_finished[id] = true
		_replies.erase(id)

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
	_pending_history.clear()
	changed.emit()

func _history_page(messages: Array[Dictionary]) -> void:
	var prepend: Array[Dictionary] = []
	for message in messages:
		if _by_id.has(message.id):
			# History UUID is authoritative identity, never text/time matching.
			# Preserve live content while moving the item into its history position.
			var existing: Dictionary = _by_id[message.id]
			_messages.erase(existing)
			prepend.append(existing)
		else:
			_by_id[message.id] = message
			prepend.append(message)
	_messages = prepend + _messages
	changed.emit()

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
	if _images != null and _by_id.get(id,{}).get("type") == "image":
		if retry:
			_images.retry(id)
		else:
			_images.ensure(id)

func get_message_image(id: String) -> Dictionary:
	return _images.get_state(id) if _images != null else {"status":"idle","texture":null,"original_size":Vector2i.ZERO,"code":""}

func preview_message_image(id: String) -> Texture2D:
	return _images.preview(id) if _images != null and _by_id.get(id,{}).get("type") == "image" else null

func _model_types() -> Array:
	return _models.enabled_types() if _models != null else []
