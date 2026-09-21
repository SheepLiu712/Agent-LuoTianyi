extends Node
const AccountScope = preload("res://src/domain/account_scope.gd")
const ServerAddress = preload("res://src/domain/server_address.gd")
signal changed(id: String,state: Dictionary)
var _root: String
var _logger: RefCounted
var _session: Dictionary = {}
var _directory := ""
var _generation := 0
var _states: Dictionary = {}
var _active: Dictionary = {}
var _queue: Array[String] = []
var _recent: Array[String] = []
var _volatile: Dictionary = {}
func _init(root: String = "user://images",logger: RefCounted = null) -> void:
	_root = root
	_logger = logger
func start(session: Dictionary) -> void:
	stop()
	var server := ServerAddress.normalize(str(session.get("server","")))
	if server.is_empty() or not session.get("username") is String or not session.get("message_token") is String or session.username.is_empty() or session.message_token.is_empty():
		return
	_session = {"server":server,"username":session.username,"token":session.message_token}
	_directory = _root.path_join(AccountScope.key(server, session.username))
func stop() -> void:
	_generation += 1
	for http in _active.values():
		http.cancel_request()
		http.queue_free()
	_active.clear()
	_queue.clear()
	_states.clear()
	_recent.clear()
	_volatile.clear()
	_session.clear()
	_directory = ""
func get_state(id: String) -> Dictionary:
	return _states.get(id,{"status":"idle","texture":null,"original_size":Vector2i.ZERO,"code":""}).duplicate()
func store_local(id: String, bytes: PackedByteArray) -> Error:
	if id.is_empty() or _session.is_empty(): return ERR_UNCONFIGURED
	var image := _decode(bytes)
	if image == null: return ERR_INVALID_DATA
	var result := _save(id, bytes)
	if result != OK: _volatile[id] = image
	_ready_image(id, image, "" if result == OK else "CACHE_WRITE_FAILED")
	return result
func ensure(id: String) -> void:
	if id.is_empty() or _session.is_empty() or _states.has(id):
		return
	var path := _path(id)
	if FileAccess.file_exists(path):
		var cached := _decode(FileAccess.get_file_as_bytes(path))
		if cached != null:
			_ready_image(id,cached,"")
			return
		DirAccess.remove_absolute(path)
	_states[id] = {"status":"loading","texture":null,"original_size":Vector2i.ZERO,"code":""}
	changed.emit(id,get_state(id))
	_queue.append(id)
	_pump()
func retry(id: String) -> void:
	if get_state(id).status == "error":
		_states.erase(id)
		ensure(id)
func preview(id: String) -> Texture2D:
	var image: Image = _volatile.get(id)
	if image == null and not _directory.is_empty() and FileAccess.file_exists(_path(id)):
		image = _decode(FileAccess.get_file_as_bytes(_path(id)))
	if image == null:
		_error(id,"INVALID_IMAGE")
		return null
	return ImageTexture.create_from_image(image)
func _pump() -> void:
	while _active.size()<3 and not _queue.is_empty():
		var id: String = _queue.pop_front()
		var http := HTTPRequest.new()
		var generation := _generation
		_active[id] = http
		http.timeout = 15
		http.body_size_limit = 16*1024*1024
		http.max_redirects = 0
		add_child(http)
		http.request_completed.connect(func(result,status,_headers,body):
			if generation != _generation:
				return
			_active.erase(id)
			http.queue_free()
			if result != HTTPRequest.RESULT_SUCCESS or status != 200:
				_error(id,"NETWORK_ERROR")
			else:
				var image := _decode(body)
				if image == null:
					_error(id,"INVALID_IMAGE")
				else:
					var saved := _save(id,body)
					if saved != OK:
						_volatile[id] = image
					_ready_image(id,image,"" if saved == OK else "CACHE_WRITE_FAILED")
			_pump())
		var error := http.request(_session.server+"/get_image",PackedStringArray(["Content-Type: application/json"]),HTTPClient.METHOD_POST,JSON.stringify({"username":_session.username,"token":_session.token,"uuid":id}))
		if error != OK:
			_active.erase(id)
			http.queue_free()
			_error(id,"NETWORK_ERROR")
func _ready_image(id: String,image: Image,code: String) -> void:
	var thumb: Image = image.duplicate()
	var scale := minf(1.0,480.0/maxi(image.get_width(),image.get_height()))
	if scale<1:
		thumb.resize(maxi(1,int(image.get_width()*scale)),maxi(1,int(image.get_height()*scale)))
	_states[id] = {"status":"ready","texture":ImageTexture.create_from_image(thumb),"original_size":image.get_size(),"code":code}
	_recent.erase(id)
	_recent.append(id)
	while _recent.size()>24:
		var old: String = _recent.pop_front()
		_states.erase(old)
		_volatile.erase(old)
	changed.emit(id,get_state(id))
	if _logger != null:
		_logger.record("history_image",{"reply_id":id,"code":"OK" if code.is_empty() else code})
func _error(id: String,code: String) -> void:
	_states[id] = {"status":"error","texture":null,"original_size":Vector2i.ZERO,"code":code}
	changed.emit(id,get_state(id))
	if _logger != null:
		_logger.record("history_image_error",{"reply_id":id,"code":code})
func _save(id: String,bytes: PackedByteArray) -> Error:
	var error := DirAccess.make_dir_recursive_absolute(_directory)
	if error != OK:
		return error
	var path := _path(id)
	var file := FileAccess.open(path+".tmp",FileAccess.WRITE)
	if file == null:
		return FileAccess.get_open_error()
	file.store_buffer(bytes)
	file.flush()
	error = file.get_error()
	file.close()
	if error == OK:
		error = DirAccess.rename_absolute(path+".tmp",path)
	if error != OK:
		DirAccess.remove_absolute(path+".tmp")
	return error
func _path(id: String) -> String:
	return _directory.path_join(id.sha256_text()+".image")
func _decode(bytes: PackedByteArray) -> Image:
	if bytes.size()<24 or bytes.size()>16*1024*1024:
		return null
	var image := Image.new()
	var result := ERR_INVALID_DATA
	if bytes.slice(0,8).hex_encode() == "89504e470d0a1a0a":
		var width := _big_endian(bytes,16)
		var height := _big_endian(bytes,20)
		if width<1 or height<1 or width>8192 or height>8192 or width*height>16000000:
			return null
		result = image.load_png_from_buffer(bytes)
	elif bytes[0] == 255 and bytes[1] == 216:
		result = image.load_jpg_from_buffer(bytes)
	elif bytes.slice(0,4).get_string_from_ascii() == "RIFF" and bytes.slice(8,12).get_string_from_ascii() == "WEBP":
		result = image.load_webp_from_buffer(bytes)
	if result != OK or image.get_width()>8192 or image.get_height()>8192 or image.get_width()*image.get_height()>16000000:
		return null
	return image
func _big_endian(bytes: PackedByteArray,at: int) -> int:
	return (int(bytes[at])<<24)|(int(bytes[at+1])<<16)|(int(bytes[at+2])<<8)|int(bytes[at+3])
func _exit_tree() -> void:
	stop()
