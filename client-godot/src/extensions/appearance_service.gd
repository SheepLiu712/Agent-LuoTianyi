extends Resource
## Reserved appearance capability, not an AI policy or a renderer.
signal completed(request_id: String, result: Dictionary)
signal state_changed(state: Dictionary)
func get_capabilities() -> Dictionary:
	return {"available":false,"change":false}
func start(_context: Dictionary) -> Error:
	return ERR_UNAVAILABLE
func get_state() -> Dictionary:
	return {}
func request_change(_request_id: String, _character_id: String, _resource_id: String, _origin: String) -> Dictionary:
	return {"ok":false,"code":"NOT_IMPLEMENTED"}
func cancel(_request_id: String) -> void:
	pass
func stop() -> void:
	pass
