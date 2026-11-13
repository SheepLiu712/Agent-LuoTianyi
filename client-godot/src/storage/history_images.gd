extends "res://src/storage/history_image_source.gd"
const Codec = preload("res://src/storage/history_image_codec.gd")
const Locator = preload("res://src/storage/python_client_locator.gd")
const AccountScope = preload("res://src/domain/account_scope.gd")
const ServerAddress = preload("res://src/domain/server_address.gd")
const AtomicFile = preload("res://src/storage/atomic_file.gd")
const Schema = preload("res://src/storage/log_schema.gd")
const Events = preload("res://src/storage/log_events.gd")
const Pruner = preload("res://src/storage/cache_pruner.gd")
const MAX_SCOPE_BYTES := 256 * 1024 * 1024
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
var _local_source := Callable()
func _init(root: String = "user://images",logger: RefCounted = null) -> void:
	_root = root
	_logger = logger
## Python 媒体目录由装配层注入；未选择或目录失效时返回空串即可。
func set_local_source(provider: Callable) -> void:
	_local_source = provider
func get_directory() -> String:
	return _directory
## 批量导入后让已加载的气泡重新问一次磁盘；无状态的条目会直接命中新缓存。
func refresh(ids: Array) -> void:
	for value in ids:
		var id := str(value)
		if id.is_empty():
			continue
		_states.erase(id)
		_volatile.erase(id)
		ensure(id)
func start(session: Dictionary) -> void:
	stop()
	var server := ServerAddress.normalize(str(session.get("server","")))
	if server.is_empty() or not session.get("username") is String or not session.get("message_token") is String or session.username.is_empty() or session.message_token.is_empty():
		return
	if not ServerAddress.allows_insecure(server):
		return
	_session = {"server":server,"username":session.username,"token":session.message_token}
	_directory = _root.path_join(AccountScope.key(server, session.username))
	_prune_scope_bytes()
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
	var cached := _cached(id)
	if cached != null:
		_ready_image(id,cached,"")
		return
	var imported := _local_source_bytes(id)
	if not imported.is_empty():
		var local := _decode(imported)
		if local != null:
			var result := _save(id,imported)
			_ready_image(id,local,"" if result == OK else "CACHE_WRITE_FAILED")
			return
	_states[id] = {"status":"loading","texture":null,"original_size":Vector2i.ZERO,"code":""}
	changed.emit(id,get_state(id))
	_queue.append(id)
	_pump()
## 本地发送的图片只有本地副本，缺失即不可用，不回源服务器。
func ensure_local(id: String) -> void:
	if id.is_empty() or _session.is_empty() or _states.has(id):
		return
	var cached := _cached(id)
	if cached == null:
		_error(id,"IMAGE_MISSING")
		return
	_ready_image(id,cached,"")
func _cached(id: String) -> Image:
	if _directory.is_empty():
		return null
	var path := _path(id)
	if not FileAccess.file_exists(path):
		return null
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return null
	if file.get_length() > Codec.MAX_BYTES:
		file.close()
		DirAccess.remove_absolute(path)
		return null
	var bytes := file.get_buffer(file.get_length())
	file.close()
	var image := _decode(bytes)
	if image == null:
		DirAccess.remove_absolute(path)
	return image
func retry(id: String) -> void:
	if get_state(id).status == "error":
		_states.erase(id)
		ensure(id)
func preview(id: String) -> Texture2D:
	var image: Image = _volatile.get(id)
	if image == null:
		image = _cached(id)
	if image == null:
		_error(id,"INVALID_IMAGE")
		return null
	return ImageTexture.create_from_image(image)
func _pump() -> void:
	while _active.size()<3 and not _queue.is_empty():
		var id: String = _queue.pop_front()
		var http := HTTPRequest.new()
		var generation := _generation
		var started := Time.get_ticks_usec()
		var trace_id := Schema.new_trace_id("img")
		_active[id] = http
		http.timeout = 15
		http.body_size_limit = 16*1024*1024
		http.max_redirects = 0
		add_child(http)
		http.request_completed.connect(_on_completed.bind(http, id, generation, started, trace_id))
		var error := http.request(_session.server+"/get_image",PackedStringArray(["Content-Type: application/json"]),HTTPClient.METHOD_POST,JSON.stringify({"username":_session.username,"token":_session.token,"uuid":id}))
		if error != OK:
			_active.erase(id)
			http.queue_free()
			_log_access(0, 0, started, trace_id, "failure", Events.request_error_detail(error))
			_error(id,"NETWORK_ERROR",Events.request_error_detail(error))

