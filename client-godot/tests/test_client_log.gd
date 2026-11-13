extends SceneTree
const Log = preload("res://src/storage/client_log.gd")
var failures: Array[String] = []

func check(value: bool, description: String) -> void:
	if not value:
		failures.append(description)
		print("FAIL: ", description)

func _initialize() -> void:
	var directory := "user://log-test-%s" % Time.get_ticks_usec()
	var log = Log.new(directory, 64 * 1024, null, 256)
	log.record_as("business", "app_started", {"phase":"starting"})
	check(log.has_method("read_entries"), "startup records remain queryable from launch")
	if not log.has_method("read_entries"):
		DirAccess.remove_absolute(directory + "/client.jsonl")
		DirAccess.remove_absolute(directory)
		quit(1)
		return
	for index in range(120):
		check(log.record_as("business", "message_reply_received", {"reply_id":"synthetic-uuid", "frames":index,
			"has_audio":true,"token":"SECRET-TOKEN", "text":"SECRET-TEXT", "code":"bad secret code",
			"phase":"received"}) == OK, "record written")
	var entries: Array = log.read_entries()
	_check_no_truncation_of_launch_records(entries)
	var raw := JSON.stringify(entries)
	_check_secrets_excluded(raw)
	check(entries[1].reply_id == "synthetic-uuid".sha256_text().left(12), "correlation hashed")
	_check_terminal_metadata_present(entries)
	log.record_as("business", "message_error", {"code":"TIMEOUT", "phase":"error", "detail":""})
	check(not JSON.stringify(log.read_entries()).contains("SECRET"), "code-shaped secrets are not logged")
	var id: String = log.get_run_id()
	log.finish()
	log.finish()
	check(log.read_entries().size() == 123, "finish is idempotent")
	check(log.record_as("business", "message_queued", {"phase":"queued"}) != OK, "closed run immutable")
	var observer = Log.new(directory)
	check(observer.read_entries(id).size() == 123, "complete run recovered across instances")
	var zip_path := directory + "/diagnostic.zip"
	check(observer.export_run(id, zip_path) == OK, "export whole selected startup")
	var zip := ZIPReader.new()
	check(zip.open(zip_path) == OK, "export is valid ZIP")
	check(zip.get_files().size() == 3, "only diagnostic entries included")
	for name in zip.get_files():
		check(not zip.read_file(name).get_string_from_utf8().contains("SECRET"), "all ZIP entries sanitized")
	check(zip.read_file("events.jsonl").get_string_from_utf8().contains("app_started"), "export retains beginning")
	check(zip.read_file("readable.txt").get_string_from_utf8().contains("客户端启动"), "readable Chinese explanation")
	check(zip.read_file("environment.json").get_string_from_utf8().contains("counts_by_origin"), "export summarizes fault origins")
	check(zip.read_file("environment.json").get_string_from_utf8().contains("\"dropped_limit\""), "export reports capacity drops")
	check(zip.read_file("environment.json").get_string_from_utf8().contains("\"dropped_pending\""), "export reports queue drops")
	zip.close()
	check(observer.export_run(id, zip_path) != OK, "export does not overwrite")
	observer.record_as("business", "app_started", {"phase":"starting"})
	var active: String = observer.get_run_id()
	for index in range(53):
		var run = Log.new(directory)
		run.record_as("business", "app_started", {"phase":"starting"})
		run.finish()
	var runs: Array = observer.list_runs()
	check(runs.size() == 50, "50 startup retention")
	check(not observer.read_entries(active).is_empty(), "another active instance protected")
	check(observer.read_entries(id).is_empty(), "old finished run evicted whole")
	check(observer.read_entries("../diagnostic").is_empty(), "path traversal rejected")
	observer.finish()
	var bad = Log.new(zip_path + "/impossible")
	check(bad.record_as("system", "state_snapshot", {}) != OK, "write failure surfaced")
	check(bad.read_entries().size() == 1, "failed disk write retained for current viewer")
	_check_capacity_and_recovery()
	for file in DirAccess.get_files_at(directory):
		DirAccess.remove_absolute(directory.path_join(file))
		DirAccess.remove_absolute(directory)
	_check_categories()
	print("Client startup diagnostics: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func _check_capacity_and_recovery() -> void:
	var limited_directory := "user://log-limit-test-%s" % Time.get_ticks_usec()
	var limited = Log.new(limited_directory, 2048, null, 3)
	check(limited.record_as("system", "state_snapshot", {}) == OK, "limited log accepts first entry")
	check(limited.record_as("system", "state_snapshot", {"count":1}) == OK, "limited log accepts entries within count")
	check(limited.record_as("system", "state_snapshot", {"count":2}) == OK, "limited log accepts final count")
	check(limited.record_as("system", "state_snapshot", {"count":3}) != OK, "limited log rejects entries beyond count")
	var limited_entries: Array = limited.read_entries()
	check(limited_entries.size() == 4 and limited_entries[-1].event == "log_limit_reached", "limit diagnostic is written once")
	check(limited.get_stats().dropped_limit == 1, "limit drop is counted")
	var limited_meta: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(
		limited_directory.path_join(limited.get_run_id() + ".json")))
	check(int(limited_meta.get("dropped_limit", 0)) == 1, "limit drop is persisted in metadata")
	var limited_file := limited_directory.path_join(limited.get_run_id() + ".jsonl")
	check(FileAccess.get_file_as_bytes(limited_file).size() > 0, "capacity diagnostic keeps archive readable")
	check(limited.record_as("system", "state_snapshot", {"count":4}) != OK, "later entries remain dropped")
	check(limited.get_stats().dropped_limit == 2, "every rejected entry remains counted")
	var byte_directory := "user://log-byte-limit-test-%s" % Time.get_ticks_usec()
	var byte_limited = Log.new(byte_directory, 600, null, 100)
	check(byte_limited.record_as("system", "state_snapshot", {}) == OK, "byte-limited log accepts first entry")
	check(byte_limited.record_as("system", "state_snapshot", {"detail":"error detail ".repeat(100)}) != OK, "byte-limited log rejects oversized run")
	var byte_file := byte_directory.path_join(byte_limited.get_run_id() + ".jsonl")
	var byte_entries: Array = byte_limited.read_entries()
	check(byte_entries.size() == 2 and byte_entries[-1].event == "log_limit_reached", "byte limit writes one diagnostic")
	var byte_lines: Array = Array(FileAccess.get_file_as_string(byte_file).strip_edges().split("\n"))
	check(byte_lines.size() == 2 and byte_lines.all(func(line): return JSON.parse_string(line) is Dictionary), "byte limit never leaves a partial JSON line")
	var stale_metadata := limited_directory.path_join(limited.get_run_id() + ".json.tmp")
	var stale_file := FileAccess.open(stale_metadata, FileAccess.WRITE)
	stale_file.store_string("stale")
	stale_file.close()
	var reopened = Log.new(limited_directory, 2048, null, 3)
	check(reopened.record_as("system", "state_snapshot", {}) == OK, "reopened log writes after stale metadata")
	check(not FileAccess.file_exists(stale_metadata), "stale metadata temporary file cleaned")
	reopened.finish()
	for file in DirAccess.get_files_at(limited_directory):
		DirAccess.remove_absolute(limited_directory.path_join(file))
	DirAccess.remove_absolute(limited_directory)
	for file in DirAccess.get_files_at(byte_directory):
		DirAccess.remove_absolute(byte_directory.path_join(file))
	DirAccess.remove_absolute(byte_directory)

