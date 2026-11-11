extends SceneTree
const Transport = preload("res://src/network/websocket_transport.gd")
const Events = preload("res://src/storage/log_events.gd")
const CredentialStore = preload("res://src/storage/credential_store.gd")
var failures: Array[String] = []

class FakeLogger:
	extends RefCounted
	var access: Array = []
	var security: Array = []
	var performance: Array = []
	var transactions: Array = []
	var debug: Array = []
	func log_access(event: String, fields: Dictionary) -> Error:
		access.append({"event":event, "fields":fields})
		return OK
	func log_security(event: String, fields: Dictionary) -> Error:
		security.append({"event":event, "fields":fields})
		return OK
	func log_performance(event: String, fields: Dictionary) -> Error:
		performance.append({"event":event, "fields":fields})
		return OK
	func log_transaction(event: String, fields: Dictionary) -> Error:
		transactions.append({"event":event, "fields":fields})
		return OK
	func log_debug(event: String, fields: Dictionary) -> Error:
		debug.append({"event":event, "fields":fields})
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
	var directory := _check_credentials(logger)
	_cleanup(directory)
	print("Log integration: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func _check_transport(logger: FakeLogger) -> void:
	var transport = Transport.new(Callable(), logger)
	transport._connect_trace = "ws_abcdef123456"
	transport._log_ws("send", "hb_ping", "success", 4, 12)
	check(logger.access.size() == 1 and logger.access[0].event == "access_ws", "ws access logged")
	check(logger.access[0].fields.channel == "ws" and logger.access[0].fields.route == "/chat_ws", "ws access fields")
	transport._audio_frames = 2
	transport._audio_bytes = 100
	transport._audio_started = Time.get_ticks_msec() - 1000
	transport._flush_audio_access()
	check(logger.performance.size() == 1 and logger.performance[0].event == "performance_ws_audio", "ws audio aggregate")
	transport._session = {"server":"https://example.com", "username":"alice"}
	transport._fingerprint = "fp"
	transport._reject_auth("AUTH_REJECTED")
	check(logger.security.size() == 1 and logger.security[0].event == "security_ws_auth", "ws auth security")
	check(not JSON.stringify(logger.security).contains("alice"), "ws security subject hashed")
	transport.free()

func _check_http(logger: FakeLogger) -> void:
	Events.http(logger, {"ok":false, "code":"HTTP_ERROR"}, 500, 12, Time.get_ticks_usec() - 5000, "req_abcdef123456", "/history", "GET")
	check(logger.access.size() == 2 and logger.access[1].fields.outcome == "failure", "http failure access")
	check(logger.access[1].fields.status == 500 and logger.access[1].fields.route == "/history", "http access fields")

func _check_credentials(logger: FakeLogger) -> String:
	var directory := "user://log-credential-%s" % Time.get_ticks_usec()
	var store = CredentialStore.new(FakeSecurity.new(), directory, logger)
	check(store.save("https://example.com", "alice", "session-token") == OK, "credential save")
	check(store.read("https://example.com", "alice").get("token") == "session-token", "credential read")
	check(store.forget("https://example.com", "alice") == OK, "credential forget")
	check(logger.security.size() == 4, "credential security events")
	check(not JSON.stringify(logger.security).contains("session-token"), "credential token excluded")
	return directory

func _cleanup(directory: String) -> void:
	if DirAccess.dir_exists_absolute(directory):
		for file in DirAccess.get_files_at(directory):
			DirAccess.remove_absolute(directory.path_join(file))
		DirAccess.remove_absolute(directory)
