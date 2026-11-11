extends Resource
## 预留双向世界边界：payload 不定义世界格式。
signal interaction_received(event: Dictionary)
signal completed(request_id: String, result: Dictionary)
func get_capabilities() -> Dictionary:
	return {"available":false,"state":false,"action":false,"events":false}
func start(_context: Dictionary) -> Error:
	return ERR_UNAVAILABLE
func apply_state(_state: Dictionary) -> Dictionary:
	return {"ok":false,"code":"NOT_IMPLEMENTED"}
func request_action(_request_id: String, _action: Dictionary) -> Dictionary:
	return {"ok":false,"code":"NOT_IMPLEMENTED"}
func cancel(_request_id: String) -> void:
	pass
func stop() -> void:
	pass
