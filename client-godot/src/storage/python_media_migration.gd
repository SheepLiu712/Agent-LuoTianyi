extends "res://src/storage/python_media_migration_port.gd"
## Python 媒体导入：用户选定 exe/目录后，只读扫描并把 UUID 对齐的
## 语音与历史图片复制进当前账号缓存。文本历史仍由服务端提供。

const Locator = preload("res://src/storage/python_client_locator.gd")
const AudioImport = preload("res://src/storage/audio_import.gd")
const ImageImport = preload("res://src/storage/image_import.gd")
const Schema = preload("res://src/storage/log_schema.gd")
const Events = preload("res://src/storage/log_events.gd")
const ServerAddress = preload("res://src/domain/server_address.gd")

const SETTINGS_SECTION := "migration"
const SETTINGS_KEY := "python_client_path"
const REPORT_MS := 150

var _audio_directory := Callable()
var _images_directory := Callable()
var _scope := Callable()
var _settings: Resource
var _logger: RefCounted

var _target_path := ""
var _loaded := false
var _dirs_checked := false
var _scan_result: Dictionary = {}
var _audio_dir := ""
var _images_dir := ""
var _source_hash := ""
var _mismatch := false

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
var _audio_total := 0
var _audio_done := 0
var _image_total := 0
var _image_done := 0
var _seen: Dictionary = {}
var _bulk_done := false
var _marker_checked := false
var _last_report := 0
var _last_done := 0


func set_settings(store: Resource) -> void:
	_settings = store


func set_scope_provider(provider: Callable) -> void:
	_scope = provider


## 目录来自装配层：音频缓存与图片缓存都按账号作用域分桶。
func bind(audio_directory: Callable, images_directory: Callable) -> void:
	_audio_directory = audio_directory
	_images_directory = images_directory


func set_logger(logger: RefCounted) -> void:
	_logger = logger


func set_target(path: String) -> Dictionary:
	_target_path = path.strip_edges()
	_loaded = true
	_scan_result = Locator.inspect(_target_path)
	if _scan_result.get("ok", false):
		_apply_scan(_scan_result)
		_save_path(_target_path)
	else:
		_audio_dir = ""
		_images_dir = ""
		_source_hash = ""
		_log_scan("failure")
	return _scan_result


func scan() -> Dictionary:
	_ensure_loaded()
	if _target_path.is_empty():
		_scan_result = {"ok":false, "code":"TARGET_MISSING"}
		return _scan_result
	_scan_result = Locator.inspect(_target_path)
	if _scan_result.get("ok", false):
		_apply_scan(_scan_result)
	else:
		_audio_dir = ""
		_images_dir = ""
		_source_hash = ""
	_log_scan("success" if _scan_result.get("ok", false) else "failure")
	return _scan_result


func get_target_path() -> String:
	_ensure_loaded()
	return _target_path


func get_audio_directory() -> String:
	_ensure_dirs()
	return _audio_dir if not _audio_dir.is_empty() and DirAccess.dir_exists_absolute(_audio_dir) else ""


func get_images_directory() -> String:
	_ensure_dirs()
	return _images_dir if not _images_dir.is_empty() and DirAccess.dir_exists_absolute(_images_dir) else ""


func request_import() -> void:
	if is_busy():
		return
	_ensure_dirs()
	if not _scan_result.get("ok", false):
		_finish("unavailable", str(_scan_result.get("code", "TARGET_MISSING")))
		return
	if _cache_audio().is_empty() and _cache_images().is_empty():
		_finish("unavailable", "STORAGE_UNAVAILABLE")
		return
	_reset_run("bulk")
	_seen.clear()
	_marker_checked = true
	_queue_audio()
	_queue_images()
	if _total == 0:
		_finish("done", "SOURCE_EMPTY")
		return
	_start_worker()
	_report()


## 只处理刚进入视野的语音 id；图片在 history_images 中按需兜底。
func request_ids(ids: Array) -> void:
	if ids.is_empty() or is_busy():
		return
	_ensure_dirs()
	if not _scan_result.get("ok", false) or _audio_dir.is_empty():
		return
	if not _marker_allows_incremental(_cache_audio()):
		return
	var queued := _queue_requested(ids)
	if queued == 0:
		return
	_audio_total += queued
	_mode = "incremental"
	_start_worker()
	_report()


func get_state() -> Dictionary:
	return {
		"mode":_mode, "busy":is_busy(), "total":_total, "done":_done,
		"imported":_imported, "skipped":_skipped, "failed":_failed,
		"code":_code, "audio_total":_audio_total, "audio_done":_audio_done,
		"image_total":_image_total, "image_done":_image_done,
		"target":_target_path, "mismatch":_mismatch, "scan":_scan_result,
	}


