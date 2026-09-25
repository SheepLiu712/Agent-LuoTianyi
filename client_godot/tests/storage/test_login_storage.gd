extends SceneTree
var failures: Array[String] = []

func _initialize() -> void: run.call_deferred()
func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)

func run() -> void:
	var service = load("res://src/storage/godot_storage_service.gd").new()
	for method in ["read_login_profile", "write_login_profile", "read_login_token", "save_login_token", "forget_login_token"]:
		check(service.has_method(method), "storage exposes " + method)
	if not failures.is_empty():
		quit(1)
		return
	var path := "user://login-storage-%s" % Time.get_ticks_usec()
	var credentials = load("res://src/storage/credential_store.gd").new(ClassDB.instantiate("WindowsSecurity"), path + "/tokens")
	service = load("res://src/storage/godot_storage_service.gd").new(path + "/account.cfg", credentials)
	var empty: Dictionary = service.read_login_profile()
	check(empty.ok and empty.data.is_empty(), "missing profile is a fresh install")
	var profile := {"version":2,"server":"https://example.test","username":"alice","accounts":[]}
	check(service.write_login_profile(profile) == OK, "profile writes atomically")
	var restored: Dictionary = service.read_login_profile().data
	check(int(restored.get("version", 0)) == 2 and restored.get("server") == profile.server and restored.get("username") == "alice" and restored.get("accounts") == [], "profile round trip")
	check(service.save_login_token(profile.server, "alice", "PRIVATE_TOKEN") == OK, "protected credential saves")
	check(service.save_login_token(profile.server, "bob", "OTHER_TOKEN") == OK, "other account saves independently")
	check(service.read_login_token(profile.server, "alice").token == "PRIVATE_TOKEN", "protected credential restores")
	check(not service.read_login_token("https://another.test", "alice").ok, "server scope isolates credentials")
	check(not FileAccess.get_file_as_string(path + "/account.cfg").contains("TOKEN"), "profile contains no credential")
	for file in DirAccess.get_files_at(path + "/tokens"):
		check(not FileAccess.get_file_as_bytes(path + "/tokens/" + file).hex_encode().contains("PRIVATE_TOKEN".to_utf8_buffer().hex_encode()), "credential is not plaintext")
	check(service.forget_login_token(profile.server, "alice") == OK and not service.read_login_token(profile.server, "alice").ok, "forget clears just selected account")
	check(service.read_login_token(profile.server, "bob").ok, "forget preserves other account")
	var file := FileAccess.open(path + "/account.cfg", FileAccess.WRITE)
	file.store_string("{broken")
	file.close()
	check(not service.read_login_profile().ok, "corrupt profile is not treated as a fresh install")
	check(FileAccess.get_file_as_string(path + "/account.cfg") == "{broken", "read failure leaves original data intact")
	file = FileAccess.open(path + "/blocked", FileAccess.WRITE)
	file.close()
	var blocked = load("res://src/storage/godot_storage_service.gd").new(path + "/blocked/account.cfg", credentials)
	check(blocked.write_login_profile(profile) != OK, "unwritable destination reports failure")
	var unavailable = load("res://src/storage/storage_service.gd").new()
	check(not unavailable.read_login_profile().ok and unavailable.save_login_token("a", "b", "c") != OK, "unsupported implementation cannot pretend to save")
	remove_folder(path)
	print("Login storage: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func remove_folder(path: String) -> void:
	for directory in DirAccess.get_directories_at(path): remove_folder(path.path_join(directory))
	for file in DirAccess.get_files_at(path): DirAccess.remove_absolute(path.path_join(file))
	DirAccess.remove_absolute(path)
