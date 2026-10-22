extends "res://src/storage/settings_store.gd"
@export var file_path := ""
var _config := ConfigFile.new()

func _init(path: String = "") -> void:
	file_path = path

func load_settings() -> Error:
	var candidate := ConfigFile.new()
	var error := candidate.load(file_path)
	if error == OK: _config = candidate
	return error

func get_value(section: String, key: String, fallback: Variant = null) -> Variant:
	return _config.get_value(section, key, fallback)

func set_value(section: String, key: String, value: Variant) -> void:
	_config.set_value(section, key, value)

func save_settings() -> Error:
	var temporary := file_path + ".tmp"
	var error := _config.save(temporary)
	if error != OK: return error
	error = DirAccess.rename_absolute(temporary, file_path)
	if error != OK: DirAccess.remove_absolute(temporary)
	return error
