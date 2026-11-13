extends SceneTree
const Transport = preload("res://src/network/websocket_transport.gd")
const Events = preload("res://src/storage/log_events.gd")
const CredentialStore = preload("res://src/storage/credential_store.gd")
const EngineSink = preload("res://src/storage/engine_log_sink.gd")
const HistoryApi = preload("res://src/network/history_api.gd")
const AvatarStore = preload("res://src/storage/avatar_store.gd")
const AvatarProfile = preload("res://src/session/avatar_profile.gd")
var failures: Array[String] = []

class FakeLogger:
	extends RefCounted
	var entries: Array = []
	func record_as(category: String, event: String, fields: Dictionary) -> Error:
		entries.append({"category":category, "event":event, "fields":fields})
		return OK

class FakeSecurity:
	extends RefCounted
	func protect_secret(_data: PackedByteArray, _scope: PackedByteArray) -> Dictionary:
		return {"ok":true, "data":PackedByteArray([1, 2, 3])}
	func unprotect_secret(_data: PackedByteArray, _scope: PackedByteArray) -> Dictionary:
		return {"ok":true, "data":"session-token".to_utf8_buffer()}

func check(value: bool, description: String) -> void:
	if not value:
		failures.append(description)
		print("FAIL: ", description)

func _initialize() -> void:
	var logger := FakeLogger.new()
	_check_transport(logger)
	_check_http(logger)
	_check_detail_mapping(logger)
	_check_history_api()
	_check_avatar_logging(logger)
	_check_engine_throttle(logger)
	var directory := _check_credentials(logger)
	_check_credential_failure(logger)
	_cleanup(directory)
	print("Log integration: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func _check_transport(logger: FakeLogger) -> void:
	var transport = Transport.new(Callable(), logger)
	transport._connect_trace = "ws_abcdef123456"
	transport._log_ws("send", "hb_ping", "success", 4, 12)
	var ws_access := _find(logger, "network_ws")
	check(not ws_access.is_empty() and ws_access.category == "network", "ws access logged")
	check(ws_access.fields.channel == "ws" and ws_access.fields.route == "/chat_ws", "ws access fields")
	transport._audio_frames = 2
	transport._audio_bytes = 100
	transport._audio_started = Time.get_ticks_msec() - 1000
	transport._flush_audio_access()
	check(not _find(logger, "network_ws_audio_summary").is_empty(), "ws audio aggregate")
	transport._session = {"server":"https://example.com", "username":"alice"}
	transport._fingerprint = "fp"
	transport._reject_auth("AUTH_REJECTED")
	var auth := _find(logger, "network_ws_auth")
	check(not auth.is_empty() and auth.category == "network", "ws auth security")
	check(not JSON.stringify(auth).contains("alice"), "ws security subject hashed")
	transport.free()

func _check_http(logger: FakeLogger) -> void:
	Events.http(logger, {"ok":false, "code":"HTTP_ERROR", "detail":"server exploded"}, 500, 12, Time.get_ticks_usec() - 5000, "req_abcdef123456", "/history", "GET")
	var http := _find(logger, "network_http")
	check(not http.is_empty() and http.fields.outcome == "failure", "http failure access")
	check(http.fields.status == 500 and http.fields.route == "/history", "http access fields")
	check(http.fields.detail == "server exploded", "http error detail carried")

func _check_detail_mapping(logger: FakeLogger) -> void:
	var json_body := '{"detail":"server exploded"}'.to_utf8_buffer()
	check(Events.http_failure_detail(json_body, 500) == "server exploded", "server detail extracted")
	var structured := '{"detail":{"field":"secret"}}'.to_utf8_buffer()
	check(Events.http_failure_detail(structured, 500) == "HTTP status 500", "structured validation detail is not echoed")
	check(Events.http_failure_detail(PackedByteArray(), 502) == "HTTP status 502", "status fallback detail")
	check(Events.http_result_name(HTTPRequest.RESULT_CANT_CONNECT) == "RESULT_CANT_CONNECT", "transport enum preserved")
	check(not Events.request_error_detail(ERR_FILE_NOT_FOUND).is_empty(), "request error string preserved")
	Events.ws(logger, "ws_abcdef123456", "close", "CONNECTION_LOST", "failure", 1000, 0, "CONNECTION_LOST",
		"close code 1006; reason: peer vanished")
	var ws_entries: Array = logger.entries.filter(func(entry): return entry.event == "network_ws")
	check(ws_entries[-1].fields.detail.contains("close code 1006"), "ws close reason carried")
	Events.security_auth(logger, "login", "failure", "AUTH_REJECTED", "https://example.com", "alice",
		"invalid credentials")
	var auth := _find(logger, "account_auth")
	check(auth.fields.detail == "invalid credentials", "security failure detail carried")

func _check_history_api() -> void:
	var api = HistoryApi.new()
	var transport: Dictionary = api._transport_failure(HTTPRequest.RESULT_CANT_CONNECT, 0)
	check(transport.code == "NETWORK_ERROR" and transport.detail.contains("RESULT_CANT_CONNECT"),
		"history transport failure keeps enum")
	var server: Dictionary = api._http_failure(500, '{"detail":"history exploded"}'.to_utf8_buffer())
	check(server.code == "HTTP_ERROR" and server.detail == "history exploded", "history server detail carried")
	var empty: Dictionary = api._http_failure(503, PackedByteArray())
	check(empty.detail == "HTTP status 503", "history empty body falls back to status")
	var rejected: Dictionary = api._response(HTTPRequest.RESULT_SUCCESS, 403, '{"message":"token expired"}'.to_utf8_buffer())
	check(rejected.code == "AUTH_REJECTED" and rejected.detail == "token expired", "history auth detail carried")
	api.free()

func _check_avatar_logging(logger: FakeLogger) -> void:
	var root := "user://log-avatar-%s" % Time.get_ticks_usec()
	var store = AvatarStore.new(root, logger)
	store.set_scope("https://example.com", "alice")
	var profile = AvatarProfile.new(store, logger)
	var before := logger.entries.size()
	profile.apply_bytes(PackedByteArray())
	var failures: Array = logger.entries.slice(before).filter(func(entry): return entry.event == "storage_avatar_save_failed")
	check(failures.size() == 1 and not failures[0].fields.detail.is_empty(), "avatar save failure logged once with detail")
	before = logger.entries.size()
	profile.apply_file(root.path_join("missing.png"))
	var reads: Array = logger.entries.slice(before).filter(func(entry): return entry.event == "avatar_applied")
	check(reads.size() == 1 and reads[0].fields.code == "IMAGE_READ_FAILED", "avatar read failure logged by profile")
	var image := Image.create(32, 32, false, Image.FORMAT_RGBA8)
	image.fill(Color(0.4, 0.8, 1, 1))
	before = logger.entries.size()
	check(profile.apply_bytes(image.save_png_to_buffer()).ok, "valid avatar applies")
	var applied: Array = logger.entries.slice(before).filter(func(entry): return entry.event == "avatar_applied")
	check(applied.size() == 1 and applied[0].fields.code == "OK", "avatar success logged once")
	profile.free()
	_remove_tree(root)

func _find(logger: FakeLogger, event: String) -> Dictionary:
	for entry in logger.entries:
		if entry.event == event:
			return entry
	return {}

func _check_engine_throttle(logger: FakeLogger) -> void:
	var sink = EngineSink.new(logger)
	var before := logger.entries.size()
	var now := Time.get_ticks_msec()
	sink._save("f", "res://a.gd", 10, "SCRIPT ERROR", "boom", 2, [])
	sink._save("f", "res://a.gd", 10, "SCRIPT ERROR", "boom", 2, [])
	sink._save("f", "res://a.gd", 10, "SCRIPT ERROR", "boom", 2, [])
	check(logger.entries.size() - before == 1, "engine errors are throttled within the window")
	sink.flush(now + 2000)
	var repeated: Array = logger.entries.filter(func(entry): return entry.event == "engine_error_repeated")
	check(repeated.size() == 1 and repeated[0].fields.count == 2, "engine suppression summary flushes once")

func _check_credentials(logger: FakeLogger) -> String:
	var directory := "user://log-credential-%s" % Time.get_ticks_usec()
	var store = CredentialStore.new(FakeSecurity.new(), directory, logger)
	var before := logger.entries.size()
	check(store.save("https://example.com", "alice", "session-token") == OK, "credential save")
	check(store.read("https://example.com", "alice").get("token") == "session-token", "credential read")
	check(store.forget("https://example.com", "alice") == OK, "credential forget")
	check(logger.entries.size() - before == 4, "credential storage events")
	check(not JSON.stringify(logger.entries.slice(before)).contains("session-token"), "credential token excluded")
	return directory

func _check_credential_failure(logger: FakeLogger) -> void:
	var root := "user://log-credential-fail-%s" % Time.get_ticks_usec()
	var file := FileAccess.open(root, FileAccess.WRITE)
	file.store_string("blocks directory creation")
	file.close()
	var store = CredentialStore.new(FakeSecurity.new(), root, logger)
	check(store.save("https://example.com", "alice", "session-token") != OK, "credential failure surfaced")
	var writes: Array = logger.entries.filter(func(entry): return entry.event == "storage_file_write")
	check(writes[-1].fields.outcome == "failure" and not writes[-1].fields.detail.is_empty(),
		"credential transaction keeps OS error detail")
	DirAccess.remove_absolute(ProjectSettings.globalize_path(root))

func _cleanup(directory: String) -> void:
	if DirAccess.dir_exists_absolute(directory):
		for file in DirAccess.get_files_at(directory):
			DirAccess.remove_absolute(directory.path_join(file))
		DirAccess.remove_absolute(directory)

func _remove_tree(directory: String) -> void:
	if not DirAccess.dir_exists_absolute(directory):
		return
	for child in DirAccess.get_directories_at(directory):
		_remove_tree(directory.path_join(child))
	for file in DirAccess.get_files_at(directory):
		DirAccess.remove_absolute(directory.path_join(file))
	DirAccess.remove_absolute(directory)