func is_busy() -> bool:
	return _mode in ["bulk", "incremental"] and _done < _total


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
	_seen.clear()
	_bulk_done = false
	_marker_checked = false
	_reset_run("idle")
	if was_running:
		_report()


func _process(_delta: float) -> void:
	if not _running:
		return
	_drain()
	if _mode == "bulk" and _total > 0 and _done >= _total and _jobs.is_empty():
		_complete_bulk()
	_report_if_moved()


func _exit_tree() -> void:
	stop()


func _ensure_loaded() -> void:
	if _loaded:
		return
	_loaded = true
	if _settings != null:
		var stored: Variant = _settings.get_value(SETTINGS_SECTION, SETTINGS_KEY, "")
		if stored is String:
			_target_path = str(stored).strip_edges()


func _ensure_dirs() -> void:
	_ensure_loaded()
	if _dirs_checked:
		return
	_dirs_checked = true
	if _target_path.is_empty():
		return
	var result := Locator.inspect(_target_path)
	if result.get("ok", false):
		_scan_result = result
		_apply_scan(result)
	else:
		_scan_result = result
		_audio_dir = ""
		_images_dir = ""


func _apply_scan(result: Dictionary) -> void:
	var next_hash := str(result.get("root", "")).to_lower().sha256_text()
	if next_hash != _source_hash:
		_seen.clear()
		_bulk_done = false
		_marker_checked = false
	_audio_dir = str(result.get("audio_dir", ""))
	_images_dir = str(result.get("images_dir", ""))
	_source_hash = next_hash
	_mismatch = _accounts_differ(result.get("account", {}))


func _accounts_differ(account: Variant) -> bool:
	if not account is Dictionary or not account.get("available", false):
		return false
	if not _scope.is_valid():
		return false
	var current: Variant = _scope.call()
	if not current is Dictionary:
		return false
	var python_user := str(account.get("username", ""))
	var python_server := ServerAddress.normalize(str(account.get("server_url", "")))
	var current_user := str(current.get("username", ""))
	var current_server := ServerAddress.normalize(str(current.get("server", "")))
	if not python_user.is_empty() and python_user != current_user:
		return true
	return not python_server.is_empty() and python_server != current_server


func _queue_audio() -> void:
	var cache := _cache_audio()
	if cache.is_empty() or _audio_dir.is_empty():
		return
	var entries := Locator.audio_index(_audio_dir)
	_audio_total = entries.size()
	for id in entries:
		_seen["audio:" + str(id)] = true
		_enqueue("audio", str(id), str(entries[id]), cache)


func _queue_images() -> void:
	var cache := _cache_images()
	if cache.is_empty() or _images_dir.is_empty():
		return
	var entries := Locator.image_index(_images_dir)
	_image_total = entries.size()
	for id in entries:
		_seen["image:" + str(id)] = true
		_enqueue("image", str(id), str(entries[id]), cache)


func _queue_requested(ids: Array) -> int:
	var cache := _cache_audio()
	var queued := 0
	for value in ids:
		var id := str(value)
		if id.is_empty() or _seen.has("audio:" + id) or not Locator.is_uuid(id):
			continue
		var source := Locator.find_audio(_audio_dir, id)
		if source.is_empty():
			continue
		_seen["audio:" + id] = true
		_enqueue("audio", id, source, cache)
		queued += 1
	return queued


func _start_worker() -> void:
	if _running:
		return
	_thread = Thread.new()
	if _thread.start(_run) != OK:
		_thread = null
		_mutex.lock()
		_jobs.clear()
		_mutex.unlock()
		_finish("unavailable", "STORAGE_UNAVAILABLE")
		return
	_running = true


func _enqueue(kind: String, id: String, source: String, cache: String) -> void:
	if cache.is_empty():
		return
	_mutex.lock()
	_jobs.append({"kind":kind, "id":id, "source":source, "cache":cache})
	_mutex.unlock()
	_semaphore.post()
	_total += 1


func _run() -> void:
	while true:
		_semaphore.wait()
		var job: Variant = _take()
		if job == null or str(job.get("id", "")).is_empty():
			break
		var started := Time.get_ticks_usec()
		var result := _import(job)
		result["kind"] = str(job.get("kind", "audio"))
		result["id"] = str(job.get("id", ""))
		result["duration_ms"] = int((Time.get_ticks_usec() - started) / 1000)
		_mutex.lock()
		_results.append(result)
		_mutex.unlock()


