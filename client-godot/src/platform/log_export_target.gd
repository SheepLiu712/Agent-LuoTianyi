extends RefCounted
## 用户选择的目标路径，界面与控制器不得自行解释路径含义。
var _path: String


func _init(path: String) -> void:
	_path = path


func export_log(logger: RefCounted, run_id: String) -> Error:
	return logger.export_run(run_id, _path)