func _on_completed(result: int, status: int, _headers: PackedStringArray, body: PackedByteArray,
		http: HTTPRequest, id: String, generation: int, started: int, trace_id: String) -> void:
	if generation != _generation:
		return
	_active.erase(id)
	http.queue_free()
	var success := result == HTTPRequest.RESULT_SUCCESS and status == 200
	var detail := _failure_detail(result, status, body)
	_log_access(status, body.size(), started, trace_id, "success" if success else "failure", detail)
	if success:
		_decode_fetched(id, body, started, trace_id)
	else:
		_error(id, "NETWORK_ERROR", detail)
	_pump()

func _failure_detail(result: int, status: int, body: PackedByteArray) -> String:
	if result != HTTPRequest.RESULT_SUCCESS:
		return Events.http_result_name(result)
	if status != 200:
		return Events.http_failure_detail(body, status)
	return ""

func _decode_fetched(id: String, body: PackedByteArray, started: int, trace_id: String) -> void:
	var decode_started := Time.get_ticks_usec()
	var image := _decode(body)
	_log_performance("decode", Time.get_ticks_usec() - decode_started, body.size(),
		"success" if image != null else "failure", trace_id)
	if image == null:
		_error(id, "INVALID_IMAGE", "image payload could not be decoded")
		return
	var saved := _save(id, body)
	if saved != OK:
		_volatile[id] = image
	_ready_image(id, image, "" if saved == OK else "CACHE_WRITE_FAILED")
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
		_logger.record_as("storage", "storage_history_image_ready", {"scope":"file", "operation":"image_fetch",
			"outcome":"success" if code.is_empty() else "failure", "duration_ms":0,
			"reply_id":id, "code":"OK" if code.is_empty() else code, "phase":"complete"})

func _error(id: String,code: String,detail: String = "") -> void:
	_states[id] = {"status":"error","texture":null,"original_size":Vector2i.ZERO,"code":code}
	changed.emit(id,get_state(id))
	if _logger != null:
		_logger.record_as("storage", "storage_history_image_failed", {"scope":"file", "operation":"image_fetch",
			"outcome":"failure", "duration_ms":0, "reply_id":id, "code":code, "detail":detail,
			"phase":"error", "level":"ERROR"})
func _save(id: String,bytes: PackedByteArray) -> Error:
	var started := Time.get_ticks_usec()
	var transaction_id := Schema.new_transaction_id()
	var error := DirAccess.make_dir_recursive_absolute(_directory)
	if error != OK:
		_log_transaction(transaction_id, "history_image_save", false, started, error)
		return error
	var path := _path(id)
	error = AtomicFile.write_bytes(path, bytes)
	_log_transaction(transaction_id, "history_image_save", error == OK, started, error)
	if error == OK:
		_prune_scope_bytes()
	return error
func _log_access(status: int, bytes: int, started: int, trace_id: String, outcome: String, detail: String = "") -> void:
	var response := {"ok":outcome == "success", "code":"OK" if outcome == "success" else "NETWORK_ERROR",
		"status":status, "detail":detail}
	Events.http(_logger, response, status, bytes, started, trace_id, "/get_image", "POST")
func _log_performance(operation: String, duration_us: int, bytes: int, outcome: String, trace_id: String) -> void:
	if _logger == null:
		return
	_logger.record_as("storage", "storage_image_operation", {"scope":"file", "operation":operation,
		"outcome":outcome, "duration_ms":int(duration_us / 1000), "bytes":bytes,
		"code":"OK" if outcome == "success" else "INVALID_IMAGE", "phase":"complete"})
func _log_transaction(transaction_id: String, operation: String, success: bool, started: int, error: int) -> void:
	Events.file_transaction(_logger, "history", operation, transaction_id, success, started,
		"OK" if success else "CACHE_WRITE_FAILED", {"detail":"" if success else error_string(error)})
func _path(id: String) -> String:
	return _directory.path_join(id.sha256_text()+".image")


## 按文件修改时间淘汰旧图片；不读取图片内容，也不影响当前内存纹理。
func _prune_scope_bytes() -> void:
	Pruner.prune(
		_directory,
		func(name): return name.ends_with(".image"),
		func(item): return DirAccess.remove_absolute(str(item.path)),
		MAX_SCOPE_BYTES,
	)
func _decode(bytes: PackedByteArray) -> Image:
	return Codec.decode(bytes)
func _local_source_bytes(id: String) -> PackedByteArray:
	if not _local_source.is_valid():
		return PackedByteArray()
	var directory := str(_local_source.call())
	if directory.is_empty() or directory == _directory:
		return PackedByteArray()
	var path := Locator.find_image(directory,id)
	if path.is_empty():
		return PackedByteArray()
	var file := FileAccess.open(path,FileAccess.READ)
	if file == null or file.get_length() > Codec.MAX_BYTES:
		if file != null:
			file.close()
		return PackedByteArray()
	var bytes := file.get_buffer(file.get_length())
	file.close()
	return bytes
func _exit_tree() -> void:
	stop()
