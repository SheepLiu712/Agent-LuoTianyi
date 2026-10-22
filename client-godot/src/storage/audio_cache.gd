extends RefCounted
const AccountScope = preload("res://src/domain/account_scope.gd")
const ServerAddress = preload("res://src/domain/server_address.gd")
var _root: String
var _directory := ""
var _logger: RefCounted
var _pending: Dictionary = {}
var _owned := RegEx.new()
var _now_seconds: Callable

func _init(root: String = "user://audio", logger: RefCounted = null, now_seconds: Callable = Callable()) -> void:
	_root = root.trim_suffix("/")
	_logger = logger
	_now_seconds = now_seconds
	_owned.compile("^[0-9a-f]{64}\\.(part|audio|json|json\\.tmp)$")

func set_scope(server: String, username: String) -> Error:
	abort_all()
	_directory = ""
	var address := ServerAddress.normalize(server)
	if address.is_empty() or username.is_empty():
		return ERR_INVALID_PARAMETER
	var target := _root.path_join(AccountScope.key(server, username))
	var ancestor := target
	while not ancestor.is_empty():
		if FileAccess.file_exists(ancestor):
			return ERR_FILE_BAD_PATH
		var parent := ancestor.get_base_dir()
		if ancestor == parent:
			break
		ancestor = parent
	var result := DirAccess.make_dir_recursive_absolute(target)
	if result != OK:
		return result
	_directory = target
	result = _cleanup_incomplete_and_orphans()
	if result != OK:
		_directory = ""
	return result

func _cleanup_incomplete_and_orphans() -> Error:
	var pairs := _cache_pairs()
	for stem in pairs:
		var files: Dictionary = pairs[stem]
		var remove_names := _incomplete_files(files)
		for file in remove_names:
			var result := DirAccess.remove_absolute(_directory.path_join(file))
			if result != OK:
				return result
	return OK
func _path(id: String, extension: String) -> String:
	return _directory.path_join(id.sha256_text() + extension)

func get_directory() -> String:
	return _directory

func begin(id: String) -> Error:
	if _directory.is_empty() or id.is_empty():
		return ERR_UNCONFIGURED
	if _pending.has(id) or not lookup(id).is_empty():
		return ERR_ALREADY_EXISTS
	if _pending.size() >= 16:
		return ERR_OUT_OF_MEMORY
	var file := FileAccess.open(_path(id,".part"),FileAccess.WRITE)
	if file == null:
		return _error(id,FileAccess.get_open_error())
	_pending[id] = file
	return OK

func append(id: String, bytes: PackedByteArray) -> Error:
	if not _pending.has(id):
		return ERR_DOES_NOT_EXIST
	if bytes.size() > 8*1024*1024:
		abort(id)
		return _error(id,ERR_OUT_OF_MEMORY)
	var file: FileAccess = _pending[id]
	file.store_buffer(bytes)
	var result := file.get_error()
	if result != OK:
		abort(id)
		return _error(id,result)
	return OK

func commit(id: String, status: Dictionary, waveform: PackedFloat32Array) -> Error:
	if not _pending.has(id):
		return ERR_DOES_NOT_EXIST
	var file: FileAccess = _pending[id]
	var metadata := {"version":1, "sample_rate":status.get("sample_rate",0), "channels":status.get("channels",0),
		"bits":status.get("bits",0), "frames":status.get("decoded_frames",0), "bytes":file.get_position(), "waveform":Array(waveform)}
	metadata.saved_at_unix = _now()
	if not _valid_completion(status, metadata):
		abort(id)
		return _error(id,ERR_INVALID_DATA)
	file.flush()
	var result := file.get_error()
	file.close()
	_pending.erase(id)
	if result == OK:
		result = DirAccess.rename_absolute(_path(id,".part"),_path(id,".audio"))
	if result == OK:
		result = _write_manifest(id, metadata)
	if result == OK:
		result = DirAccess.rename_absolute(_path(id,".json.tmp"),_path(id,".json"))
	if result != OK:
		for extension in [".part", ".audio", ".json.tmp"]:
			if FileAccess.file_exists(_path(id,extension)):
				DirAccess.remove_absolute(_path(id,extension))
		return _error(id,result)
	if _logger != null:
		_logger.record("cache_committed",{"reply_id":id,"bytes":metadata.bytes,"frames":metadata.frames})
	return OK
