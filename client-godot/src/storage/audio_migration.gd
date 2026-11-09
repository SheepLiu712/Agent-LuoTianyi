extends "res://src/storage/audio_migration_port.gd"
## 语音兜底迁移：把本机 Python 客户端留下的 wav 转成当前账号的播放缓存。
## 两条入口共用同一条写入队列与同一套去重规则，所以永远不会互相覆盖：
##   request_all() —— 一键迁移，扫全部候选目录，按文件全量结转；
##   request_ids() —— 增量迁移，只处理刚进入视野的那一页消息。
## 一键迁移成功后写标记；此后增量不再扫盘（清理掉了缓存会让标记自动失效）。
## 失败只影响本批文件，不抛错、不阻塞会话，下一批或下次翻页会自然重试。

const Import = preload("res://src/storage/audio_import.gd")

## 进度上报节流：批量迁移时避免每个文件都刷一次界面。
const REPORT_MS := 150
## 候选目录缓存时长：翻页时不必每页都重新扫盘。
const SOURCE_TTL_MS := 30000

var _directory := Callable()
var _sources_provider := Callable()
var _jobs: Array = []
var _results: Array = []
var _mutex := Mutex.new()
var _semaphore := Semaphore.new()
var _thread: Thread
var _running := false
var _mode := "idle"
var _code := ""
var _total := 0
var _done := 0
var _imported := 0
var _skipped := 0
var _failed := 0
var _seen: Dictionary = {}
var _sources: Array[String] = []
var _sources_at := 0
var _bulk_done := false
var _marker_checked := false
var _last_report := 0
var _last_done := 0


## 目录由装配层给：只有它知道当前账号的缓存落在哪里。
## `sources` 可选，用于测试或将来支持「用户自选 Python 目录」。
func bind(directory: Callable, sources: Callable = Callable()) -> void:
	_directory = directory
	_sources_provider = sources


func request_all() -> void:
	if is_busy():
		return
	var directory := _cache_directory()
	if directory.is_empty():
		_finish("unavailable", "STORAGE_UNAVAILABLE")
		return
	_marker_checked = true
	_seen.clear()
	_reset_run("bulk")
	if not _ensure_worker():
		_finish("unavailable", "STORAGE_UNAVAILABLE")
		return
	var sources := _candidate_sources()
	_sources = sources
	_sources_at = Time.get_ticks_msec()
	if sources.is_empty():
		_finish("done", "SOURCE_NOT_FOUND")
		return
	var queued := 0
	for source in sources:
		var entries := Import.index(source)
		for id in entries:
			if _seen.has(id):
				continue
			_seen[id] = true
			_enqueue({"id": str(id), "source": str(entries[id]), "cache": directory})
			queued += 1
	if queued == 0:
		_finish("done", "SOURCE_EMPTY")
		return
	_total = queued
	_report()


## 只处理调用方给出的 id；没有源文件或已经处理过的直接跳过，不算失败。
func request_ids(ids: Array) -> void:
	var directory := _cache_directory()
	if directory.is_empty() or ids.is_empty():
		return
	if not _marker_allows_incremental(directory):
		return
	var sources := _fresh_sources()
	if sources.is_empty():
		return
	var queued := _enqueue_unseen(ids, sources, directory)
	if queued == 0:
		return
	_total += queued
	_mode = "incremental"
	_report()


## 首次调用才读标记：标记在但缓存被清空过，说明结转结果已不在，退回增量模式。
## 返回 false 表示整体结转已经覆盖，本批不必再处理。
func _marker_allows_incremental(directory: String) -> bool:
	if not _marker_checked:
		_marker_checked = true
		_bulk_done = not Import.read_marker(directory).is_empty() and Import.cached_count(directory) > 0
	return not _bulk_done and _mode != "bulk"


## 只收本机确实找得到源文件、且没处理过的 id。
func _enqueue_unseen(ids: Array, sources: Array[String], directory: String) -> int:
	var queued := 0
	for value in ids:
		var id := str(value)
		if not _is_wanted(id):
			continue
		_seen[id] = true
		var source := Import.find(sources, id)
		if source.is_empty():
			continue
		_enqueue({"id": id, "source": source, "cache": directory})
		queued += 1
	return queued


func _is_wanted(id: String) -> bool:
	return not id.is_empty() and not _seen.has(id) and Import.is_uuid(id)


