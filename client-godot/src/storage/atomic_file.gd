extends RefCounted
## 统一的临时文件 -> flush -> rename 写入；失败时清理临时文件。

static func write_bytes(path: String, bytes: PackedByteArray) -> Error:
	var directory := path.get_base_dir()
	if not directory.is_empty():
		var made := DirAccess.make_dir_recursive_absolute(directory)
		if made != OK:
			return made
	var temporary := path + ".tmp"
	var file := FileAccess.open(temporary, FileAccess.WRITE)
	if file == null:
		return FileAccess.get_open_error()
	file.store_buffer(bytes)
	file.flush()
	var error := file.get_error()
	file.close()
	if error == OK:
		error = DirAccess.rename_absolute(temporary, path)
	if error != OK and FileAccess.file_exists(temporary):
		DirAccess.remove_absolute(temporary)
	return error


static func write_text(path: String, text: String) -> Error:
	return write_bytes(path, text.to_utf8_buffer())