func lookup(id: String) -> Dictionary:
	if _directory.is_empty() or id.is_empty() or not FileAccess.file_exists(_path(id,".json")):
		return {}
	var file := FileAccess.open(_path(id,".json"),FileAccess.READ)
	if file == null or file.get_length() > 8192:
		return {}
	var metadata: Variant = JSON.parse_string(file.get_as_text())
	file.close()
	if not metadata is Dictionary or not _valid(metadata):
		return {}
	var audio := FileAccess.open(_path(id,".audio"),FileAccess.READ)
	if audio == null or audio.get_length() != int(metadata.bytes):
		return {}
	audio.close()
	metadata.path = _path(id,".audio")
	metadata.saved_at_unix = _saved_at(metadata, metadata.path)
	metadata.duration = float(metadata.frames) / float(metadata.sample_rate)
	metadata.waveform = PackedFloat32Array(metadata.waveform)
	return metadata

func _valid(data: Dictionary) -> bool:
	return _valid_saved_time(data) and _valid_metadata_shape(data) and _valid_integer_fields(data) and _valid_audio_ranges(data) and _valid_waveform(data.waveform)

func _valid_saved_time(data: Dictionary) -> bool:
	if not data.has("saved_at_unix"):
		return true
	var saved: Variant = data.saved_at_unix
	return (saved is int or saved is float) and is_finite(float(saved)) and saved >= 0

func _valid_metadata_shape(data: Dictionary) -> bool:
	return (data.get("version") is int or data.get("version") is float) and data.version == 1 and data.get("waveform") is Array and data.waveform.size() == 24

func _valid_integer_fields(data: Dictionary) -> bool:
	for key in ["sample_rate","channels","bits","frames","bytes"]:
		var value: Variant = data.get(key)
		if not (value is int or value is float) or not is_finite(float(value)) or value != floor(value):
			return false
	return true

func _valid_audio_ranges(data: Dictionary) -> bool:
	if data.sample_rate < 8000 or data.sample_rate > 192000 or not int(data.channels) in [1,2] or not int(data.bits) in [8,16,24,32]:
		return false
	return data.frames > 0 and data.frames <= data.sample_rate * 1800 and data.bytes >= 44

func _valid_waveform(waveform: Array) -> bool:
	for value in waveform:
		if not (value is int or value is float) or not is_finite(value) or value < 0 or value > 1:
			return false
	return true
func abort(id: String) -> void:
	if _pending.has(id):
		_pending[id].close()
		_pending.erase(id)
		DirAccess.remove_absolute(_path(id,".part"))

func abort_all() -> void:
	for id in _pending.keys():
		abort(id)

func clear(older_than_days: int = 0) -> Error:
	if older_than_days < 0: return ERR_INVALID_PARAMETER
	if older_than_days > 0: return _clear_older(older_than_days)
	abort_all()
	if _directory.is_empty():
		return ERR_UNCONFIGURED
	var result := OK
	for file in DirAccess.get_files_at(_directory):
		if _owned.search(file) != null:
			var removed := DirAccess.remove_absolute(_directory.path_join(file))
			if removed != OK:
				result = removed
	if _logger != null:
		_logger.record("cache_cleared",{"code":"OK" if result == OK else "CACHE_CLEAR_FAILED"})
	return result

func _now() -> int:
	return int(_now_seconds.call()) if _now_seconds.is_valid() else int(Time.get_unix_time_from_system())

func _saved_at(metadata: Dictionary, audio_path: String) -> int:
	if metadata.has("saved_at_unix"): return int(metadata.saved_at_unix)
	if not FileAccess.file_exists(audio_path): return -1
	var modified := FileAccess.get_modified_time(audio_path)
	return modified if modified > 0 else -1

