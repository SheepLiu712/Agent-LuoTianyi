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
	log.record("client_started")
	check(log.has_method("read_entries"), "startup records remain queryable from launch")
	if not log.has_method("read_entries"):
		DirAccess.remove_absolute(directory + "/client.jsonl")
		DirAccess.remove_absolute(directory)
		quit(1)
		return
	for index in range(120):
		check(log.record("reply_received", {"reply_id":"synthetic-uuid", "frames":index,
			"has_audio":true,"token":"SECRET-TOKEN", "text":"SECRET-TEXT", "code":"bad secret code"}) == OK, "record written")
	var entries: Array = log.read_entries()
	_check_no_truncation_of_launch_records(entries)
	var raw := JSON.stringify(entries)
	_check_secrets_excluded(raw)
	check(entries[1].reply_id == "synthetic-uuid".sha256_text().left(12), "correlation hashed")
	_check_terminal_metadata_present(entries)
	log.record("system_error", {"code":"SECRET_TOKEN", "phase":"SECRET_ACCOUNT"})
	check(not JSON.stringify(log.read_entries()).contains("SECRET"), "code-shaped secrets are not logged")
	var id: String = log.get_run_id()
	log.finish()
	log.finish()
	check(log.read_entries().size() == 123, "finish is idempotent")
	check(log.record("after_finish") != OK, "closed run immutable")
	var observer = Log.new(directory)
	check(observer.read_entries(id).size() == 123, "complete run recovered across instances")
	var zip_path := directory + "/diagnostic.zip"
	check(observer.export_run(id, zip_path) == OK, "export whole selected startup")
	var zip := ZIPReader.new()
	check(zip.open(zip_path) == OK, "export is valid ZIP")
	check(zip.get_files().size() == 3, "only diagnostic entries included")
	for name in zip.get_files():
		check(not zip.read_file(name).get_string_from_utf8().contains("SECRET"), "all ZIP entries sanitized")
	check(zip.read_file("events.jsonl").get_string_from_utf8().contains("client_started"), "export retains beginning")
	check(zip.read_file("readable.txt").get_string_from_utf8().contains("客户端启动"), "readable Chinese explanation")
	check(zip.read_file("environment.json").get_string_from_utf8().contains("counts_by_origin"), "export summarizes fault origins")
	zip.close()
	check(observer.export_run(id, zip_path) != OK, "export does not overwrite")
	observer.record("client_started")
	var active: String = observer.get_run_id()
	for index in range(53):
		var run = Log.new(directory)
		run.record("client_started")
		run.finish()
	var runs: Array = observer.list_runs()
	check(runs.size() == 50, "50 startup retention")
	check(not observer.read_entries(active).is_empty(), "another active instance protected")
	check(observer.read_entries(id).is_empty(), "old finished run evicted whole")
	check(observer.read_entries("../diagnostic").is_empty(), "path traversal rejected")
	observer.finish()
	var bad = Log.new(zip_path + "/impossible")
	check(bad.record("client_started") != OK, "write failure surfaced")
	check(bad.read_entries().size() == 1, "failed disk write retained for current viewer")
	var limited_directory := "user://log-limit-test-%s" % Time.get_ticks_usec()
	var limited = Log.new(limited_directory, 2048, null, 3)
	check(limited.record("client_started") == OK, "limited log accepts first entry")
	check(limited.record("reply_received", {"bytes":128}) == OK, "limited log accepts entries within count")
	check(limited.record("reply_received", {"bytes":128}) == OK, "limited log accepts final count")
	check(limited.record("reply_received", {"bytes":128}) != OK, "limited log rejects entries beyond count")
	check(limited.read_entries().size() == 3, "entry count cap bounds current run")
	var limited_file := limited_directory.path_join(limited.get_run_id() + ".jsonl")
	check(FileAccess.get_file_as_bytes(limited_file).size() <= 2048, "single-run byte cap bounds archive")
	var byte_directory := "user://log-byte-limit-test-%s" % Time.get_ticks_usec()
	var byte_limited = Log.new(byte_directory, 400, null, 100)
	check(byte_limited.record("client_started") == OK, "byte-limited log accepts first entry")
	check(byte_limited.record("reply_received", {"bytes":128}) != OK, "byte-limited log rejects oversized run")
	var byte_file := byte_directory.path_join(byte_limited.get_run_id() + ".jsonl")
	check(FileAccess.get_file_as_bytes(byte_file).size() <= 400, "byte limit bounds archive without partial line")
	var stale_metadata := limited_directory.path_join(limited.get_run_id() + ".json.tmp")
	var stale_file := FileAccess.open(stale_metadata, FileAccess.WRITE)
	stale_file.store_string("stale")
	stale_file.close()
	var reopened = Log.new(limited_directory, 2048, null, 3)
	check(reopened.record("client_started") == OK, "reopened log writes after stale metadata")
	check(not FileAccess.file_exists(stale_metadata), "stale metadata temporary file cleaned")
	reopened.finish()
	for file in DirAccess.get_files_at(directory):
		DirAccess.remove_absolute(directory.path_join(file))
		DirAccess.remove_absolute(directory)
	for file in DirAccess.get_files_at(limited_directory):
		DirAccess.remove_absolute(limited_directory.path_join(file))
	DirAccess.remove_absolute(limited_directory)
	for file in DirAccess.get_files_at(byte_directory):
		DirAccess.remove_absolute(byte_directory.path_join(file))
	DirAccess.remove_absolute(byte_directory)
	_check_categories()
	print("Client startup diagnostics: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
func _check_terminal_metadata_present(entries: Variant) -> void:
	check(entries[1].has_audio and entries[1].has("module") and entries[1].has("level"), "terminal metadata present")

func _check_no_truncation_of_launch_records(entries: Variant) -> void:
	check(entries.size() == 121 and entries[0].event == "client_started", "no truncation of launch records")

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
	_check_legacy(directory)
	log.finish()
	_cleanup_category_dirs(directory)

func _write_categories(log) -> void:
	check(log.log_error("error_system", {"code":"NETWORK_ERROR", "detail":"boom", "stack":["f@res://a.gd:1"]}) == OK, "error category writes")
	check(log.log_warning("warning_settings_save", {"code":"SETTINGS_SAVE_FAILED", "detail":"save"}) == OK, "warning category writes")
	check(log.log_info("info_message_queued", {"phase":"queued", "count":1}) == OK, "info category writes")
	check(log.log_debug("debug_state", {"data":{"state":"ready"}}) == OK, "debug category writes")
	check(log.log_access("access_http", {"channel":"http", "action":"request", "method":"GET", "route":"/history", "status":200, "outcome":"success", "duration_ms":3, "bytes":10}) == OK, "access category writes")
	check(log.log_security("security_auth", {"action":"login", "outcome":"success", "reason_code":"OK", "subject":"abc123"}) == OK, "security category writes")
	check(log.log_performance("performance_sample", {"operation":"resource_sample", "outcome":"success", "duration_ms":1, "fps":60}) == OK, "performance category writes")
	check(log.log_transaction("transaction_sqlite", {"transaction_id":"tx_abc123", "scope":"sqlite", "operation":"save_live", "phase":"committed", "outcome":"success", "duration_ms":4}) == OK, "transaction category writes")
	check(log.log_runtime("runtime_app_started", {"phase":"starting", "reason":"normal", "uptime_ms":0, "pid":1}) == OK, "runtime category writes")

func _check_category_entries(log) -> void:
	var entries: Array = log.read_entries()
	var categories := {}
	for entry in entries:
		categories[entry.category] = true
	check(categories.size() == 9, "nine category records present")
	for entry in entries:
		for key in {"error":["code","detail","stack"], "warning":["code","detail"], "info":["phase"], "debug":["data"], "access":["channel","action","route","outcome","duration_ms","trace_id"], "security":["action","outcome","reason_code","subject","trace_id"], "performance":["operation","outcome","duration_ms","trace_id"], "transaction":["transaction_id","scope","operation","phase","outcome","duration_ms","trace_id"], "runtime":["phase","reason","uptime_ms","pid"]}[entry.category]:
			check(entry.has(key), "required field " + entry.category + "." + key)

func _check_origins(directory: String) -> void:
	var log = Log.new(directory.path_join("origins"), 8 * 1024 * 1024, null, 100)
	check(log.log_error("error_system", {"code":"CACHE_WRITE_FAILED", "detail":"cache", "stack":[]}) == OK, "client error writes")
	check(log.log_error("error_system", {"code":"AUTH_REJECTED", "detail":"auth", "stack":[]}) == OK, "server error writes")
	check(log.log_error("error_system", {"code":"REMOTE_AUDIO_ERROR", "detail":"tts", "stack":[]}) == OK, "upstream error writes")
	check(log.log_access("access_http", {"channel":"http", "action":"request", "method":"GET", "route":"/auth/public_key",
		"status":0, "outcome":"failure", "duration_ms":1, "bytes":0}) == OK, "network access writes")
	check(log.log_access("access_http", {"channel":"http", "action":"request", "method":"GET", "route":"/history",
		"status":503, "outcome":"failure", "duration_ms":1, "bytes":0}) == OK, "server access writes")
	var origins: Array = log.read_entries().map(func(entry): return entry.origin)
	check(origins == ["client", "server", "upstream", "network", "server"], "origin inferred from code and HTTP status")
	var stats: Dictionary = log.get_stats()
	check(int(stats.by_origin.get("server", 0)) == 2 and int(stats.by_origin.get("network", 0)) == 1, "stats group by origin")
	log.finish()

func _check_missing_fields(directory: String) -> void:
	var missing_log = Log.new(directory.path_join("missing"), 8 * 1024 * 1024, null, 100)
	check(missing_log.log_access("access_http", {}) == OK, "missing fields still write")
	var missing_entry: Dictionary = missing_log.read_entries()[0]
	check(missing_entry.has("schema_missing") and missing_entry.has("trace_id") and missing_entry.route == "/unknown", "missing fields auto-filled")
	missing_log.finish()

func _check_debug_and_threadsafe(directory: String) -> void:
	var debug_off = Log.new(directory.path_join("off"), 8 * 1024 * 1024, null, 100)
	check(debug_off.log_debug("debug_state", {"data":{"a":1}}) == OK, "debug disabled returns ok")
	check(debug_off.read_entries().is_empty(), "debug disabled drops entry")
	check(debug_off.get_stats().dropped_debug == 1, "debug drop counted")
	debug_off.set_debug_enabled(true)
	check(debug_off.log_debug("debug_state", {"data":{"a":1}}) == OK and debug_off.read_entries().size() == 1, "debug enabled writes")
	debug_off.finish()
	var threaded = Log.new(directory.path_join("threaded"), 8 * 1024 * 1024, null, 100)
	threaded.record_threadsafe("info", "info_message_queued", {"phase":"queued"})
	check(threaded.get_pending_count() == 1 and threaded.drain() == 1, "thread safe queue drains")
	check(threaded.read_entries()[0].event == "info_message_queued", "thread safe event written")
	threaded.finish()

func _check_legacy(directory: String) -> void:
	var legacy_directory := directory.path_join("legacy")
	DirAccess.make_dir_recursive_absolute(legacy_directory)
	var legacy_id := "00000000000000000001_1_abcdef123456"
	var legacy_file := FileAccess.open(legacy_directory.path_join(legacy_id + ".jsonl"), FileAccess.WRITE)
	legacy_file.store_string(JSON.stringify({"time":"2026-01-01T00:00:00Z","event":"client_started","level":"INFO","module":"app"}) + "\n")
	legacy_file.close()
	var legacy = Log.new(legacy_directory)
	var legacy_entries: Array = legacy.read_entries(legacy_id)
	check(legacy_entries.size() == 1 and legacy_entries[0].category == "runtime" and legacy_entries[0].message == "客户端启动", "legacy archive alias readable")

func _cleanup_category_dirs(directory: String) -> void:
	for child in ["", "origins", "missing", "off", "threaded", "legacy"]:
		var path := directory if child.is_empty() else directory.path_join(child)
		if DirAccess.dir_exists_absolute(path):
			for file in DirAccess.get_files_at(path):
				DirAccess.remove_absolute(path.path_join(file))
			DirAccess.remove_absolute(path)
