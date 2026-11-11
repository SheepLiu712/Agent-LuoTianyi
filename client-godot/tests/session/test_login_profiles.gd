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
	_check_both_options_default_off(session)
	var result: Dictionary = await session.perform("login", server, {"username":"alice","password":"synthetic-password"}, true, false)
	_check_successful_login_enters_server_scoped_history(result, session)
	_check_remember_and_automatic_are_independent(session)
	session.queue_free()
	await process_frame
	session = fresh(storage, security)
	await _check_remember_alone_does_not_log_in_on_startup(session)
	check((await session.login_saved("alice")).ok, "remembered account accepts explicit token login")
	check(storage.read_login_token(server, "alice").token == "login-rotated", "manual token login persists rotation")
	check(session.logout() == OK, "logout completes")
	_check_logout_clears_token_but_preserves_history(storage, server, session)
	await session.perform("login", server, {"username":"alice","password":"synthetic-password"}, true, true)
	session.queue_free()
	await process_frame
	session = fresh(storage, security)
	check((await session.resume()).ok, "automatic login runs when both options are enabled")
	session.queue_free()
	await process_frame
	session = fresh(storage, security)
	await session.perform("login", server, {"username":"bob","password":"synthetic-password"}, true, false)
	_check_most_recent_successful_account_comes_first(session)
	session.logout()
	_check_logout_does_not_clear_another_account(storage, server)
	_check_history_selection_does_not_log_in(session)
	check(session.set_login_options("alice", false, false).ok, "remember can be disabled immediately")
	_check_disabling_remember_clears_credential_and_automatic_option(storage, server, session)
	await _check_invalid_public_key_response_preserves_server(session, server)
	pending = {}
	change_server(session, server + "/slow")
	await create_timer(.03).timeout
	session.cancel()
	await create_timer(.6).timeout
	_check_cancelled_probe_cannot_switch_servers_later(session, server)
	check((await session.set_server(server + "/alternate")).ok, "validated server is saved")
	_check_new_server_never_carries_old_account_selection(session)
	await session.perform("login", server + "/alternate", {"username":"alice","password":"synthetic-password"}, true, false)
	session.queue_free()
	await process_frame
	session = fresh(storage, security)
	_check_same_name_on_different_servers_remains_isolated(session, server)
	check(session.remove_account("alice").ok and session.get_history().is_empty(), "remove local record and credential")
	check(session.get_history(server).size() == 2, "remove leaves other server intact")
	await session.set_server(server)
	await session.perform("login", server, {"username":"alice","password":"synthetic-password"}, true, true)
	session.queue_free()
	await process_frame
	storage.save_login_token(server, "alice", "invalid")
	session = fresh(storage, security)
	check((await session.resume()).code == "AUTH_REJECTED", "expired token is rejected")
	_check_expired_credential_falls_back_to_password(session, storage, server)
	session.queue_free()
	await process_frame
	storage.write_login_profile({"version":2,"server":server,"username":"busy","accounts":[{"server":server,"username":"busy","remember":true,"auto_login":true,"last_used":1}]})
	storage.save_login_token(server, "busy", "login-test")
	session = fresh(storage, security)
	await _check_temporary_service_failure_preserves_remembered_login(session, storage, server)
	FileAccess.set_read_only_attribute(path + "/account.cfg", true)
	result = await session.set_server(server + "/alternate")
	_check_local_save_failure_preserves_the_previous_server(result, session, server)
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

func _check_expired_credential_falls_back_to_password(session: Variant, storage: Variant, server: Variant) -> void:
	check(not session.get_login_defaults().remember and not session.get_login_defaults().auto_login and not storage.read_login_token(server, "alice").ok, "expired credential falls back to password")

func _check_temporary_service_failure_preserves_remembered_login(session: Variant, storage: Variant, server: Variant) -> void:
	check((await session.resume()).code == "HTTP_ERROR" and storage.read_login_token(server, "busy").ok and session.get_login_defaults().remember, "temporary service failure preserves remembered login")

func _check_local_save_failure_preserves_the_previous_server(result: Variant, session: Variant, server: Variant) -> void:
	check(not result.ok and result.storage_error and session.get_login_defaults().server == server, "local save failure preserves the previous server")

func _check_both_options_default_off(session: Variant) -> void:
	check(not session.get_login_defaults().remember and not session.get_login_defaults().auto_login, "both options default off")

func _check_successful_login_enters_server_scoped_history(result: Variant, session: Variant) -> void:
	check(result.ok and session.get_history().size() == 1, "successful login enters server-scoped history")

func _check_remember_and_automatic_are_independent(session: Variant) -> void:
	check(session.get_login_defaults().remember and not session.get_login_defaults().auto_login, "remember and automatic are independent")

func _check_remember_alone_does_not_log_in_on_startup(session: Variant) -> void:
	check((await session.resume()).code == "NO_SAVED_LOGIN" and session.get_session().is_empty(), "remember alone does not log in on startup")

func _check_logout_clears_token_but_preserves_history(storage: Variant, server: Variant, session: Variant) -> void:
	check(not storage.read_login_token(server, "alice").ok and session.get_history().size() == 1, "logout clears token but preserves history")

func _check_most_recent_successful_account_comes_first(session: Variant) -> void:
	check(session.get_history()[0].username == "bob" and session.get_history().size() == 2, "most recent successful account comes first")

func _check_logout_does_not_clear_another_account(storage: Variant, server: Variant) -> void:
	check(storage.read_login_token(server, "alice").ok and not storage.read_login_token(server, "bob").ok, "logout does not clear another account")

func _check_history_selection_does_not_log_in(session: Variant) -> void:
	check(session.select_account("alice").ok and session.get_session().is_empty(), "history selection does not log in")

func _check_disabling_remember_clears_credential_and_automatic_option(storage: Variant, server: Variant, session: Variant) -> void:
	check(not storage.read_login_token(server, "alice").ok and not session.get_login_defaults().auto_login, "disabling remember clears credential and automatic option")

func _check_invalid_public_key_response_preserves_server(session: Variant, server: Variant) -> void:
	check((await session.set_server(server + "/badjson")).ok == false and session.get_login_defaults().server == server, "invalid public key response preserves server")

func _check_cancelled_probe_cannot_switch_servers_later(session: Variant, server: Variant) -> void:
	check(pending.get("code") == "CANCELLED" and session.get_login_defaults().server == server, "cancelled probe cannot switch servers later")

func _check_new_server_never_carries_old_account_selection(session: Variant) -> void:
	check(session.get_history().is_empty() and session.get_login_defaults().username.is_empty(), "new server never carries old account selection")

func _check_same_name_on_different_servers_remains_isolated(session: Variant, server: Variant) -> void:
	check(session.get_history(server).size() == 2 and session.get_history().size() == 1, "same name on different servers remains isolated")
