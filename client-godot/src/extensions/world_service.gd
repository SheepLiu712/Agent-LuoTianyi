extends Resource
## Reserved bidirectional world boundary; payloads do not define a world format.
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
