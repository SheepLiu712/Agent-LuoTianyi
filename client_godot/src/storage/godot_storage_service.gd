extends "res://src/storage/storage_service.gd"
## Platform APIs stay in this implementation; callers use StorageService only.
var _volume: RefCounted
var _profile_path: String
var _credentials: RefCounted

func _init(profile_path: String = "user://account.cfg", credentials: RefCounted = null) -> void:
	_profile_path = profile_path
	_credentials = credentials
	if ClassDB.class_exists("StorageVolume"):
		_volume = ClassDB.instantiate("StorageVolume")

func read_login_profile() -> Dictionary:
	if not FileAccess.file_exists(_profile_path): return {"ok":true,"code":"OK","data":{}}
	var file := FileAccess.open(_profile_path, FileAccess.READ)
	if file == null: return {"ok":false,"code":"STORAGE_ERROR","data":{}}
	var parser := JSON.new()
	if parser.parse(file.get_as_text()) != OK or not parser.data is Dictionary:
		return {"ok":false,"code":"INVALID_DATA","data":{}}
	return {"ok":true,"code":"OK","data":parser.data}

func write_login_profile(data: Dictionary) -> Error:
	var error := DirAccess.make_dir_recursive_absolute(_profile_path.get_base_dir())
	if error != OK: return error
	var temporary := _profile_path + ".tmp"
	var file := FileAccess.open(temporary, FileAccess.WRITE)
	if file == null: return FileAccess.get_open_error()
	file.store_string(JSON.stringify(data))
	file.flush()
	error = file.get_error()
	file.close()
	if error == OK: error = DirAccess.rename_absolute(temporary, _profile_path)
	if error != OK: DirAccess.remove_absolute(temporary)
	return error

func read_login_token(server: String, username: String) -> Dictionary:
	return _credentials.read(server, username) if _credentials != null else super.read_login_token(server, username)

func save_login_token(server: String, username: String, token: String) -> Error:
	return _credentials.save(server, username, token) if _credentials != null else ERR_UNAVAILABLE

func forget_login_token(server: String, username: String) -> Error:
	return _credentials.forget(server, username) if _credentials != null else ERR_UNAVAILABLE

func query_directory(path: String) -> Dictionary:
	var result := {"directory_bytes":-1,"total_bytes":-1,"free_bytes":-1,"file_count":-1,"code":"STORAGE_UNAVAILABLE"}
	if path.is_empty(): return result
	var absolute := ProjectSettings.globalize_path(path)
	if _volume != null:
		var capacity: Dictionary = _volume.query(absolute)
		for key in ["total_bytes", "free_bytes"]:
			if capacity.get(key) is int and capacity[key] >= 0: result[key] = capacity[key]
	if result.total_bytes == 0: result.total_bytes = -1
	var measured := _measure(absolute)
	result.directory_bytes = measured.bytes
	result.file_count = measured.count
	result.code = "SCAN_FAILED" if measured.bytes < 0 else ("CAPACITY_UNAVAILABLE" if result.total_bytes < 0 else "OK")
	if result.free_bytes < 0:
		var directory := DirAccess.open(absolute)
		if directory != null:
			var available := directory.get_space_left()
			# Godot cannot distinguish unsupported from a genuine zero without an adapter.
			if available > 0: result.free_bytes = available
	return result

func _measure(path: String) -> Dictionary:
	var directory := DirAccess.open(path)
	if directory == null: return {"bytes":-1,"count":-1}
	directory.include_hidden = true
	directory.include_navigational = false
	if directory.list_dir_begin() != OK: return {"bytes":-1,"count":-1}
	var total: int = 0
	var count: int = 0
	var name := directory.get_next()
	while not name.is_empty():
		if not directory.is_link(name):
			if directory.current_is_dir():
				var nested := _measure(path.path_join(name))
				if nested.bytes < 0: return {"bytes":-1,"count":-1}
				total += int(nested.bytes)
				count += int(nested.count)
			else:
				var file := FileAccess.open(path.path_join(name), FileAccess.READ)
				if file == null: return {"bytes":-1,"count":-1}
				total += file.get_length()
				count += 1
		name = directory.get_next()
	directory.list_dir_end()
	return {"bytes":total,"count":count}
