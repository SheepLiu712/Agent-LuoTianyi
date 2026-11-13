extends RefCounted
signal entry_added(entry: Dictionary)
signal write_failed(error: int)

const Schema = preload("res://src/storage/log_schema.gd")
const Release = preload("res://src/storage/release_info.gd")
const MODULES := Schema.MODULES
const SCHEMA_VERSION := 3
const DEFAULT_MAX_BYTES := 8 * 1024 * 1024
const DEFAULT_MAX_ENTRIES := 50000
const MAX_RUNS := 50
const MAX_PENDING := 4096

var _environment: Resource
var _directory: String
var _max_bytes: int
var _max_entries: int
var _token := RegEx.new()
var _id_pattern := RegEx.new()
var _metadata_tmp_pattern := RegEx.new()
var _id: String
var _entries: Array[Dictionary] = []
var _started := Time.get_ticks_msec()
var _meta: Dictionary
var _initialized := false
var _closed := false
var _archive_bytes := -1
var _archive_handle: FileAccess
var _archive_path := ""
var _seq := 0
var _debug_enabled := false
var _pending: Array[Dictionary] = []
var _pending_mutex := Mutex.new()
var _dropped_debug := 0
var _dropped_pending := 0
var _schema_warnings := 0
var _write_failures := 0
var _limit_reported := false
var _dropped_limit := 0
var _pending_drop_requested := false
var _pending_drop_reported := false

func _init(directory: String = "user://logs", max_bytes: int = DEFAULT_MAX_BYTES, environment: Variant = null, max_entries: int = DEFAULT_MAX_ENTRIES) -> void:
	_environment = environment if environment is Resource else preload("res://src/platform/godot_runtime_environment.gd").new()
	# 保留历史三参数签名，同时允许测试与受限部署显式给出单次运行条数上限。
	if environment is int:
		_max_entries = max(0, int(environment))
	else:
		_max_entries = max(0, max_entries)
	_max_bytes = max(0, max_bytes)
	_directory = directory
	_token.compile("^[a-zA-Z0-9_]{1,64}$")
	_id_pattern.compile("^[0-9]{20}_[0-9]+_[a-f0-9]{12}$")
	_metadata_tmp_pattern.compile("^[0-9]{20}_[0-9]+_[a-f0-9]{12}\\.json\\.tmp$")
	_id = "%020d_%d_%s" % [int(Time.get_unix_time_from_system() * 1000000), _environment.process_id(), Crypto.new().generate_random_bytes(6).hex_encode()]
	_debug_enabled = _environment.has_method("arguments") and "--debug-log" in _environment.arguments()
	_meta = {"id":_id, "started":Time.get_datetime_string_from_system(true) + "Z", "pid":_environment.process_id(), "closed":false, "complete":true,
		"schema_version":SCHEMA_VERSION, "debug_enabled":_debug_enabled,
		"release":Release.get_info(), "engine":Engine.get_version_info().string, "os":_environment.os_name(), "architecture":Engine.get_architecture_name(),
		"retention":{"max_bytes":_max_bytes, "max_entries":_max_entries, "max_runs":MAX_RUNS},
		"dropped_limit":0, "dropped_pending":0, "dropped_debug":0}

func record_as(category: String, event: String, fields: Dictionary = {}) -> Error:
	var scoped := fields.duplicate(true)
	var resolved := category if Schema.is_category(category) else Schema.category_for(event, scoped)
	scoped.category = resolved
	return _record_entry(resolved, event, scoped)

func _record_entry(category: String, event: String, fields: Dictionary) -> Error:
	if _closed or _token.search(event) == null:
		return ERR_INVALID_PARAMETER
	var scoped := fields.duplicate(true)
	_prepare_fields(scoped, event, category)
	var level := _resolved_level(category, scoped)
	if level == "DEBUG" and not _debug_enabled:
		_dropped_debug += 1
		return OK
	var entry := _build_entry(category, event, scoped, level)
	return _commit_built(entry, category)

