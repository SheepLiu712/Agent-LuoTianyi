extends SceneTree
const Session = preload("res://src/session/account_session.gd")
const Api = preload("res://src/network/account_api.gd")
const Storage = preload("res://src/storage/godot_storage_service.gd")
const Tokens = preload("res://src/storage/credential_store.gd")
var failures: Array[String] = []
var pending: Dictionary = {}

func _initialize() -> void: run.call_deferred()
func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)
func change_server(session: Node, address: String) -> void:
	pending = await session.set_server(address)
func fresh(storage: RefCounted, security: Object) -> Node:
	var session = Session.new(Api.new(security, 2), storage)
	root.add_child(session)
	return session

func run() -> void:
	var script: Script = load("res://src/session/account_session.gd")
	var methods := script.get_script_method_list().map(func(method): return method.name)
	for name in ["get_history", "select_account", "remove_account", "set_login_options", "login_saved", "set_server"]:
		check(name in methods, "account exposes " + name)
	if not failures.is_empty():
		quit(1)
		return
	var path := "user://login-profiles-%s" % Time.get_ticks_usec()
	var server := OS.get_environment("GODOT_TEST_SERVER")
	var security = ClassDB.instantiate("WindowsSecurity")
	var storage = Storage.new(path + "/account.cfg", Tokens.new(security, path + "/tokens"))
	var session := fresh(storage, security)
	check(not session.get_login_defaults().remember and not session.get_login_defaults().auto_login, "both options default off")
	var result: Dictionary = await session.perform("login", server, {"username":"alice","password":"synthetic-password"}, true, false)
	check(result.ok and session.get_history().size() == 1, "successful login enters server-scoped history")
	check(session.get_login_defaults().remember and not session.get_login_defaults().auto_login, "remember and automatic are independent")
	session.queue_free()
	await process_frame
	session = fresh(storage, security)
	check((await session.resume()).code == "NO_SAVED_LOGIN" and session.get_session().is_empty(), "remember alone does not log in on startup")
	check((await session.login_saved("alice")).ok, "remembered account accepts explicit token login")
	check(storage.read_login_token(server, "alice").token == "login-rotated", "manual token login persists rotation")
	check(session.logout() == OK, "logout completes")
	check(not storage.read_login_token(server, "alice").ok and session.get_history().size() == 1, "logout clears token but preserves history")
	await session.perform("login", server, {"username":"alice","password":"synthetic-password"}, true, true)
	session.queue_free()
	await process_frame
	session = fresh(storage, security)
	check((await session.resume()).ok, "automatic login runs when both options are enabled")
	session.queue_free()
	await process_frame
	session = fresh(storage, security)
	await session.perform("login", server, {"username":"bob","password":"synthetic-password"}, true, false)
	check(session.get_history()[0].username == "bob" and session.get_history().size() == 2, "most recent successful account comes first")
	session.logout()
	check(storage.read_login_token(server, "alice").ok and not storage.read_login_token(server, "bob").ok, "logout does not clear another account")
	check(session.select_account("alice").ok and session.get_session().is_empty(), "history selection does not log in")
	check(session.set_login_options("alice", false, false).ok, "remember can be disabled immediately")
	check(not storage.read_login_token(server, "alice").ok and not session.get_login_defaults().auto_login, "disabling remember clears credential and automatic option")
	check((await session.set_server(server + "/badjson")).ok == false and session.get_login_defaults().server == server, "invalid public key response preserves server")
	pending = {}
	change_server(session, server + "/slow")
	await create_timer(.03).timeout
	session.cancel()
	await create_timer(.6).timeout
	check(pending.get("code") == "CANCELLED" and session.get_login_defaults().server == server, "cancelled probe cannot switch servers later")
	check((await session.set_server(server + "/alternate")).ok, "validated server is saved")
	check(session.get_history().is_empty() and session.get_login_defaults().username.is_empty(), "new server never carries old account selection")
	await session.perform("login", server + "/alternate", {"username":"alice","password":"synthetic-password"}, true, false)
	session.queue_free()
	await process_frame
	session = fresh(storage, security)
	check(session.get_history(server).size() == 2 and session.get_history().size() == 1, "same name on different servers remains isolated")
	check(session.remove_account("alice").ok and session.get_history().is_empty(), "remove local record and credential")
	check(session.get_history(server).size() == 2, "remove leaves other server intact")
	await session.set_server(server)
	await session.perform("login", server, {"username":"alice","password":"synthetic-password"}, true, true)
	session.queue_free()
	await process_frame
	storage.save_login_token(server, "alice", "invalid")
	session = fresh(storage, security)
	check((await session.resume()).code == "AUTH_REJECTED", "expired token is rejected")
	check(not session.get_login_defaults().remember and not session.get_login_defaults().auto_login and not storage.read_login_token(server, "alice").ok, "expired credential falls back to password")
	session.queue_free()
	await process_frame
	storage.write_login_profile({"version":2,"server":server,"username":"busy","accounts":[{"server":server,"username":"busy","remember":true,"auto_login":true,"last_used":1}]})
	storage.save_login_token(server, "busy", "login-test")
	session = fresh(storage, security)
	check((await session.resume()).code == "HTTP_ERROR" and storage.read_login_token(server, "busy").ok and session.get_login_defaults().remember, "temporary service failure preserves remembered login")
	FileAccess.set_read_only_attribute(path + "/account.cfg", true)
	result = await session.set_server(server + "/alternate")
	check(not result.ok and result.storage_error and session.get_login_defaults().server == server, "local save failure preserves the previous server")
	FileAccess.set_read_only_attribute(path + "/account.cfg", false)
	storage.forget_login_token(server, "busy")
	check((await session.login_saved("busy")).code == "CREDENTIAL_UNAVAILABLE" and not session.get_login_defaults().remember, "unavailable credential returns to password mode")
	session.queue_free()
	await process_frame
	# Migrate the existing single-account config without changing its credential key.
	var legacy = Storage.new(path + "/legacy.cfg", Tokens.new(security, path + "/legacy-tokens"))
	legacy.write_login_profile({"server":server,"username":"test","remember":true})
	legacy.save_login_token(server, "test", "login-test")
	session = fresh(legacy, security)
	check(session.get_login_defaults().remember and session.get_login_defaults().auto_login, "legacy remember migrates to both flags")
	check(int(legacy.read_login_profile().data.version) == 2 and (await session.resume()).ok, "legacy token remains usable")
	session.queue_free()
	await process_frame
	legacy.write_login_profile({"server":server,"username":"test","remember":true})
	var original := FileAccess.get_file_as_string(path + "/legacy.cfg")
	FileAccess.set_read_only_attribute(path + "/legacy.cfg", true)
	session = fresh(legacy, security)
	check(session.get_login_defaults().storage_error, "failed migration is visible")
	check(FileAccess.get_file_as_string(path + "/legacy.cfg") == original, "failed migration does not replace old config")
	FileAccess.set_read_only_attribute(path + "/legacy.cfg", false)
	session.queue_free()
	await process_frame
	check(not FileAccess.get_file_as_string(path + "/account.cfg").contains("synthetic-password") and not FileAccess.get_file_as_string(path + "/account.cfg").contains("login-test"), "profile contains no password or token")
	remove_folder(path)
	print("Login profiles: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func remove_folder(path: String) -> void:
	for folder in DirAccess.get_directories_at(path): remove_folder(path.path_join(folder))
	for file in DirAccess.get_files_at(path): DirAccess.remove_absolute(path.path_join(file))
	DirAccess.remove_absolute(path)
