extends RefCounted
## 历史图片导入器：把 Python 客户端 `temp/images/<uuid>.<ext>` 复制成
## 当前账号的 `<sha256(uuid)>.image`。源文件只读，已有缓存不覆盖。

const Locator = preload("res://src/storage/python_client_locator.gd")
const Codec = preload("res://src/storage/history_image_codec.gd")
const EXTENSION := ".image"
const TEMP_EXTENSION := ".import.tmp"


static func import_file(cache_directory: String, id: String, source: String) -> Dictionary:
	if cache_directory.is_empty() or not Locator.is_uuid(id):
		return _result("failed", "INVALID_INPUT")
	var target := cache_directory.path_join(id.sha256_text() + EXTENSION)
	if FileAccess.file_exists(target):
		return _result("skipped", "ALREADY_CACHED")
	var bytes := _read(source)
	if bytes.is_empty():
		return _result("failed", "SOURCE_UNREADABLE")
	if Codec.decode(bytes) == null:
		return _result("failed", "UNSUPPORTED_IMAGE")
	if not _write(cache_directory, target, bytes):
		return _result("failed", "CACHE_WRITE_FAILED")
	return _result("imported", "OK")


static func _read(path: String) -> PackedByteArray:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return PackedByteArray()
	var length := file.get_length()
	if length <= 0 or length > Codec.MAX_BYTES:
		file.close()
		return PackedByteArray()
	var bytes := file.get_buffer(length)
	file.close()
	return bytes


static func _write(directory: String, target: String, bytes: PackedByteArray) -> bool:
	if DirAccess.make_dir_recursive_absolute(directory) != OK:
		return false
	var temporary := target + TEMP_EXTENSION
	var file := FileAccess.open(temporary, FileAccess.WRITE)
	if file == null:
		return false
	file.store_buffer(bytes)
	file.flush()
	var error := file.get_error()
	file.close()
	if error == OK:
		error = DirAccess.rename_absolute(temporary, target)
	if error != OK:
		DirAccess.remove_absolute(temporary)
		return false
	return true


static func _result(status: String, code: String) -> Dictionary:
	return {"status":status, "code":code}
