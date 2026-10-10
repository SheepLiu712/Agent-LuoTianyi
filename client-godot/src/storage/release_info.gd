extends RefCounted
## Shared by runtime diagnostics and the build script; user data path is unchanged.
static func get_info() -> Dictionary:
	return JSON.parse_string(FileAccess.get_file_as_string("res://release.json"))

static func title() -> String:
	var info := get_info()
	return "%s %s" % [info.product, info.version]
