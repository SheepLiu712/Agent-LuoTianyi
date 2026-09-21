extends RefCounted
const ServerAddress = preload("res://src/domain/server_address.gd")
var _security: Object
var _root: String
var _scope := ""
var _directory := ""
func _init(security: Object,root: String = "user://models") -> void:
	_security = security
	_root = root
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
	if data.get("api_key_plain") is String:
		config.api_key = data.api_key_plain
	elif data.get("api_key_dpapi") is String and not data.api_key_dpapi.is_empty():
		var plain: Dictionary = _security.unprotect_secret(Marshalls.base64_to_raw(data.api_key_dpapi),(_scope+"/"+type_id).to_utf8_buffer())
		if not plain.ok:
			config.enabled = false
			return {"ok":false,"code":"KEY_UNAVAILABLE","config":config}
		config.api_key = plain.data.get_string_from_utf8()
	return {"ok":true,"code":"OK","config":config}
func save(type_id: String,config: Dictionary,allow_plain: bool = false) -> Dictionary:
	if _directory.is_empty() or type_id.is_empty() or not config.get("api_key") is String:
		return {"ok":false,"code":"INVALID_CONFIG"}
	var values := {}
	for key in ["enabled","provider","base_url","model","model_kind","model_capabilities","params"]:
		values[key] = config.get(key)
	var data := {"version":1,"config":values}
	if not config.api_key.is_empty():
		var protected: Dictionary = _security.protect_secret(config.api_key.to_utf8_buffer(),(_scope+"/"+type_id).to_utf8_buffer())
		if protected.ok:
			data.api_key_dpapi = Marshalls.raw_to_base64(protected.data)
		elif not allow_plain:
			return {"ok":false,"code":"PLAINTEXT_CONFIRMATION_REQUIRED"}
		else:
			data.api_key_plain = config.api_key
	var error := DirAccess.make_dir_recursive_absolute(_directory)
	if error == OK:
		var file := FileAccess.open(_path(type_id)+".tmp",FileAccess.WRITE)
		if file == null:
			error = FileAccess.get_open_error()
		else:
			file.store_string(JSON.stringify(data))
			file.flush()
			error = file.get_error()
			file.close()
			if error == OK:
				error = DirAccess.rename_absolute(_path(type_id)+".tmp",_path(type_id))
	if error != OK and FileAccess.file_exists(_path(type_id)+".tmp"):
		DirAccess.remove_absolute(_path(type_id)+".tmp")
	return {"ok":error == OK,"code":"OK" if error == OK else "SAVE_FAILED"}
func _path(type_id: String) -> String:
	return _directory.path_join(type_id.sha256_text()+".json")
