extends Node
## 语音迁移端口：界面与装配层只依赖这个抽象，不接触文件系统。
## 具体实现（文件扫描、线程、原子写入）在 `audio_migration.gd`；
## 界面因此拿不到路径，也无法绕过一致性约定直接写缓存。

## 进度上报。字段：mode / busy / total / done / imported / skipped / failed / code。
signal progress(state: Dictionary)
## 一批条目已落盘，参数是本批的消息 id，供会话层刷新气泡。
signal imported(ids: Array)


func request_all() -> void:
	pass


func request_ids(_ids: Array) -> void:
	pass


func stop() -> void:
	pass


func is_busy() -> bool:
	return false


func get_state() -> Dictionary:
	return {
		"mode": "unavailable", "busy": false, "total": 0, "done": 0,
		"imported": 0, "skipped": 0, "failed": 0, "code": "STORAGE_UNAVAILABLE",
	}
