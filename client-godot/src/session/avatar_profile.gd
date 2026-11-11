extends Node
## 头像的账号态：登录时读回本机图片，变更后向聊天气泡与动态同时扇出。
## 存储由装配层注入，所以这里既不碰文件系统，也不依赖具体存储实现。
signal avatar_changed(texture: Texture2D)
var _store: RefCounted
var _logger: RefCounted
var _texture: Texture2D
var _username := ""

func _init(store: RefCounted, logger: RefCounted = null) -> void:
	_store = store
	_logger = logger

func start(session: Dictionary) -> void:
	_username = str(session.get("username", ""))
	_store.set_scope(str(session.get("server", "")), _username)
	_texture = _store.load_texture()
	avatar_changed.emit(_texture)

func stop() -> void:
	_store.set_scope("", "")
	_texture = null
	_username = ""
	avatar_changed.emit(null)

func get_texture() -> Texture2D:
	return _texture

func get_username() -> String:
	return _username

func has_custom() -> bool:
	return _texture != null

func apply_bytes(bytes: PackedByteArray) -> Dictionary:
	var result: Dictionary = _store.save(bytes)
	if result.ok:
		_texture = result.texture
		avatar_changed.emit(_texture)
	_log(str(result.code))
	return {"ok": result.ok, "code": result.code}

## 头像页拿到的是路径而不是字节：读盘交给存储，这里只做结果归一。
func apply_file(path: String) -> Dictionary:
	var bytes: PackedByteArray = _store.read_bytes(path)
	if bytes.is_empty():
		_log("IMAGE_READ_FAILED")
		return {"ok": false, "code": "IMAGE_READ_FAILED"}
	return apply_bytes(bytes)

func reset() -> Dictionary:
	var error: Error = _store.clear()
	if error != OK:
		return {"ok": false, "code": "AVATAR_WRITE_FAILED"}
	_texture = null
	avatar_changed.emit(null)
	return {"ok": true, "code": "OK"}

func _log(code: String) -> void:
	if _logger != null:
		if code == "OK":
			_logger.log_info("info_avatar_apply", {"code":code, "phase":"complete"})
		else:
			_logger.log_error("error_avatar_save", {"code":code, "detail":code, "phase":"error"})
