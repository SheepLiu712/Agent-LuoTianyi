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
		var start: Variant = response.data.get("start_index")
		var rows: Array = response.data.get("history",[])
		if not _valid_page_bounds(start, rows.size()):
			_fail("HISTORY_INVALID")
			return
		var messages := _page_messages(rows)
		if messages.size() != rows.size():
			_fail("HISTORY_INVALID")
			return
		var unique := _deduplicate(messages)
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

func _valid_page_bounds(start: Variant, row_count: int) -> bool:
	if not _valid_page_start(start, row_count):
		return false
	if (_end >= 0 and (start >= _end or _end-int(start) != row_count)) or (_end == -1 and start > 0 and row_count != 50):
		return false
	return true

func _valid_page_start(start: Variant, row_count: int) -> bool:
	if not (start is int or start is float) or not is_finite(float(start)) or start < 0 or start != floor(start) or row_count > 50:
		return false
	return true

func _page_messages(rows: Array) -> Array[Dictionary]:
	var messages: Array[Dictionary] = []
	for row in rows:
		if not _valid_history_row(row):
			return []
		messages.append({"id":row.uuid,"role":"assistant" if row.source == "agent" else row.source,"text":"[图片]" if row.type == "image" else row.content,"type":row.type,"timestamp":row.timestamp,"history":true,"status":"received","code":""})
	return messages

func _valid_history_row(row: Variant) -> bool:
	if not row is Dictionary or not row.get("uuid") is String or row.uuid.is_empty():
		return false
	if not row.get("source") in ["agent","user","system"] or not row.get("type") in ["text","image","sing","cmd"]:
		return false
	return _valid_history_content(row)

func _valid_history_content(row: Dictionary) -> bool:
	if row.type != "image" and not row.get("content") is String:
		return false
	return row.get("timestamp") is int or row.get("timestamp") is float or row.get("timestamp") is String

func _deduplicate(messages: Array[Dictionary]) -> Array[Dictionary]:
	var unique: Array[Dictionary] = []
	for message in messages:
		if _seen.has(message.id):
			_state.incomplete = true
		else:
			_seen[message.id] = true
			unique.append(message)
	return unique