func _import(job: Dictionary) -> Dictionary:
	if str(job.get("kind", "audio")) == "image":
		return ImageImport.import_file(str(job.cache), str(job.id), str(job.source))
	return AudioImport.import_file(str(job.cache), str(job.id), str(job.source))


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
	var landed := {"audio":[], "image":[]}
	for entry in entries:
		_done += 1
		_count(entry)
		_log_import(entry)
		if str(entry.get("status", "failed")) == "imported":
			landed[str(entry.get("kind", "audio"))].append(str(entry.get("id", "")))
	_emit_landed(landed)


func _count(entry: Dictionary) -> void:
	var kind := str(entry.get("kind", "audio"))
	if kind == "image":
		_image_done += 1
	else:
		_audio_done += 1
	match str(entry.get("status", "failed")):
		"imported":
			_imported += 1
		"skipped":
			_skipped += 1
		_:
			_failed += 1


func _emit_landed(landed: Dictionary) -> void:
	for kind in ["audio", "image"]:
		var ids: Array = landed[kind]
		if not ids.is_empty():
			imported.emit(kind, ids)


func _log_import(entry: Dictionary) -> void:
	var status := str(entry.get("status", "failed"))
	var success := status in ["imported", "skipped"]
	Events.file_transaction(_logger, "cache", "python_media_import", Schema.new_transaction_id(),
		success, Time.get_ticks_usec() - int(entry.get("duration_ms", 0)) * 1000,
		"OK" if success else str(entry.get("code", "SOURCE_UNREADABLE")),
		{"detail":str(entry.get("kind", "audio")) + ":" + str(entry.get("code", ""))})


func _complete_bulk() -> void:
	_mode = "done"
	_code = "" if _failed == 0 else "PARTIAL"
	_bulk_done = _failed == 0
	var cache := _cache_audio()
	if _bulk_done and not cache.is_empty():
		AudioImport.write_marker(cache, {
			"audio":_audio_total, "image":_image_total, "imported":_imported,
			"skipped":_skipped, "failed":_failed,
		}, _source_hash)
	_report()


func _reset_run(mode: String) -> void:
	_mode = mode
	_code = ""
	_total = 0
	_done = 0
	_imported = 0
	_skipped = 0
	_failed = 0
	_audio_total = 0
	_audio_done = 0
	_image_total = 0
	_image_done = 0
	_last_done = 0


func _finish(mode: String, code: String) -> void:
	if mode == "unavailable":
		_reset_run(mode)
	_mode = mode
	_code = code
	_report()


func _marker_allows_incremental(cache: String) -> bool:
	if cache.is_empty():
		return false
	if not _marker_checked:
		_marker_checked = true
		var marker := AudioImport.read_marker(cache)
		_bulk_done = not marker.is_empty() and str(marker.get("source_hash", "")) == _source_hash \
			and AudioImport.cached_count(cache) > 0
	return not _bulk_done and _mode != "bulk"


func _cache_audio() -> String:
	return str(_audio_directory.call()) if _audio_directory.is_valid() else ""


func _cache_images() -> String:
	return str(_images_directory.call()) if _images_directory.is_valid() else ""


func _save_path(path: String) -> void:
	if _settings == null:
		return
	_settings.set_value(SETTINGS_SECTION, SETTINGS_KEY, path)
	if _settings.save_settings() != OK:
		_log_warning("SETTINGS_SAVE_FAILED")


func _log_scan(outcome: String) -> void:
	if _logger == null:
		return
	var counts := {
		"audio":int(_scan_result.get("audio_count", 0)),
		"images":int(_scan_result.get("image_count", 0)),
		"unmatched":int(_scan_result.get("unmatched_count", 0)),
	}
	var event := "storage_media_scan" if outcome == "success" else "storage_media_scan_failed"
	var fields := {"scope":"file", "operation":"media_scan",
		"detail":str(_scan_result.get("code", "")), "phase":"complete" if outcome == "success" else "failed",
		"outcome":outcome, "duration_ms":0, "code":"OK" if outcome == "success" else "UNAVAILABLE",
		"data":counts, "module":"cache", "level":"INFO" if outcome == "success" else "WARN"}
	_logger.record_as("storage", event, fields)


func _log_warning(code: String) -> void:
	if _logger == null:
		return
	_logger.record_as("business", "settings_save_failed", {"code":code, "detail":"Python 客户端路径保存失败", "phase":"failed", "level":"WARN"})


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
