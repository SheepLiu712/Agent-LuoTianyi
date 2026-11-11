extends Resource
## 只负责设置值；平台路径与序列化归具体实现。
func load_settings() -> Error:
	return ERR_UNAVAILABLE
func get_value(_section: String, _key: String, fallback: Variant = null) -> Variant:
	return fallback
func set_value(_section: String, _key: String, _value: Variant) -> void:
	pass
func save_settings() -> Error:
	return ERR_UNAVAILABLE