func _check_terminal_metadata_present(entries: Variant) -> void:
	check(entries[1].has_audio and entries[1].has("module") and entries[1].has("level"), "terminal metadata present")

func _check_no_truncation_of_launch_records(entries: Variant) -> void:
	check(entries.size() == 121 and entries[0].event == "app_started", "no truncation of launch records")

func _check_secrets_excluded(raw: Variant) -> void:
	check(not raw.contains("SECRET") and not raw.contains("bad secret code"), "secrets excluded")

func _check_categories() -> void:
	var directory := "user://log-category-test-%s" % Time.get_ticks_usec()
	var log = Log.new(directory, 8 * 1024 * 1024, null, 1000)
	log.set_debug_enabled(true)
	_write_categories(log)
	_check_category_entries(log)
	_check_origins(directory)
	_check_missing_fields(directory)
	_check_debug_and_threadsafe(directory)
	log.finish()
	_cleanup_category_dirs(directory)

func _write_categories(log) -> void:
	check(log.record_as("business", "settings_save_failed", {"code":"SETTINGS_SAVE_FAILED", "detail":"save", "phase":"failed", "level":"WARN"}) == OK, "business category writes")
	check(log.record_as("network", "network_http", {"channel":"http", "action":"request", "method":"GET", "route":"/history", "status":200, "outcome":"success", "duration_ms":3, "bytes":10, "code":"OK"}) == OK, "network category writes")
	check(log.record_as("storage", "storage_sqlite_operation", {"scope":"sqlite", "operation":"save_live", "outcome":"success", "duration_ms":4, "code":"OK"}) == OK, "storage category writes")
	check(log.record_as("system", "system_resource_sample", {"operation":"resource_sample", "outcome":"success", "duration_ms":1, "fps":60}) == OK, "system category writes")
	check(log.record_as("system", "state_snapshot", {"level":"DEBUG", "data":{"state":"ready"}}) == OK, "debug snapshot writes")

