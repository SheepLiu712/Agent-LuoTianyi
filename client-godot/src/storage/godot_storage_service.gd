extends "res://src/storage/storage_service.gd"
## 平台 API 只出现在本实现内，调用方只依赖 StorageService。
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
	error = _store_temporary(temporary, JSON.stringify(data))
	if error == OK: error = _replace_file(temporary, _profile_path)
	if error != OK: DirAccess.remove_absolute(temporary)
	return error

## 覆盖点：测试子类替换这两步来模拟写入中断与替换失败，
## 生产实现保持「先写临时文件，再整体替换」。
func _store_temporary(path: String, text: String) -> Error:
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null: return FileAccess.get_open_error()
	file.store_string(text)
	file.flush()
	var error := file.get_error()
	file.close()
	return error

func _replace_file(temporary: String, target: String) -> Error:
	return DirAccess.rename_absolute(temporary, target)

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
	_fill_free_bytes(result, absolute)
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

func _fill_free_bytes(result: Dictionary, absolute: String) -> void:
	if result.free_bytes < 0:
		var directory := DirAccess.open(absolute)
		if directory != null:
			var available := directory.get_space_left()
			# Godot 无法区分「不支持」与「真的为 0」，只能按 >0 采信。
			if available > 0: result.free_bytes = available
