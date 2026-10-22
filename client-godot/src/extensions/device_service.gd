extends Resource
## Reserved device boundary; no protocol, permissions or connection is implemented.
signal state_changed(state: Dictionary)
signal event_received(event: Dictionary)
signal completed(request_id: String, result: Dictionary)
func get_capabilities() -> Dictionary:
	return {"available":false,"control":false,"events":false}
func start(_context: Dictionary) -> Error:
	return ERR_UNAVAILABLE
func request_control(_request_id: String, _device_id: String, _intent: Dictionary) -> Dictionary:
	return {"ok":false,"code":"NOT_IMPLEMENTED"}
func cancel(_request_id: String) -> void:
	pass
func stop() -> void:
	pass