func _clear_older(days: int) -> Error:
	if _directory.is_empty(): return ERR_UNCONFIGURED
	var cutoff := float(_now()) - float(days) * 86400.0
	var result := OK
	for name in DirAccess.get_files_at(_directory):
		if _owned.search(name) == null or not name.ends_with(".json"): continue
		var removed := _clear_old_manifest(_directory.path_join(name), cutoff)
		if removed != OK:
			result = removed
	if _logger != null: _logger.record("cache_cleared", {"code":"OK" if result == OK else "CACHE_CLEAR_FAILED"})
	return result
func _error(id: String, result: Error) -> Error:
	if _logger != null:
		_logger.record("cache_error",{"reply_id":id,"code":"CACHE_WRITE_FAILED"})
	return result

func open_stream(id: String) -> RefCounted:
	if lookup(id).is_empty(): return null
	var file := FileAccess.open(_path(id,".audio"),FileAccess.READ)
	return preload("res://src/storage/godot_read_stream.gd").new(file) if file != null else null

func _cache_pairs() -> Dictionary:
	var pairs: Dictionary = {}
	for file in DirAccess.get_files_at(_directory):
		if _owned.search(file) == null:
			continue
		var extension := ""
		if file.ends_with(".part"):
			extension = ".part"
		elif file.ends_with(".json.tmp"):
			extension = ".json.tmp"
		elif file.ends_with(".audio"):
			extension = ".audio"
		elif file.ends_with(".json"):
			extension = ".json"
		if extension.is_empty():
			continue
		var stem := file.trim_suffix(extension)
		if not pairs.has(stem):
			pairs[stem] = {}
		pairs[stem][extension] = file
	return pairs

func _incomplete_files(files: Dictionary) -> Array[String]:
	var remove_names: Array[String] = []
	for extension in [".part", ".json.tmp"]:
		if files.has(extension):
			remove_names.append(files[extension])
	var has_audio := files.has(".audio")
	var has_metadata := files.has(".json")
	if has_audio != has_metadata:
		if has_audio:
			remove_names.append(files[".audio"])
		if has_metadata:
			remove_names.append(files[".json"])
	return remove_names

func _valid_completion(status: Dictionary, metadata: Dictionary) -> bool:
	var completed: bool = status.get("ok") is bool and status.ok and status.get("finished") is bool and status.finished
	var same_size: bool = (status.get("input_bytes") is int or status.get("input_bytes") is float) and status.input_bytes == metadata.bytes
	return completed and same_size and _valid(metadata)

func _write_manifest(id: String, metadata: Dictionary) -> Error:
	var result := OK
	var manifest := FileAccess.open(_path(id,".json.tmp"),FileAccess.WRITE)
	if manifest == null:
		result = FileAccess.get_open_error()
	else:
		manifest.store_string(JSON.stringify(metadata))
		manifest.flush()
		result = manifest.get_error()
		manifest.close()
	return result

func _clear_old_manifest(manifest_path: String, cutoff: float) -> Error:
	var file := FileAccess.open(manifest_path, FileAccess.READ)
	if file == null:
		return FileAccess.get_open_error()
	if file.get_length() > 8192: return OK
	var parser := JSON.new()
	var parsed := parser.parse(file.get_as_text())
	file.close()
	if parsed != OK or not parser.data is Dictionary or not _valid(parser.data): return OK
	var audio_path := manifest_path.get_basename() + ".audio"
	var saved := _saved_at(parser.data, audio_path)
	if saved < 0 or float(saved) >= cutoff: return OK
	return _remove_cache_pair(audio_path, manifest_path)

func _remove_cache_pair(audio_path: String, manifest_path: String) -> Error:
	if FileAccess.file_exists(audio_path):
		var removed := DirAccess.remove_absolute(audio_path)
		if removed != OK:
			return removed
	var removed := DirAccess.remove_absolute(manifest_path)
	return removed
