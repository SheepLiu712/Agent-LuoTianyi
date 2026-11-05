extends "res://src/platform/runtime_environment.gd"
func arguments() -> PackedStringArray:
	return OS.get_cmdline_user_args()
func is_headless() -> bool:
	return DisplayServer.get_name() == "headless"
func register_logger(logger: Logger) -> void:
	OS.add_logger(logger)
func unregister_logger(logger: Logger) -> void:
	OS.remove_logger(logger)
func capture(viewport: Viewport, path: String) -> Error:
	return viewport.get_texture().get_image().save_png(path)
func process_id() -> int:
	return OS.get_process_id()
func process_running(id: int) -> bool:
	return OS.is_process_running(id)
func os_name() -> String:
	return OS.get_name()