func stop() -> void:
	var was_running := _running
	if was_running:
		_mutex.lock()
		_jobs.clear()
		_mutex.unlock()
		_semaphore.post()
		if _thread != null:
			_thread.wait_to_finish()
			_thread = null
		_running = false
		_mutex.lock()
		_jobs.clear()
		_results.clear()
		_mutex.unlock()
	# 作用域可能已经换了账号：去重表与标记都作废，下一次重新判断。
	_seen.clear()
	_bulk_done = false
	_marker_checked = false
	_sources.clear()
	_sources_at = 0
	_reset_run("idle")
	if was_running:
		_report()


func is_busy() -> bool:
	return _mode in ["bulk", "incremental"] and _done < _total


func get_state() -> Dictionary:
	return {
		"mode": _mode, "busy": is_busy(), "total": _total, "done": _done,
		"imported": _imported, "skipped": _skipped, "failed": _failed,
		"code": _code, "sources": _sources.size(),
	}


func _process(_delta: float) -> void:
	if not _running:
		return
	_drain()
	if _mode == "bulk" and _total > 0 and _done >= _total and _jobs.is_empty():
		_complete_bulk()
	_report_if_moved()


func _exit_tree() -> void:
	stop()


func _ensure_worker() -> bool:
	if _running:
		return true
	_thread = Thread.new()
	if _thread.start(_run) != OK:
		_thread = null
		return false
	_running = true
	return true


func _enqueue(job: Dictionary) -> void:
	if not _ensure_worker():
		return
	_mutex.lock()
	_jobs.append(job)
	_mutex.unlock()
	_semaphore.post()


func _run() -> void:
	while true:
		_semaphore.wait()
		var job: Variant = _take()
		if job == null or str(job.get("id", "")).is_empty():
			break
		var result: Dictionary = Import.import_file(str(job.cache), str(job.id), str(job.source))
		result["id"] = str(job.id)
		_mutex.lock()
		_results.append(result)
		_mutex.unlock()


func _take() -> Variant:
	_mutex.lock()
	var job: Variant = null if _jobs.is_empty() else _jobs.pop_front()
	_mutex.unlock()
	return job


func _drain() -> void:
	_mutex.lock()
	var entries := _results.duplicate()
	_results.clear()
	_mutex.unlock()
	if entries.is_empty():
		return
	var landed: Array = []
	for entry in entries:
		_done += 1
		match str(entry.get("status", "failed")):
			"imported":
				_imported += 1
				landed.append(str(entry.get("id", "")))
			"skipped":
				_skipped += 1
			_:
				_failed += 1
	if not landed.is_empty():
		imported.emit(landed)


func _complete_bulk() -> void:
	_mode = "done"
	_code = "" if _failed == 0 else "PARTIAL"
	# 有失败就不写标记：这些条目留给翻页时的增量再试一次。
	_bulk_done = _failed == 0
	if _bulk_done:
		Import.write_marker(_cache_directory(), {
			"total": _total, "imported": _imported, "skipped": _skipped, "failed": _failed,
		})
	_report()


func _reset_run(mode: String) -> void:
	_mode = mode
	_code = ""
	_total = 0
	_done = 0
	_imported = 0
	_skipped = 0
	_failed = 0
	_last_done = 0


func _finish(mode: String, code: String) -> void:
	_reset_run(mode)
	_code = code
	_report()


func _cache_directory() -> String:
	if not _directory.is_valid():
		return ""
	return str(_directory.call())


func _fresh_sources() -> Array[String]:
	var now := Time.get_ticks_msec()
	if not _sources.is_empty() and now - _sources_at < SOURCE_TTL_MS:
		return _sources
	_sources = _candidate_sources()
	_sources_at = now
	return _sources


## 候选目录默认来自磁盘布局；注入来源后以注入为准（测试与手动指定目录）。
func _candidate_sources() -> Array[String]:
	var result: Array[String] = []
	if _sources_provider.is_valid():
		for value in _sources_provider.call():
			result.append(str(value))
		return result
	return Import.candidates()


func _report() -> void:
	_last_report = Time.get_ticks_msec()
	_last_done = _done
	progress.emit(get_state())


func _report_if_moved() -> void:
	if _done == _last_done:
		return
	if _done < _total and Time.get_ticks_msec() - _last_report < REPORT_MS:
		return
	_report()
