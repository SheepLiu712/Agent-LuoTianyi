extends RefCounted
## A user-selected destination, never a path interpreted by a UI/controller.
var _path: String
func _init(path: String) -> void:
	_path = path
func export_log(logger: RefCounted, run_id: String) -> Error:
	return logger.export_run(run_id, _path)
