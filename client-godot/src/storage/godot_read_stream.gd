extends "res://src/storage/read_stream.gd"
var _file: FileAccess
func _init(file: FileAccess) -> void:
	_file = file
func get_buffer(size: int) -> PackedByteArray:
	return _file.get_buffer(size) if _file != null else PackedByteArray()
func get_length() -> int:
	return _file.get_length() if _file != null else 0
func get_position() -> int:
	return _file.get_position() if _file != null else 0
func close() -> void:
	if _file != null: _file.close()
	_file = null