func _prepare_fields(scoped: Dictionary, event: String, category: String) -> void:
	if not Schema.is_origin(scoped.get("origin")):
		scoped.origin = Schema.infer_origin(event, scoped, category)

func _resolved_level(category: String, scoped: Dictionary) -> String:
	var level := Schema.default_level(category, scoped)
	if scoped.get("level") is String and Schema.is_level(scoped.level):
		return scoped.level
	return level

func _build_entry(category: String, event: String, scoped: Dictionary, level: String) -> Dictionary:
	var entry := {"time":Time.get_datetime_string_from_system(true) + "Z", "elapsed_ms":Time.get_ticks_msec() - _started,
		"run_id":_id, "seq":_seq, "category":category, "event":event, "level":level,
		"module":Schema.module_for(event, scoped), "message":Schema.explanation(event)}
	if Schema.EVENT_REGISTRY.has(event):
		entry.phase = Schema.EVENT_REGISTRY[event].get("phase", "unknown")
	_seq += 1
	_apply_fields(entry, scoped)
	_normalize_entry(entry, category)
	if not entry.get("code") is String:
		entry.code = ""
	if not entry.get("detail") is String:
		entry.detail = ""
	var missing := Schema.apply_defaults(entry, category)
	if not missing.is_empty():
		_schema_warnings += 1
	return entry

func _commit_built(entry: Dictionary, _category: String) -> Error:
	var written := _commit_entry(entry)
	var error: Error = written.error
	if error != OK and not written.limit_rejected:
		# 普通磁盘失败保留内存视图；容量超限的条目直接丢弃。
		_entries.append(entry)
		_on_write_error(error)
	if not written.limit_rejected:
		entry_added.emit(entry.duplicate(true))
	return error

func _commit_entry(entry: Dictionary) -> Dictionary:
	var serialized := JSON.stringify(entry).to_utf8_buffer()
	var is_over_limit := _entries.size() >= _max_entries
	if not is_over_limit:
		is_over_limit = _archive_size() + serialized.size() + 1 > _max_bytes
	if is_over_limit:
		_dropped_limit += 1
		if not _limit_reported:
			_limit_reported = true
			_meta.complete = false
			_write_limit_diagnostic()
			_sync_drop_metadata()
			_save_metadata()
			write_failed.emit(ERR_OUT_OF_MEMORY)
		return {"error":ERR_OUT_OF_MEMORY, "limit_rejected":true}
	var error := _ensure_directory()
	if error != OK:
		return {"error":error, "limit_rejected":false}
	var written := _write_entry(serialized)
	if written.error == OK:
		_entries.append(entry)
	return written

## 首次超限时额外写入一条诊断条目（软上限），之后静默丢弃，避免反复同步写盘。
func _write_limit_diagnostic() -> void:
	var fields := {"outcome":"failure", "code":"LOG_LIMIT_REACHED", "phase":"error", "level":"ERROR",
		"detail":"log capacity reached (%d entries / %d bytes); later entries are dropped in this run" % [_max_entries, _max_bytes]}
	var entry := _build_entry("system", "log_limit_reached", fields, "ERROR")
	var written := _write_entry(JSON.stringify(entry).to_utf8_buffer())
	if written.error == OK:
		_entries.append(entry)
		entry_added.emit(entry.duplicate(true))
	else:
		_write_failures += 1

func _on_write_error(error: int) -> void:
	_meta.complete = false
	_write_failures += 1
	_save_metadata()
	write_failed.emit(error)

## 工作线程只入队，主线程 drain 后统一写盘。
func record_threadsafe(category: String, event: String, fields: Dictionary = {}) -> void:
	if _closed:
		return
	var item := {"category":category, "event":event, "fields":fields.duplicate(true)}
	_pending_mutex.lock()
	if _pending.size() >= MAX_PENDING:
		_pending.pop_front()
		_dropped_pending += 1
		_pending_drop_requested = true
	_pending.append(item)
	_pending_mutex.unlock()

