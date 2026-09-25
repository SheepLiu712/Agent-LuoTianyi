extends Node
signal page_received(messages: Array[Dictionary])
signal boundary_ready
signal state_changed(state: Dictionary)
var _api: Node
var _logger: RefCounted
var _session: Dictionary = {}
var _generation := 0
var _end := -1
var _seen: Dictionary = {}
var _state: Dictionary
func _init(api: Node, logger: RefCounted = null) -> void:
	_api = api
	_logger = logger
	add_child(api)
	_state = _empty()
func start(session: Dictionary) -> void:
	stop()
	_session = session.duplicate(true)
	_state.phase = "first_loading"
	_notify()
	_load.call_deferred(_generation)
func stop() -> void:
	_generation += 1
	_api.cancel()
	_session.clear()
	_seen.clear()
	_end = -1
	_state = _empty()
	_notify()
func get_state() -> Dictionary:
	return _state.duplicate(true)
func retry() -> void:
	if _state.phase not in ["first_failed","failed"]:
		return
	_state.phase = "first_loading" if _end == -1 else "loading"
	_state.code = ""
	_notify()
	_load.call_deferred(_generation)
func skip() -> void:
	if _state.phase != "first_failed":
		return
	_generation += 1
	_state.phase = "skipped"
	_state.code = ""
	_notify()
	boundary_ready.emit()
func _load(generation: int) -> void:
	while generation == _generation and _state.phase in ["first_loading","loading"]:
		var response: Dictionary = await _api.fetch_page(_session,_end)
		if generation != _generation:
			return
		if not response.ok:
			_fail(response.code)
			return
		var data: Dictionary = response.data
		var start: Variant = data.get("start_index")
		var rows: Array = data.get("history",[])
		if not (start is int or start is float) or not is_finite(float(start)) or start < 0 or start != floor(start) or rows.size() > 50:
			_fail("HISTORY_INVALID")
			return
		if (_end >= 0 and (start >= _end or _end-int(start) != rows.size())) or (_end == -1 and start > 0 and rows.size() != 50):
			_fail("HISTORY_INVALID")
			return
		var messages: Array[Dictionary] = []
		for row in rows:
			if not row is Dictionary or not row.get("uuid") is String or row.uuid.is_empty() or not row.get("source") in ["agent","user","system"] or not row.get("type") in ["text","image","sing","cmd"] or (row.type != "image" and not row.get("content") is String) or not (row.get("timestamp") is int or row.get("timestamp") is float or row.get("timestamp") is String):
				_fail("HISTORY_INVALID")
				return
			messages.append({"id":row.uuid,"role":"assistant" if row.source == "agent" else row.source,"text":"[图片]" if row.type == "image" else row.content,"type":row.type,"timestamp":row.timestamp,"history":true,"status":"received","code":""})
		var unique: Array[Dictionary] = []
		for message in messages:
			if _seen.has(message.id):
				_state.incomplete = true
			else:
				_seen[message.id] = true
				unique.append(message)
		var first := _end == -1
		_end = int(start)
		_state.start_index = _end
		_state.count = _seen.size()
		_state.phase = "complete" if _end == 0 else "loading"
		_state.code = "HISTORY_DUPLICATE" if _state.incomplete else ""
		page_received.emit(unique)
		_notify()
		if first:
			boundary_ready.emit()
		# Yield between pages so network/audio/UI all continue making progress.
		await get_tree().process_frame
func _fail(code: String) -> void:
	_state.phase = "first_failed" if _end == -1 else "failed"
	_state.code = code
	_notify()
func _notify() -> void:
	if _logger != null:
		_logger.record("history_state",{"phase":_state.phase,"code":_state.code,"count":_state.count,"index":_end})
	state_changed.emit(get_state())
func _empty() -> Dictionary:
	return {"phase":"idle","code":"","count":0,"start_index":-1,"incomplete":false}
func _exit_tree() -> void:
	stop()
