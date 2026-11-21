extends "res://src/network/ca_bundle_reader.gd"
## Godot 平台实现：唯一读取 CA 文件并让引擎解析信任链的位置。


func read(path: String) -> Dictionary:
	if path.is_empty() or not FileAccess.file_exists(path):
		return {"present": false, "bytes": PackedByteArray(), "loaded": false}
	var bytes := FileAccess.get_file_as_bytes(path)
	return {
		"present": true,
		"bytes": bytes,
		"loaded": X509Certificate.new().load(path) == OK,
	}
