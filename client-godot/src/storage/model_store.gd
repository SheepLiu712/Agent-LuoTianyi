extends RefCounted
const ServerAddress = preload("res://src/domain/server_address.gd")
const Schema = preload("res://src/storage/log_schema.gd")
const Events = preload("res://src/storage/log_events.gd")
const AtomicFile = preload("res://src/storage/atomic_file.gd")
var _security: Object
var _root: String
var _scope := ""
var _directory := ""
var _logger: RefCounted
func _init(security: Object,root: String = "user://models",logger: RefCounted = null) -> void:
	_security = security
	_root = root
	_logger = logger
func set_scope(server: String,username: String) -> void:
	var base := ServerAddress.normalize(server)
	_scope = "" if base.is_empty() or username.is_empty() else JSON.stringify([base,username])
	_directory = "" if _scope.is_empty() else _root.path_join(_scope.sha256_text())
func read(type_id: String) -> Dictionary:
	if _directory.is_empty() or type_id.is_empty() or not FileAccess.file_exists(_path(type_id)):
		return {"ok":false,"code":"NOT_FOUND","config":{}}
	var data: Variant = JSON.parse_string(FileAccess.get_file_as_string(_path(type_id)))
	if not data is Dictionary or data.get("version") != 1 or not data.get("config") is Dictionary:
		return {"ok":false,"code":"INVALID_CONFIG","config":{}}
	var config: Dictionary = data.config.duplicate(true)
	config.api_key = ""
	return _read_key(type_id, data, config)
func save(type_id: String,config: Dictionary,allow_plain: bool = false) -> Dictionary:
	if _invalid_save(type_id, config):
		return {"ok":false,"code":"INVALID_CONFIG"}
	var values := {}
	for key in ["enabled","provider","base_url","model","model_kind","model_capabilities","params"]:
		values[key] = config.get(key)
	var data := {"version":1,"config":values}
	var key_result := _protect_key(type_id, config, data, allow_plain)
	if not key_result.ok:
		_log_token("write", type_id, "failure", str(key_result.get("code", "KEY_UNAVAILABLE")))
		return key_result
	var error := _write_config(type_id, data)
	if error != OK:
		_discard_tmp(type_id)
	_log_token("write", type_id, "success" if error == OK else "failure", "OK" if error == OK else "SAVE_FAILED")
	return {"ok":error == OK,"code":"OK" if error == OK else "SAVE_FAILED"}

func _invalid_save(type_id: String, config: Dictionary) -> bool:
	return _directory.is_empty() or type_id.is_empty() or not config.get("api_key") is String

func _discard_tmp(type_id: String) -> void:
	var temporary := _path(type_id) + ".tmp"
	if FileAccess.file_exists(temporary):
		DirAccess.remove_absolute(temporary)
func _path(type_id: String) -> String:
	return _directory.path_join(type_id.sha256_text()+".json")

func _read_key(type_id: String, data: Dictionary, config: Dictionary) -> Dictionary:
	if data.get("api_key_plain") is String:
		config.api_key = data.api_key_plain
	elif data.get("api_key_dpapi") is String and not data.api_key_dpapi.is_empty():
		var plain: Dictionary = _security.unprotect_secret(Marshalls.base64_to_raw(data.api_key_dpapi),(_scope+"/"+type_id).to_utf8_buffer())
		if not plain.ok:
			config.enabled = false
			_log_token("read", type_id, "failure", "KEY_UNAVAILABLE")
			return {"ok":false,"code":"KEY_UNAVAILABLE","config":config}
		config.api_key = plain.data.get_string_from_utf8()
	_log_token("read", type_id, "success", "OK")
	return {"ok":true,"code":"OK","config":config}

func _protect_key(type_id: String, config: Dictionary, data: Dictionary, allow_plain: bool) -> Dictionary:
	if not config.api_key.is_empty():
		var protected: Dictionary = _security.protect_secret(config.api_key.to_utf8_buffer(),(_scope+"/"+type_id).to_utf8_buffer())
		if protected.ok:
			data.api_key_dpapi = Marshalls.raw_to_base64(protected.data)
		elif not allow_plain:
			return {"ok":false,"code":"PLAINTEXT_CONFIRMATION_REQUIRED"}
		else:
			data.api_key_plain = config.api_key
	return {"ok":true}

func _log_token(action: String, type_id: String, outcome: String, code: String) -> void:
	Events.security_token(_logger, action, Schema.hash_subject(_scope, type_id), outcome, code)

func _write_config(type_id: String, data: Dictionary) -> Error:
	return AtomicFile.write_text(_path(type_id), JSON.stringify(data))
