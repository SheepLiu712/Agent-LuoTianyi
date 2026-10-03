extends Resource
func arguments() -> PackedStringArray:
	return PackedStringArray()
func is_headless() -> bool:
	return true
func register_logger(_logger: Logger) -> void:
	pass
func unregister_logger(_logger: Logger) -> void:
	pass
func capture(_viewport: Viewport, _path: String) -> Error:
	return ERR_UNAVAILABLE
func process_id() -> int:
	return 0
func process_running(_id: int) -> bool:
	return true
func os_name() -> String:
	return "unavailable"
