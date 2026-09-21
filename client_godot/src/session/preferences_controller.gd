extends Node
const ServerAddress = preload("res://src/domain/server_address.gd")
signal changed(state: Dictionary)
const FIELDS := ["relationship","speaking_style","personality_text","custom_context"]
var _http: Node
var _logger: RefCounted
var _session: Dictionary = {}
var _generation := 0
var _baseline: Dictionary = {}
var _state := {"phase":"idle","fields":{},"dirty":false,"can_save":false,"code":""}
func _init(http: Node,logger: RefCounted = null) -> void:
	_http = http
	_logger = logger
	add_child(http)
func start(session: Dictionary) -> void:
	stop()
	_session = session.duplicate(true)
	_session.server = ServerAddress.normalize(str(session.get("server","")))
	await reload()
func reload() -> void:
	if _state.dirty or _state.phase in ["loading","saving"] or _session.is_empty():
		return
	var generation := _generation
	_state.phase = "loading"
	_notify()
	var response: Dictionary = await _fetch_preferences()
	if generation != _generation:
		return
	if not response.ok:
		_state.phase = "error"
		_state.code = response.code
	else:
		_baseline = _fields(response.data.preferences)
		_state.fields = _baseline.duplicate(true)
		_state.phase = "ready"
		_state.code = "OK"
	_notify()
func edit(fields: Dictionary) -> void:
	if _state.phase != "ready":
		return
	for key in FIELDS:
		if fields.get(key) is String:
			_state.fields[key] = fields[key]
	_state.dirty = _state.fields != _baseline
	_notify()
func save() -> void:
	if not _state.can_save:
		return
	var generation := _generation
	var draft: Dictionary = _state.fields.duplicate(true)
	_state.phase = "saving"
	_notify()
	var response: Dictionary = await _fetch_preferences()
	if generation != _generation:
		return
	if response.ok:
		var merged: Dictionary = response.data.preferences.duplicate(true)
		for key in FIELDS:
			if draft[key] == _baseline[key]:
				continue
			var value: String = draft[key].strip_edges()
			if key == "personality_text":
				var traits: Array[String] = []
				for part in value.replace("，",",").replace("、",",").replace("\n",",").replace("\r",",").split(","):
					if not part.strip_edges().is_empty():
						traits.append(part.strip_edges())
				merged.personality_traits = traits
				merged["#sym:personality_text"] = "，".join(traits)
			else:
				merged[key] = "" if (key == "relationship" and value == "朋友") or (key == "speaking_style" and value == "活泼可爱") else value
		var body := _auth()
		body.preferences = merged
		response = await _http.send(_session.server+"/preference/overwrite",HTTPClient.METHOD_POST,body)
		if generation != _generation:
			return
		if response.ok and response.data.get("status") == "success":
			_baseline = _fields(merged)
			_state.fields = _baseline.duplicate(true)
			_state.dirty = false
		elif response.ok:
			response = {"ok":false,"code":"INVALID_RESPONSE"}
	_state.phase = "ready"
	_state.code = response.code
	_notify()
func get_state() -> Dictionary:
	return _state.duplicate(true)
func stop() -> void:
	_generation += 1
	_http.cancel()
	_session = {}
	_baseline = {}
	_state = {"phase":"idle","fields":{},"dirty":false,"can_save":false,"code":""}
	_notify()
func _fetch_preferences() -> Dictionary:
	var result: Dictionary = await _http.send(_session.server+"/preference/get",HTTPClient.METHOD_POST,_auth())
	if result.ok and not result.data.get("preferences") is Dictionary:
		return {"ok":false,"code":"INVALID_RESPONSE"}
	return result
func _auth() -> Dictionary:
	return {"username":_session.get("username",""),"token":_session.get("message_token","")}
func _fields(preferences: Dictionary) -> Dictionary:
	var result := {"relationship":"朋友","speaking_style":"活泼可爱","personality_text":"","custom_context":""}
	for key in ["relationship","speaking_style","custom_context"]:
		if preferences.get(key) is String and not preferences[key].is_empty():
			result[key] = preferences[key]
	if preferences.get("personality_traits") is Array:
		var traits: Array[String] = []
		for item in preferences.personality_traits:
			if item is String:
				traits.append(item)
		result.personality_text = "，".join(traits)
	elif preferences.get("#sym:personality_text") is String:
		result.personality_text = preferences["#sym:personality_text"]
	return result
func _notify() -> void:
	_state.can_save = _state.phase == "ready" and _state.dirty
	if _logger != null:
		_logger.record("settings_preference",{"phase":_state.phase,"code":_state.code})
	changed.emit(get_state())
func _exit_tree() -> void:
	stop()
