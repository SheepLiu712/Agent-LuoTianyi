extends Node
signal changed(state: Dictionary)
const Api = preload("res://src/network/account_api.gd")
var _http: Node
var _store: RefCounted
var _logger: RefCounted
var _types: Dictionary = {}
var _configs: Dictionary = {}
var _state := {"phase":"idle","code":"","count":0}
var _generation := 0
var _scope: Dictionary = {}
func _init(http: Node,store: RefCounted,logger: RefCounted = null) -> void:
	_http = http
	_store = store
	_logger = logger
	add_child(http)
func start(session: Dictionary) -> void:
	stop()
	_scope = session.duplicate(true)
	var generation := _generation
	var base := Api.normalize_server(str(session.get("server","")))
	_store.set_scope(base,session.get("username",""))
	_state.phase = "loading"
	_notify()
	var result: Dictionary = await _http.send(base+"/llm/client-model-types",HTTPClient.METHOD_GET)
	if generation != _generation:
		return
	if not result.ok or not result.data.get("types") is Array:
		_state = {"phase":"error","code":result.code if not result.ok else "INVALID_RESPONSE","count":0}
		_notify()
		return
	var types := {}
	for item in result.data.types:
		if not item is Dictionary or not item.get("id") is String or item.id.is_empty() or not item.get("name") is String or item.name.is_empty() or not item.get("model_kind") in ["llm","vlm"] or not item.get("requires_json") is bool or not item.get("requires_thinking") is bool or types.has(item.id):
			_state = {"phase":"error","code":"INVALID_RESPONSE","count":0}
			_notify()
			return
		types[item.id] = item.duplicate(true)
		if not item.get("description") is String:
			_state = {"phase":"error","code":"INVALID_RESPONSE","count":0}
			_notify()
			return
	_types = types
	var code := "OK"
	for id in _types:
		_configs[id] = _default(_types[id])
		var stored: Dictionary = _store.read(id)
		if not stored.config.is_empty():
			_configs[id].merge(stored.config,true)
		if not validate(id,_configs[id]).ok:
			var disabled: Dictionary = _configs[id].duplicate(true)
			disabled.enabled = false
			disabled.model_kind = _types[id].model_kind
			_configs[id] = disabled if validate(id,disabled).ok else _default(_types[id])
			code = "INVALID_CONFIG"
		if not stored.ok and stored.code != "NOT_FOUND":
			code = stored.code
	_state = {"phase":"ready","code":code,"count":_types.size()}
	_notify()
func reload() -> void:
	if not _scope.is_empty(): await start(_scope.duplicate(true))
func get_types() -> Array[Dictionary]:
	var result: Array[Dictionary] = []
	for type in _types.values():
		result.append(type.duplicate(true))
	return result
func get_config(type_id: String) -> Dictionary:
	return _configs.get(type_id,{}).duplicate(true)
func get_state() -> Dictionary:
	return _state.duplicate()
func validate(type_id: String,config: Dictionary) -> Dictionary:
	if not _types.has(type_id):
		return {"ok":false,"code":"UNKNOWN_MODEL_TYPE"}
	if not config.get("enabled") is bool or not config.get("params") is Dictionary or not config.get("model_capabilities") is Dictionary:
		return {"ok":false,"code":"INVALID_CONFIG"}
	for field in ["provider","base_url","api_key","model","model_kind"]:
		if not config.get(field) is String:
			return {"ok":false,"code":"INVALID_CONFIG"}
	for flag in ["can_use_json","can_enable_thinking"]:
		if not config.model_capabilities.get(flag) is bool:
			return {"ok":false,"code":"INVALID_CONFIG"}
	if config.model_kind != _types[type_id].model_kind:
		return {"ok":false,"code":"MODEL_KIND_MISMATCH"}
	if (config.params.has("stream") and (not config.params.stream is bool or config.params.stream != false)) or config.params.has("stream_options"):
		return {"ok":false,"code":"STREAMING_NOT_SUPPORTED"}
	if config.enabled:
		if config.provider.strip_edges().is_empty() or Api.normalize_server(config.base_url).is_empty() or config.api_key.strip_edges().is_empty() or config.model.strip_edges().is_empty():
			return {"ok":false,"code":"MODEL_FIELDS_REQUIRED"}
		if (_types[type_id].requires_json and not config.model_capabilities.can_use_json) or (_types[type_id].requires_thinking and not config.model_capabilities.can_enable_thinking):
			return {"ok":false,"code":"MODEL_CAPABILITY_MISMATCH"}
	return {"ok":true,"code":"OK"}
func save(type_id: String,config: Dictionary,allow_plain: bool = false) -> Dictionary:
	var valid := validate(type_id,config)
	if not valid.ok:
		return valid
	var result: Dictionary = _store.save(type_id,config,allow_plain)
	if result.ok:
		_configs[type_id] = config.duplicate(true)
	_state.code = result.code
	_notify()
	return result
func enabled_types() -> Array[String]:
	var result: Array[String] = []
	for id in _types:
		if _configs[id].enabled and validate(id,_configs[id]).ok:
			result.append(id)
	return result
func copy_config(source: Dictionary,target_id: String) -> Dictionary:
	if not _types.has(target_id):
		return {}
	var result := source.duplicate(true)
	result.model_kind = _types[target_id].model_kind
	return result
func stop() -> void:
	_scope.clear()
	_generation += 1
	_http.cancel()
	_store.set_scope("","")
	_types.clear()
	_configs.clear()
	_state = {"phase":"idle","code":"","count":0}
	_notify()
func _default(type: Dictionary) -> Dictionary:
	return {"enabled":false,"provider":"OpenAI 兼容","base_url":"","api_key":"","model":"","model_kind":type.model_kind,"model_capabilities":{"can_use_json":false,"can_enable_thinking":false},"params":{}}
func _notify() -> void:
	if _logger != null:
		_logger.record("settings_models",{"phase":_state.phase,"code":_state.code,"count":_state.count})
	changed.emit(get_state())
func _exit_tree() -> void:
	stop()
