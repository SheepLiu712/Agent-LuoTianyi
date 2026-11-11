extends RefCounted
const AccountScope = preload("res://src/domain/account_scope.gd")
const Schema = preload("res://src/storage/log_schema.gd")
const Events = preload("res://src/storage/log_events.gd")
var _security: Object
var _root: String
var _logger: RefCounted

func _init(security: Object, root: String = "user://accounts", logger: RefCounted = null) -> void:
	_security = security
	_root = root.trim_suffix("/")
	_logger = logger

func _scope(server: String, username: String) -> String:
	return AccountScope.key(server, username)

func save(server: String, username: String, token: String) -> Error:
	if server.is_empty() or username.is_empty() or token.is_empty():
		_log_token("write", server, username, "failure", "INVALID_INPUT")
		return ERR_INVALID_PARAMETER
	var started := Time.get_ticks_usec()
	var transaction_id := Schema.new_transaction_id()
	var scope := _scope(server, username)
	var encrypted: Dictionary = _security.protect_secret(token.to_utf8_buffer(), scope.to_utf8_buffer())
	if not encrypted.ok:
		return _save_failure(server, username, transaction_id, started, "PROTECT_FAILED", ERR_UNAVAILABLE)
	return _write_encrypted(server, username, scope, encrypted, transaction_id, started)

func _write_encrypted(server: String, username: String, scope: String, encrypted: Dictionary, transaction_id: String, started: int) -> Error:
	if FileAccess.file_exists(_root):
		return _save_failure(server, username, transaction_id, started, "SAVE_FAILED", ERR_FILE_BAD_PATH)
	var created := DirAccess.make_dir_recursive_absolute(_root)
	if created != OK:
		return _save_failure(server, username, transaction_id, started, "SAVE_FAILED", created)
	var target := _root.path_join(scope + ".bin")
	var file := FileAccess.open(target + ".tmp", FileAccess.WRITE)
	if file == null:
		return _save_failure(server, username, transaction_id, started, "SAVE_FAILED", FileAccess.get_open_error())
	file.store_buffer(encrypted.data)
	file.flush()
	var written := file.get_error()
	file.close()
	var result := DirAccess.rename_absolute(target + ".tmp", target) if written == OK else written
	if result != OK:
		DirAccess.remove_absolute(target + ".tmp")
		return _save_failure(server, username, transaction_id, started, "SAVE_FAILED", result)
	_log_token("write", server, username, "success", "OK")
	_log_transaction(transaction_id, true, started, "OK")
	return result

func _save_failure(server: String, username: String, transaction_id: String, started: int, code: String, error: Error) -> Error:
	_log_token("write", server, username, "failure", code)
	_log_transaction(transaction_id, false, started, code)
	return error

func read(server: String, username: String) -> Dictionary:
	var failure := {"ok":false, "code":"UNAVAILABLE", "token":""}
	var scope := _scope(server, username)
	var path := _root.path_join(scope + ".bin")
	if not FileAccess.file_exists(path):
		failure.code = "NOT_FOUND"
		_log_token("read", server, username, "failure", "NOT_FOUND")
		return failure
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null or file.get_length() > 131072:
		_log_token("read", server, username, "failure", "UNAVAILABLE")
		return failure
	var cipher := file.get_buffer(file.get_length())
	file.close()
	var restored: Dictionary = _security.unprotect_secret(cipher, scope.to_utf8_buffer())
	if not restored.ok:
		_log_token("read", server, username, "failure", "UNPROTECT_FAILED")
		return failure
	var token: String = restored.data.get_string_from_utf8()
	if not token.is_empty():
		_log_token("read", server, username, "success", "OK")
		return {"ok":true, "code":"OK", "token":token}
	_log_token("read", server, username, "failure", "NOT_FOUND")
	return failure

func forget(server: String, username: String) -> Error:
	var path := _root.path_join(_scope(server, username) + ".bin")
	var result := DirAccess.remove_absolute(path) if FileAccess.file_exists(path) else OK
	_log_token("forget", server, username, "success" if result == OK else "failure", "OK" if result == OK else "SAVE_FAILED")
	return result

func _log_token(action: String, server: String, username: String, outcome: String, code: String) -> void:
	Events.security_token(_logger, action, Schema.hash_subject(server, username), outcome, code)

func _log_transaction(transaction_id: String, success: bool, started: int, code: String) -> void:
	Events.file_transaction(_logger, "account", "credential_save", transaction_id, success, started, code)
