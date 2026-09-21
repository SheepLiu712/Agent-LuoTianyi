extends SceneTree
const ServerAddress = preload("res://src/domain/server_address.gd")
const Api = preload("res://src/network/account_api.gd")
var failures: Array[String] = []
var _pending: Dictionary = {}

func check(ok: bool, message: String) -> void:
	if not ok:
		failures.append(message)
		print("FAIL: ", message)

func _initialize() -> void:
	call_deferred("run")

func start_slow(api, server: String) -> void:
	_pending = await api.request("login", server + "/slow", {"username":"test", "password":"synthetic-password"})

func start_slow_post(api, server: String) -> void:
	_pending = await api.request("auto_login", server + "/slowpost", {"username":"test", "token":"login-test"})

func run() -> void:
	var server := OS.get_environment("GODOT_TEST_SERVER")
	if server.is_empty() or not ClassDB.class_exists("WindowsSecurity"):
		print("ENVIRONMENT: local HTTP fixture and WindowsSecurity required")
		quit(2)
		return
	check(ServerAddress.normalize(" EXAMPLE.org:443/api/ ") == "https://example.org/api", "server canonicalization")
	check(ServerAddress.normalize("http://127.0.0.1:80") == "http://127.0.0.1", "default HTTP port removed")
	check(ServerAddress.normalize("https://[::1]:8443/") == "https://[::1]:8443", "IPv6 supported")
	for invalid in ["", "ftp://host", "https://user:pass@host", "https://host?token=x", "https://host:99999", "https://host/a b", "https://999.1.1.1", "https://1.2.3.999", "https://1.2.3.4.5"]:
		check(ServerAddress.normalize(invalid).is_empty(), "unsafe address rejected")
	var api = Api.new(ClassDB.instantiate("WindowsSecurity"), 0.15)
	root.add_child(api)
	var login: Dictionary = await api.request("login", server, {"username":"test", "password":"synthetic-password", "request_token":true, "ignored":"field"})
	check(login.ok and login.data.get("message_token") == "message-test", "encrypted password login succeeds")
	var registered: Dictionary = await api.request("register", server, {"username":"test", "password":"synthetic-password", "invite_code":"invite-test"})
	check(registered.ok, "registration fields accepted")
	var reset: Dictionary = await api.request("reset", server, {"new_username":"test", "new_password":"synthetic-password", "invite_code":"invite-test"})
	check(reset.ok, "account reset fields accepted")
	var automatic: Dictionary = await api.request("auto_login", server, {"username":"test", "token":"login-test"})
	check(automatic.ok, "auto login uses login token")
	for pair in [["reject", "AUTH_REJECTED"], ["empty_token", "INVALID_RESPONSE"], ["busy", "HTTP_ERROR"]]:
		var response: Dictionary = await api.request("login", server, {"username":pair[0], "password":"synthetic-password"})
		check(response.code == pair[1], "failure classification: " + pair[0])
	for pair in [["/badkey", "ENCRYPTION_ERROR"], ["/badjson", "PUBLIC_KEY_ERROR"], ["/redirect", "PUBLIC_KEY_ERROR"], ["/slow", "TIMEOUT"]]:
		var response: Dictionary = await api.request("login", server + pair[0], {"username":"test", "password":"synthetic-password"})
		check(response.code == pair[1], "public key failure: " + pair[0])
	start_slow(api, server)
	await create_timer(0.02).timeout
	var parallel: Dictionary = await api.request("login", server, {"username":"test", "password":"synthetic-password"})
	check(parallel.code == "BUSY", "concurrent account operation refused")
	api.cancel()
	api.cancel()
	await process_frame
	check(_pending.get("code") == "CANCELLED", "cancel resolves pending operation")
	var recovered: Dictionary = await api.request("login", server, {"username":"test", "password":"synthetic-password"})
	check(recovered.ok, "new request after cancel uses current server")
	_pending = {}
	start_slow_post(api, server)
	await create_timer(0.03).timeout
	api.cancel()
	await create_timer(0.6).timeout
	check(_pending.get("code") == "CANCELLED", "late POST success cannot restore cancelled session")
	api.queue_free()
	await process_frame
	print("Account API: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