func drain() -> int:
	var items: Array[Dictionary] = []
	var report_drop := false
	_pending_mutex.lock()
	if not _pending.is_empty():
		items = _pending.duplicate()
		_pending.clear()
	if _pending_drop_requested and not _pending_drop_reported:
		_pending_drop_reported = true
		_pending_drop_requested = false
		report_drop = true
	_pending_mutex.unlock()
	# _process 每帧都会调用；没有后台日志时不要复制/清空整个队列。
	if items.is_empty() and not report_drop:
		return 0
	for item in items:
		if _closed:
			break
		record_as(str(item.category), str(item.event), item.fields)
	if report_drop:
		_record_pending_drop()
	return items.size()

## 后台队列溢出每次运行只报告一次；总量留在 metadata 与状态栏。
func _record_pending_drop() -> void:
	record_as("system", "log_pending_dropped", {"outcome":"failure", "code":"LOG_PENDING_DROPPED",
		"phase":"warning", "level":"WARN", "count":_dropped_pending,
		"detail":"background log queue overflowed; oldest entries were dropped"})

func get_pending_count() -> int:
	_pending_mutex.lock()
	var size := _pending.size()
	_pending_mutex.unlock()
	return size

func set_debug_enabled(enabled: bool) -> void:
	_debug_enabled = enabled
	_meta.debug_enabled = enabled
	if _initialized:
		_save_metadata()

func is_debug_enabled() -> bool:
	return _debug_enabled

func get_stats() -> Dictionary:
	var by_category := {}
	var by_level := {}
	var by_origin := {}
	for entry in _entries:
		var category: String = entry.get("category", "info")
		var level: String = entry.get("level", "INFO")
		var origin: String = entry.get("origin", "unknown")
		by_category[category] = int(by_category.get(category, 0)) + 1
		by_level[level] = int(by_level.get(level, 0)) + 1
		by_origin[origin] = int(by_origin.get(origin, 0)) + 1
	return {"entries":_entries.size(), "by_category":by_category, "by_level":by_level, "by_origin":by_origin,
		"dropped_debug":_dropped_debug, "dropped_pending":_dropped_pending,
		"dropped_limit":_dropped_limit, "schema_warnings":_schema_warnings,
		"write_failures":_write_failures, "pending":get_pending_count()}

func ensure_ready() -> Error:
	return OK if _initialized else _ensure_directory()

func get_directory() -> String:
	return ProjectSettings.globalize_path(_directory)

func get_run_id() -> String:
	return _id

func finish() -> void:
	if _closed:
		return
	drain()
	record_as("business", "app_stopped", {"phase":"stopped", "reason":"normal", "uptime_ms":Time.get_ticks_msec() - _started, "pid":_environment.process_id()})
	_close_archive()
	_closed = true
	_meta.closed = true
	_meta.entries = _entries.size()
	_sync_drop_metadata()
	if _save_metadata() != OK:
		_meta.complete = false
		_write_failures += 1
		write_failed.emit(ERR_CANT_CREATE)

func list_runs() -> Array[Dictionary]:
	var runs := _all_runs()
	runs.assign(runs.filter(func(run): return int(run.get("schema_version", 1)) >= SCHEMA_VERSION))
	return runs

func _all_runs() -> Array[Dictionary]:
	var runs: Array[Dictionary] = []
	if not DirAccess.dir_exists_absolute(_directory):
		return runs
	for file in DirAccess.get_files_at(_directory):
		var data := _read_run_metadata(file)
		if not data.is_empty():
			runs.append(data)
	runs.sort_custom(func(a,b): return a.id > b.id)
	return runs

