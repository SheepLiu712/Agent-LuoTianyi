extends RefCounted
## 运行时诊断与构建脚本共用；用户数据目录不变。
static func get_info() -> Dictionary:
	return JSON.parse_string(FileAccess.get_file_as_string("res://release.json"))

static func title() -> String:
	var info := get_info()
	return "%s %s" % [info.product, info.version]
