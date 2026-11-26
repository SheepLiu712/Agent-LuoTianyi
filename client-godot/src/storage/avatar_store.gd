extends RefCounted
## 头像只存本地：每个账号一份 PNG，读回成纹理交给界面，避免 UI 直接碰文件系统。
const Attachment = preload("res://src/media/image_attachment.gd")
const AvatarImage = preload("res://src/media/avatar_image.gd")
const AccountScope = preload("res://src/domain/account_scope.gd")
const ALLOWED_MIME := ["image/png", "image/jpeg", "image/webp"]
const FILE := "avatar.png"
var _root := ""
var _directory := ""
var _logger: RefCounted

func _init(root: String = "user://avatar", logger: RefCounted = null) -> void:
	_root = root
	_logger = logger

func set_scope(server: String, username: String) -> void:
	var scope := AccountScope.key(server, username)
	_directory = _root.path_join(scope) if not scope.is_empty() else ""

func path() -> String:
	return "" if _directory.is_empty() else _directory.path_join(FILE)

func has_avatar() -> bool:
	return not path().is_empty() and FileAccess.file_exists(path())

func load_texture() -> Texture2D:
	if not has_avatar():
		return null
	var image := Image.load_from_file(ProjectSettings.globalize_path(path()))
	if image == null:
		return null
	return ImageTexture.create_from_image(image)

## 选图对话框只给路径，读盘留在这里，界面层因此不必碰文件系统。
func read_bytes(path: String) -> PackedByteArray:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return PackedByteArray()
	var bytes := file.get_buffer(file.get_length())
	file.close()
	return bytes

func save(bytes: PackedByteArray) -> Dictionary:
	if _directory.is_empty():
		return _result("NO_ACCOUNT", "no active account scope")
	if bytes.size() > Attachment.MAX_BYTES:
		return _result("IMAGE_TOO_LARGE", "image exceeds %d bytes" % Attachment.MAX_BYTES)
	# 先按魔数过滤格式，再解码：不支持的格式根本不该走进解码器。
	if Attachment.detect_mime(bytes) not in ALLOWED_MIME:
		return _result("IMAGE_FORMAT", "unsupported image format")
	var attachment := Attachment.from_bytes(bytes, "")
	if not attachment.ok:
		return _result(str(attachment.code), str(attachment.get("detail", "image validation failed")))
	var source: Image = attachment.texture.get_image()
	if source == null:
		return _result("IMAGE_FORMAT", "decoded image is unavailable")
	var squared := AvatarImage.fit_square(source)
	var written := _write(squared)
	if written != OK:
		return _result("AVATAR_WRITE_FAILED", error_string(written))
	return {"ok": true, "code": "OK", "texture": ImageTexture.create_from_image(squared)}

func clear() -> Error:
	if not has_avatar():
		return OK
	var error := DirAccess.remove_absolute(ProjectSettings.globalize_path(path()))
	if error != OK and _logger != null:
		_logger.record_as("storage", "storage_avatar_clear_failed", {"scope":"file", "operation":"avatar_clear",
			"outcome":"failure", "duration_ms":0, "code":"AVATAR_WRITE_FAILED",
			"detail":error_string(error), "phase":"error", "level":"ERROR"})
	return error

## 先写临时文件再整体改名：中途失败不会留下半张头像。
func _write(image: Image) -> Error:
	var directory := ProjectSettings.globalize_path(_directory)
	var made := DirAccess.make_dir_recursive_absolute(directory)
	if made != OK and not DirAccess.dir_exists_absolute(directory):
		return made
	var target := ProjectSettings.globalize_path(path())
	var temporary := target + ".tmp"
	var error := image.save_png(temporary)
	if error != OK:
		return error
	if DirAccess.rename_absolute(temporary, target) != OK:
		DirAccess.remove_absolute(temporary)
		return ERR_FILE_CANT_WRITE
	return OK

func _result(code: String, detail: String = "") -> Dictionary:
	if code != "OK" and _logger != null:
		_logger.record_as("storage", "storage_avatar_save_failed", {"scope":"file", "operation":"avatar_save",
			"outcome":"failure", "duration_ms":0, "code":code, "detail":detail, "phase":"error", "level":"ERROR"})
	return {"ok": false, "code": code, "detail": detail, "texture": null}
