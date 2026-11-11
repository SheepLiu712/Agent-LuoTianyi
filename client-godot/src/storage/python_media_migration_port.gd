extends Node
## Python 媒体导入端口：界面只依赖这里的选择、扫描与进度语义，
## 不接触文件系统，也不知道缓存文件名与线程细节。

signal progress(state: Dictionary)
signal imported(kind: String, ids: Array)


func set_settings(_store: Resource) -> void:
	pass


func set_scope_provider(_provider: Callable) -> void:
	pass


func bind(_audio_directory: Callable, _images_directory: Callable) -> void:
	pass


func set_target(_path: String) -> Dictionary:
	return {"ok":false, "code":"UNAVAILABLE"}


func scan() -> Dictionary:
	return {"ok":false, "code":"UNAVAILABLE"}


func get_state() -> Dictionary:
	return {
		"mode":"unavailable", "busy":false, "total":0, "done":0,
		"imported":0, "skipped":0, "failed":0, "code":"UNAVAILABLE",
		"audio_total":0, "audio_done":0, "image_total":0, "image_done":0,
		"target":"", "mismatch":false,
	}


func request_import() -> void:
	pass


func request_ids(_ids: Array) -> void:
	pass


func get_target_path() -> String:
	return ""


func get_audio_directory() -> String:
	return ""


func get_images_directory() -> String:
	return ""


func is_busy() -> bool:
	return false


func stop() -> void:
	pass