func _read_run_metadata(file: String) -> Dictionary:
	var id := file.trim_suffix(".json")
	if not file.ends_with(".json") or _id_pattern.search(id) == null:
		return {}
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(_path(id, ".json")))
	if not _valid_run_metadata(parsed, id):
		return {}
	var data: Dictionary = parsed
	data.active = not data.get("closed", false) and _environment.process_running(int(data.pid))
	_finalize_run_metadata(data, id)
	data.schema_version = int(data.get("schema_version", 1))
	return data

func _finalize_run_metadata(data: Dictionary, id: String) -> void:
	if id == _id:
		data.complete = bool(_meta.complete)
		data.entries = _entries.size()
	elif data.has("entries"):
		# 新格式把条数/完整性写进元数据；只确认归档仍在，不再逐行解析 8 MiB JSONL。
		data.complete = data.get("complete", false) and FileAccess.file_exists(_path(id, ".jsonl"))
	else:
		data.complete = false

func read_entries(run_id: String = "") -> Array[Dictionary]:
	if run_id.is_empty() or run_id == _id:
		drain()
		return _entries.duplicate(true)
	var result: Array[Dictionary] = []
	result.assign(_read_archive(run_id).entries)
	return result

func export_run(run_id: String, destination_zip: String) -> Error:
	if FileAccess.file_exists(destination_zip):
		return ERR_ALREADY_EXISTS
	var metadata: Dictionary = {}
	for run in list_runs():
		if run.id == run_id:
			metadata = run
	if run_id == _id:
		_sync_drop_metadata()
		metadata = _meta.duplicate(true)
	if metadata.is_empty():
		return ERR_DOES_NOT_EXIST
	var read := _read_archive(run_id) if run_id != _id else {"entries":read_entries(), "complete":_meta.complete}
	var events := ""
	var readable := ""
	var counts := {}
	var origin_counts := {}
	for entry in read.entries:
		events += JSON.stringify(entry) + "\n"
		var origin: String = entry.get("origin", "unknown")
		var origin_label: String = Schema.ORIGIN_LABELS.get(origin, origin)
		readable += "%s [%s] [%s] [%s] [%s] %s (%s) %s\n" % [entry.time,entry.level,entry.get("category","info"),origin_label,entry.module,entry.message,entry.event,entry.get("code", "")]
		var category: String = entry.get("category", "info")
		counts[category] = int(counts.get(category, 0)) + 1
		origin_counts[origin] = int(origin_counts.get(origin, 0)) + 1
	# 只导出白名单摘要，不携带任意磁盘元数据、路径或环境变量。
	var summary := {"release":metadata.get("release",Release.get_info()), "engine":Engine.get_version_info().string,
		"os":_environment.os_name(), "architecture":Engine.get_architecture_name(), "schema_version":int(metadata.get("schema_version", SCHEMA_VERSION)),
		"closed":metadata.get("closed",false), "complete":metadata.get("complete",false) and read.complete,
		"debug_enabled":metadata.get("debug_enabled", false), "count":read.entries.size(), "counts_by_category":counts,
		"counts_by_origin":origin_counts, "dropped_limit":int(metadata.get("dropped_limit", 0)),
		"dropped_pending":int(metadata.get("dropped_pending", 0)), "dropped_debug":int(metadata.get("dropped_debug", 0)),
		"retention":metadata.get("retention", {"max_bytes":_max_bytes, "max_entries":_max_entries, "max_runs":MAX_RUNS})}
	return _write_export(destination_zip, [["events.jsonl",events],["readable.txt",readable],["environment.json",JSON.stringify(summary)]])

func _sync_drop_metadata() -> void:
	_meta.dropped_limit = _dropped_limit
	_meta.dropped_pending = _dropped_pending
	_meta.dropped_debug = _dropped_debug

