extends SceneTree
const Store = preload("res://src/storage/credential_store.gd")
const Session = preload("res://src/session/account_session.gd")
const Api = preload("res://src/network/account_api.gd")
var failures: Array[String] = []

func check(ok: bool, description: String) -> void:
	if not ok:
		failures.append(description)
		print("FAIL: ", description)

func _initialize() -> void:
	call_deferred("run")

func run() -> void:
	var server := OS.get_environment("GODOT_TEST_SERVER")
	if server.is_empty():
		quit(2)
		return
	var folder := "user://session-test-%s" % Time.get_ticks_usec()
	DirAccess.make_dir_recursive_absolute(folder)
	var security = ClassDB.instantiate("WindowsSecurity")
	var store = Store.new(security, folder + "/tokens")
	check(store.save(server, "test", "login-test") == OK, "protected token saved")
	check(store.read(server, "test").get("token") == "login-test", "token restores")
	check(not store.read(server + "/other", "test").ok, "server isolation")
	check(not store.read(server, "other").ok, "account isolation")
	var session = Session.new(Api.new(security), load("res://src/storage/godot_storage_service.gd").new(folder + "/account.cfg", store))
	root.add_child(session)
	var outcome: Dictionary = await session.perform("login", server, {"username":"test", "password":"synthetic-password"}, true, true)
	check(outcome.ok and not session.get_session().is_empty(), "successful login publishes session")
	check(session.get_login_defaults().remember, "auto login enabled only after save")
	check(not FileAccess.get_file_as_string(folder + "/account.cfg").contains("login-test"), "ordinary settings contain no login token")
	var snapshot: Dictionary = session.get_session()
	snapshot["message_token"] = "changed"
	check(session.get_session().get("message_token") == "message-test", "session snapshot isolated")
	session.queue_free()
	await process_frame
	var restored = Session.new(Api.new(security), load("res://src/storage/godot_storage_service.gd").new(folder + "/account.cfg", Store.new(security, folder + "/tokens")))
	root.add_child(restored)
	var resumed: Dictionary = await restored.resume()
	check(resumed.ok, "new process session resumes protected login")
	check(store.read(server, "test").get("token") == "login-rotated", "rotated login token persisted")
	check(restored.logout() == OK, "logout succeeds")
	check(restored.get_session().is_empty(), "logout clears memory")
	check(not store.read(server, "test").ok, "logout deletes credential")
	check(not restored.get_login_defaults().remember, "logout disables auto login")
	await restored.perform("login", server, {"username":"test", "password":"synthetic-password"}, true, true)
	store.save(server, "test", "invalid")
	restored.queue_free()
	await process_frame
	var rejected = Session.new(Api.new(security), load("res://src/storage/godot_storage_service.gd").new(folder + "/account.cfg", store))
	root.add_child(rejected)
	var rejection: Dictionary = await rejected.resume()
	check(rejection.code == "AUTH_REJECTED", "expired token rejected")
	check(not store.read(server, "test").ok and not rejected.get_login_defaults().remember, "401 clears saved automatic login")
	rejected.queue_free()
	var blocked := FileAccess.open(folder + "/blocked", FileAccess.WRITE)
	blocked.store_string("file prevents directory creation")
	blocked.close()
	var unsaved = Session.new(Api.new(security), load("res://src/storage/godot_storage_service.gd").new(folder + "/unsaved.cfg", Store.new(security, folder + "/blocked")))
	root.add_child(unsaved)
	var failure: Dictionary = await unsaved.perform("login", server, {"username":"test", "password":"synthetic-password"}, true, true)
	check(failure.ok and failure.storage_error, "storage failure keeps online login with explicit warning")
	check(not unsaved.get_login_defaults().remember, "storage failure disables auto login")
	unsaved.logout()
	unsaved.queue_free()
	await process_frame
	for filename in ["account.cfg", "unsaved.cfg", "blocked"]:
		DirAccess.remove_absolute(folder + "/" + filename)
	DirAccess.remove_absolute(folder + "/tokens")
	DirAccess.remove_absolute(folder)
	print("Account session: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