func _check_category_entries(log) -> void:
	var entries: Array = log.read_entries()
	var categories := {}
	for entry in entries:
		categories[entry.category] = true
	check(categories.size() == 4, "four domain categories present")
	for entry in entries:
		for key in {"business":["phase"], "network":["channel","route","outcome","duration_ms"], "storage":["scope","operation","outcome","duration_ms"], "system":[]}[entry.category]:
			check(entry.has(key), "required field " + entry.category + "." + key)
		check(entry.has("code") and entry.has("detail"), "common code and detail fields present")

func _check_origins(directory: String) -> void:
	var log = Log.new(directory.path_join("origins"), 8 * 1024 * 1024, null, 100)
	check(log.record_as("business", "message_error", {"code":"CACHE_WRITE_FAILED", "detail":"cache", "phase":"error", "level":"ERROR"}) == OK, "client error writes")
	check(log.record_as("business", "message_error", {"code":"AUTH_REJECTED", "detail":"auth", "phase":"error", "level":"ERROR"}) == OK, "server error writes")
	check(log.record_as("business", "message_error", {"code":"REMOTE_AUDIO_ERROR", "detail":"tts", "phase":"error", "level":"ERROR"}) == OK, "upstream error writes")
	check(log.record_as("network", "network_http", {"channel":"http", "action":"request", "method":"GET", "route":"/auth/public_key",
		"status":0, "outcome":"failure", "duration_ms":1, "bytes":0, "code":"NETWORK_ERROR"}) == OK, "network access writes")
	check(log.record_as("network", "network_http", {"channel":"http", "action":"request", "method":"GET", "route":"/history",
		"status":503, "outcome":"failure", "duration_ms":1, "bytes":0, "code":"HTTP_ERROR"}) == OK, "server access writes")
	var origins: Array = log.read_entries().map(func(entry): return entry.origin)
	check(origins == ["client", "server", "upstream", "network", "server"], "origin inferred from code and HTTP status")
	var stats: Dictionary = log.get_stats()
	check(int(stats.by_origin.get("server", 0)) == 2 and int(stats.by_origin.get("network", 0)) == 1, "stats group by origin")
	log.finish()

func _check_missing_fields(directory: String) -> void:
	var missing_log = Log.new(directory.path_join("missing"), 8 * 1024 * 1024, null, 100)
	check(missing_log.record_as("network", "network_http", {}) == OK, "missing fields still write")
	var missing_entry: Dictionary = missing_log.read_entries()[0]
	check(missing_entry.has("schema_missing") and missing_entry.has("trace_id") and missing_entry.route == "/unknown", "missing fields auto-filled")
	missing_log.finish()

func _check_debug_and_threadsafe(directory: String) -> void:
	var debug_off = Log.new(directory.path_join("off"), 8 * 1024 * 1024, null, 100)
	check(debug_off.record_as("system", "state_snapshot", {"level":"DEBUG", "data":{"a":1}}) == OK, "debug disabled returns ok")
	check(debug_off.read_entries().is_empty(), "debug disabled drops entry")
	check(debug_off.get_stats().dropped_debug == 1, "debug drop counted")
	debug_off.set_debug_enabled(true)
	check(debug_off.record_as("system", "state_snapshot", {"level":"DEBUG", "data":{"a":1}}) == OK and debug_off.read_entries().size() == 1, "debug enabled writes")
	debug_off.finish()
	var threaded = Log.new(directory.path_join("threaded"), 8 * 1024 * 1024, null, 100)
	threaded.record_threadsafe("business", "message_queued", {"phase":"queued"})
	check(threaded.get_pending_count() == 1 and threaded.drain() == 1, "thread safe queue drains")
	check(threaded.read_entries()[0].event == "message_queued", "thread safe event written")
	threaded.finish()
	var dropped = Log.new(directory.path_join("dropped"), 8 * 1024 * 1024, null, 10000)
	for index in range(4100):
		dropped.record_threadsafe("business", "message_queued", {"phase":"queued", "count":index})
	check(dropped.drain() == 4096, "pending queue keeps its bounded window")
	check(dropped.get_stats().dropped_pending == 4, "pending overflow is counted")
	var drop_events: Array = dropped.read_entries().filter(func(entry): return entry.event == "log_pending_dropped")
	check(drop_events.size() == 1 and int(drop_events[0].count) == 4, "pending overflow reports one aggregate diagnostic")
	dropped.finish()
	var drop_meta: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(
		directory.path_join("dropped").path_join(dropped.get_run_id() + ".json")))
	check(int(drop_meta.get("dropped_pending", 0)) == 4, "pending overflow is persisted in metadata")

func _cleanup_category_dirs(directory: String) -> void:
	for child in ["", "origins", "missing", "off", "threaded", "dropped"]:
		var path := directory if child.is_empty() else directory.path_join(child)
		if DirAccess.dir_exists_absolute(path):
			for file in DirAccess.get_files_at(path):
				DirAccess.remove_absolute(path.path_join(file))
			DirAccess.remove_absolute(path)