func _ensure_directory() -> Error:
	if _initialized:
		return OK
	var ancestor := _directory
	while not ancestor.is_empty():
		if FileAccess.file_exists(ancestor):
			return ERR_CANT_CREATE
		var parent := ancestor.get_base_dir()
		if parent == ancestor:
			break
		ancestor = parent
	var error := DirAccess.make_dir_recursive_absolute(_directory)
	if error != OK:
		return error
	for name in DirAccess.get_files_at(_directory):
		if _metadata_tmp_pattern.search(name) == null:
			continue
		error = DirAccess.remove_absolute(_directory.path_join(name))
		if error != OK:
			return error
	error = _save_metadata()
	if error == OK:
		_initialized = true
		_prune()
	return error

func _save_metadata() -> Error:
	var temporary := _path(_id, ".json.tmp")
	var file := FileAccess.open(temporary, FileAccess.WRITE)
	if file == null:
		return FileAccess.get_open_error()
	file.store_string(JSON.stringify(_meta))
	file.flush()
	var error := file.get_error()
	file.close()
	if error == OK:
		error = DirAccess.rename_absolute(temporary, _path(_id, ".json"))
	if error != OK and FileAccess.file_exists(temporary):
		DirAccess.remove_absolute(temporary)
	return error

func _prune() -> void:
	var runs := _all_runs()
	var excess := runs.size() - MAX_RUNS
	runs.reverse()
	for run in runs:
		if excess <= 0:
			break
		if run.active or run.id == _id:
			continue
		var error := OK
		for suffix in [".jsonl", ".json"]:
			var path := _path(run.id, suffix)
			if FileAccess.file_exists(path):
				error = DirAccess.remove_absolute(path)
				if error != OK:
					break
		if error == OK:
			excess -= 1
		else:
			_write_failures += 1
			write_failed.emit(error)

func _path(id: String, suffix: String) -> String:
	return _directory.path_join(id + suffix)

func _jsonl_size(path: String) -> int:
	if not FileAccess.file_exists(path):
		return 0
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return 0
	var size := file.get_length()
	file.close()
	return size

## 写入前只探测一次已有 JSONL 大小；后续由 _append_entry_file 增量维护。
func _archive_size() -> int:
	if _archive_bytes < 0:
		_archive_bytes = _jsonl_size(_path(_id, ".jsonl"))
	return _archive_bytes

func _read_archive(id: String) -> Dictionary:
	var result := {"entries":[], "complete":true}
	if _id_pattern.search(id) == null or not FileAccess.file_exists(_path(id,".jsonl")):
		result.complete = false
		return result
	var file := FileAccess.open(_path(id,".jsonl"), FileAccess.READ)
	if file == null:
		result.complete = false
		return result
	while file.get_position() < file.get_length():
		var value: Variant = JSON.parse_string(file.get_line())
		if not _valid_archive_entry(value):
			result.complete = false
			continue
		var safe := _safe_archive_entry(value)
		result.entries.append(safe)
	file.close()
	return result

func _apply_fields(entry: Dictionary, fields: Dictionary) -> void:
	_apply_metrics(entry, fields)
	for key in Schema.STRING_FIELDS:
		if key in ["level", "module", "category", "event"]:
			continue
		var value: Variant = fields.get(key)
		if value is String:
			_apply_string_field(entry, key, value)
	_apply_payload(entry, fields)

func _apply_metrics(entry: Dictionary, fields: Dictionary) -> void:
	for key in Schema.METRICS:
		var value: Variant = fields.get(key)
		if value is bool or value is int or (value is float and is_finite(value)):
			entry[key] = value

func _apply_payload(entry: Dictionary, fields: Dictionary) -> void:
	if fields.get("stack") is Array:
		entry.stack = Schema.sanitize_stack(fields.stack)
	if fields.get("data") is Dictionary:
		entry.data = Schema.sanitize_data(fields.data)
	if fields.get("level") is String and Schema.is_level(fields.level):
		entry.level = fields.level

func _apply_string_field(entry: Dictionary, key: String, value: String) -> void:
	if key in ["code", "reason_code", "phase", "outcome", "channel", "scope", "origin"]:
		_apply_enum_field(entry, key, value)
	elif key in ["route", "method", "action", "operation"]:
		_apply_action_field(entry, key, value)
	elif key in ["subject", "trace_id", "transaction_id", "reply_id"]:
		_apply_token_field(entry, key, value)
	else:
		_apply_detail_field(entry, key, value)

