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
	check(service.write_login_profile(profile) == OK, "profile is written through a replacement file")
	check(not FileAccess.file_exists(path + "/account.cfg.tmp"), "successful write leaves no temporary file")
	_check_replacement_seams(path, credentials, profile)
	var restored: Dictionary = service.read_login_profile().data
	_check_profile_round_trip(restored, profile)
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
## 外部 seam：写入中断与替换失败都必须保留上一份可用配置。
func _check_replacement_seams(path: String, credentials: Variant, profile: Dictionary) -> void:
	var original := FileAccess.get_file_as_string(path + "/account.cfg")
	var interrupted = InterruptedWrite.new(path + "/account.cfg", credentials)
	check(interrupted.write_login_profile({"version":9}) != OK, "interrupted write reports failure")
	check(FileAccess.get_file_as_string(path + "/account.cfg") == original, "interrupted write keeps the previous profile")
	check(not FileAccess.file_exists(path + "/account.cfg.tmp"), "interrupted write removes its temporary file")
	var failing = FailingReplace.new(path + "/account.cfg", credentials)
	check(failing.write_login_profile({"version":9}) != OK, "failed replacement reports failure")
	check(FileAccess.get_file_as_string(path + "/account.cfg") == original, "failed replacement keeps the previous profile")
	check(not FileAccess.file_exists(path + "/account.cfg.tmp"), "failed replacement removes its temporary file")
	var guarded = load("res://src/storage/godot_storage_service.gd").new(path + "/guarded/account.cfg", FailingProtector.new())
	check(guarded.save_login_token(profile.server, "alice", "TOKEN") != OK, "protector failure is reported instead of a fake save")
	check(not guarded.read_login_token(profile.server, "alice").ok, "protector failure cannot read a token back")

class InterruptedWrite extends "res://src/storage/godot_storage_service.gd":
	func _store_temporary(path: String, text: String) -> Error:
		var file := FileAccess.open(path, FileAccess.WRITE)
		if file != null:
			file.store_string(text.substr(0, 4))
			file.close()
		return ERR_FILE_CANT_WRITE

class FailingReplace extends "res://src/storage/godot_storage_service.gd":
	func _replace_file(_temporary: String, _target: String) -> Error:
		return ERR_FILE_CANT_WRITE

class FailingProtector:
	extends RefCounted
	func save(_server: String, _username: String, _token: String) -> Error:
		return ERR_UNAVAILABLE
	func read(_server: String, _username: String) -> Dictionary:
		return {"ok": false, "code": "PROTECTED_STORAGE_UNAVAILABLE", "data": {}}
	func forget(_server: String, _username: String) -> Error:
		return ERR_UNAVAILABLE

func remove_folder(path: String) -> void:
	for directory in DirAccess.get_directories_at(path): remove_folder(path.path_join(directory))
	for file in DirAccess.get_files_at(path): DirAccess.remove_absolute(path.path_join(file))
	DirAccess.remove_absolute(path)

func _check_profile_round_trip(restored: Variant, profile: Variant) -> void:
	check(int(restored.get("version", 0)) == 2 and restored.get("server") == profile.server and restored.get("username") == "alice" and restored.get("accounts") == [], "profile round trip")
