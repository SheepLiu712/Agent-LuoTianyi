extends RefCounted
const AccountScope = preload("res://src/domain/account_scope.gd")
var _security: Object
var _root: String

func _init(security: Object, root: String = "user://accounts") -> void:
	_security = security
	_root = root.trim_suffix("/")

func _scope(server: String, username: String) -> String:
	return AccountScope.key(server, username)

func save(server: String, username: String, token: String) -> Error:
	if server.is_empty() or username.is_empty() or token.is_empty():
		return ERR_INVALID_PARAMETER
	var scope := _scope(server, username)
	var encrypted: Dictionary = _security.protect_secret(token.to_utf8_buffer(), scope.to_utf8_buffer())
	if not encrypted.ok:
		return ERR_UNAVAILABLE
	if FileAccess.file_exists(_root):
		return ERR_FILE_BAD_PATH
	var created := DirAccess.make_dir_recursive_absolute(_root)
	if created != OK:
		return created
	var target := _root.path_join(scope + ".bin")
	var file := FileAccess.open(target + ".tmp", FileAccess.WRITE)
	if file == null:
		return FileAccess.get_open_error()
	file.store_buffer(encrypted.data)
	file.flush()
	var written := file.get_error()
	file.close()
	var result := DirAccess.rename_absolute(target + ".tmp", target) if written == OK else written
	if result != OK:
		DirAccess.remove_absolute(target + ".tmp")
	return result

func read(server: String, username: String) -> Dictionary:
	var failure := {"ok":false, "code":"UNAVAILABLE", "token":""}
	var scope := _scope(server, username)
	var path := _root.path_join(scope + ".bin")
	if not FileAccess.file_exists(path):
		failure.code = "NOT_FOUND"
		return failure
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null or file.get_length() > 131072:
		return failure
	var cipher := file.get_buffer(file.get_length())
	file.close()
	var restored: Dictionary = _security.unprotect_secret(cipher, scope.to_utf8_buffer())
	if not restored.ok:
		return failure
	var token: String = restored.data.get_string_from_utf8()
	return {"ok":true, "code":"OK", "token":token} if not token.is_empty() else failure

func forget(server: String, username: String) -> Error:
	var path := _root.path_join(_scope(server, username) + ".bin")
	return DirAccess.remove_absolute(path) if FileAccess.file_exists(path) else OK