func _apply_enum_field(entry: Dictionary, key: String, value: String) -> void:
	if key in ["code", "reason_code"] and value.is_empty():
		entry[key] = ""
		return
	entry[key] = _enum_value(key, value)

func _enum_value(key: String, value: String) -> String:
	if key in ["code", "reason_code"]:
		return Schema.safe_code(value)
	var simple := {
		"origin": value if Schema.is_origin(value) else "unknown",
		"phase": Schema.safe_phase(value),
		"outcome": value if Schema.is_outcome(value) else "unknown",
		"channel": value if Schema.is_channel(value) else "app",
		"scope": value if Schema.is_scope(value) else "unknown",
	}
	return str(simple.get(key, value))

func _apply_action_field(entry: Dictionary, key: String, value: String) -> void:
	match key:
		"route":
			entry[key] = Schema.safe_route(value)
		"method":
			entry[key] = Schema.safe_method(value)
		_:
			entry[key] = Schema.safe_action(value)

func _apply_token_field(entry: Dictionary, key: String, value: String) -> void:
	if key == "reply_id":
		entry[key] = value.sha256_text().left(12)
	elif key == "trace_id":
		entry[key] = value if Schema.is_trace_id(value) else ""
	else:
		entry[key] = value if Schema.is_token(value) else ""

func _apply_detail_field(entry: Dictionary, key: String, value: String) -> void:
	entry[key] = Schema.sanitize_text(value) if key == "detail" else Schema.sanitize_text(value, 128)

func _normalize_entry(entry: Dictionary, category: String) -> void:
	if not Schema.is_level(entry.get("level")):
		entry.level = Schema.default_level(category, entry)
	if not Schema.is_category(entry.get("category")):
		entry.category = category
	if not Schema.is_outcome(entry.get("outcome")):
		entry.outcome = "unknown"
	if not Schema.is_origin(entry.get("origin")):
		entry.origin = "unknown"
	_normalize_trace(entry, category)
	_normalize_runtime(entry, category)

func _normalize_trace(entry: Dictionary, category: String) -> void:
	if category != "network":
		entry.erase("trace_id")
	elif not Schema.is_trace_id(entry.get("trace_id")):
		entry.trace_id = Schema.new_trace_id("net")

func _normalize_runtime(entry: Dictionary, category: String) -> void:
	if category == "runtime":
		entry.uptime_ms = int(entry.get("uptime_ms", entry.get("elapsed_ms", 0)))
		entry.pid = int(entry.get("pid", _environment.process_id()))

func _write_entry(serialized: PackedByteArray) -> Dictionary:
	var path := _path(_id, ".jsonl")
	return {"error":_append_entry_file(path, serialized), "limit_rejected":false}

func _append_entry_file(path: String, serialized: PackedByteArray) -> Error:
	var error := OK
	var file := _archive_handle
	if file == null or _archive_path != path:
		_close_archive()
		file = FileAccess.open(path, FileAccess.READ_WRITE if FileAccess.file_exists(path) else FileAccess.WRITE)
		_archive_handle = file
		_archive_path = path if file != null else ""
	if file == null:
		error = FileAccess.get_open_error()
		_archive_bytes = -1
	else:
		file.seek_end()
		file.store_buffer(serialized)
		file.store_8(10)
		file.flush()
		error = file.get_error()
		if error == OK:
			_archive_bytes += serialized.size() + 1
		else:
			_archive_bytes = -1
			_close_archive()
	return error


func _close_archive() -> void:
	if _archive_handle != null:
		_archive_handle.flush()
		_archive_handle.close()
	_archive_handle = null
	_archive_path = ""

func _valid_run_metadata(data: Variant, id: String) -> bool:
	return data is Dictionary and data.get("id") == id and (data.get("pid") is float or data.get("pid") is int)

