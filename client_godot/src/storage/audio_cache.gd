extends RefCounted
const Api = preload("res://src/network/account_api.gd")
var _root: String
var _directory := ""
var _logger: RefCounted
var _pending: Dictionary = {}
var _owned := RegEx.new()

func _init(root: String = "user://audio", logger: RefCounted = null) -> void:
	_root = root.trim_suffix("/")
	_logger = logger
	_owned.compile("^[0-9a-f]{64}\\.(part|audio|json|json\\.tmp)$")

func set_scope(server: String, username: String) -> Error:
	abort_all()
	_directory = ""
	var address := Api.normalize_server(server)
	if address.is_empty() or username.is_empty():
		return ERR_INVALID_PARAMETER
	var target := _root.path_join(JSON.stringify([address,username]).sha256_text())
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
	for file in DirAccess.get_files_at(_directory):
		if _owned.search(file) != null and (file.ends_with(".part") or file.ends_with(".tmp")):
			result = DirAccess.remove_absolute(_directory.path_join(file))
			if result != OK:
				_directory = ""
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
	var completed: bool = status.get("ok") is bool and status.ok and status.get("finished") is bool and status.finished
	var same_size: bool = (status.get("input_bytes") is int or status.get("input_bytes") is float) and status.input_bytes == metadata.bytes
	if not completed or not same_size or not _valid(metadata):
		abort(id)
		return _error(id,ERR_INVALID_DATA)
	file.flush()
	var result := file.get_error()
	file.close()
	_pending.erase(id)
	if result == OK:
		result = DirAccess.rename_absolute(_path(id,".part"),_path(id,".audio"))
	if result == OK:
		var manifest := FileAccess.open(_path(id,".json.tmp"),FileAccess.WRITE)
		if manifest == null:
			result = FileAccess.get_open_error()
		else:
			manifest.store_string(JSON.stringify(metadata))
			manifest.flush()
			result = manifest.get_error()
			manifest.close()
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
	metadata.duration = float(metadata.frames) / float(metadata.sample_rate)
	metadata.waveform = PackedFloat32Array(metadata.waveform)
	return metadata

func _valid(data: Dictionary) -> bool:
	if not (data.get("version") is int or data.get("version") is float) or data.version != 1 or not data.get("waveform") is Array or data.waveform.size() != 24:
		return false
	for key in ["sample_rate","channels","bits","frames","bytes"]:
		var value: Variant = data.get(key)
		if not (value is int or value is float) or not is_finite(float(value)) or value != floor(value):
			return false
	if data.sample_rate < 8000 or data.sample_rate > 192000 or not int(data.channels) in [1,2] or not int(data.bits) in [8,16,24,32]:
		return false
	if data.frames <= 0 or data.frames > data.sample_rate * 1800 or data.bytes < 44:
		return false
	for value in data.waveform:
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

func clear() -> Error:
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

func _error(id: String, result: Error) -> Error:
	if _logger != null:
		_logger.record("cache_error",{"reply_id":id,"code":"CACHE_WRITE_FAILED"})
	return result