func _write_export(destination_zip: String, files: Array) -> Error:
	var zip := ZIPPacker.new()
	var error := zip.open(destination_zip)
	if error != OK:
		return error
	for pair in files:
		error = zip.start_file(pair[0])
		if error == OK:
			error = zip.write_file(pair[1].to_utf8_buffer())
		if error == OK:
			error = zip.close_file()
		if error != OK:
			break
	var closed := zip.close()
	if error == OK:
		error = closed
	if error != OK:
		DirAccess.remove_absolute(destination_zip)
	return error

func _valid_archive_entry(value: Variant) -> bool:
	return value is Dictionary and value.get("event") is String and _token.search(value.event) != null \
		and value.get("time") is String and value.get("level") in Schema.LEVELS and value.get("module") in MODULES \
		and (not value.has("category") or Schema.is_category(value.category))

func _safe_archive_entry(value: Dictionary) -> Dictionary:
	var event: String = value.event
	var category := Schema.category_for(event, value)
	var safe := {"event":event,"time":value.time.left(32),"level":value.level,"module":value.module,
		"message":Schema.explanation(event),"category":category}
	_copy_metrics(safe, value)
	_copy_strings(safe, value)
	_copy_identifiers(safe, value)
	_copy_enums(safe, value)
	_copy_actions(safe, value)
	_copy_payload(safe, value)
	if not safe.has("origin"):
		safe.origin = Schema.infer_origin(event, value, category)
	return safe

func _copy_metrics(safe: Dictionary, value: Dictionary) -> void:
	for key in Schema.METRICS + ["elapsed_ms"]:
		if value.get(key) is bool or value.get(key) is int or value.get(key) is float:
			safe[key] = value[key]

func _copy_strings(safe: Dictionary, value: Dictionary) -> void:
	for key in ["code","phase","reply_id","reason","schema_missing","run_id","model_type"]:
		if value.get(key) is String and _token.search(value[key]) != null:
			safe[key] = _safe_archive_string(key, value[key])

func _safe_archive_string(key: String, value: String) -> String:
	if key in ["reply_id", "run_id"]:
		return value
	if key == "code":
		return Schema.safe_code(value)
	if key == "phase":
		return Schema.safe_phase(value)
	return Schema.sanitize_text(value, 128)

func _copy_identifiers(safe: Dictionary, value: Dictionary) -> void:
	if value.get("trace_id") is String and Schema.is_trace_id(value.trace_id):
		safe.trace_id = value.trace_id
	for key in ["transaction_id", "subject", "previous_run_id"]:
		if value.get(key) is String and Schema.is_token(value[key]):
			safe[key] = value[key]

func _copy_enums(safe: Dictionary, value: Dictionary) -> void:
	if value.get("channel") is String and Schema.is_channel(value.channel):
		safe.channel = value.channel
	if value.get("scope") is String and Schema.is_scope(value.scope):
		safe.scope = value.scope
	if value.get("outcome") is String and Schema.is_outcome(value.outcome):
		safe.outcome = value.outcome
	if value.get("origin") is String and Schema.is_origin(value.origin):
		safe.origin = value.origin

func _copy_actions(safe: Dictionary, value: Dictionary) -> void:
	for key in ["action", "operation"]:
		if value.get(key) is String:
			safe[key] = Schema.safe_action(value[key])
	if value.get("method") is String:
		safe.method = Schema.safe_method(value.method)
	if value.get("route") is String:
		safe.route = Schema.safe_route(value.route)

func _copy_payload(safe: Dictionary, value: Dictionary) -> void:
	if value.get("detail") is String:
		safe.detail = Schema.sanitize_text(value.detail)
	if value.get("stack") is Array:
		safe.stack = Schema.sanitize_stack(value.stack)
	if value.get("data") is Dictionary:
		safe.data = Schema.sanitize_data(value.data)
