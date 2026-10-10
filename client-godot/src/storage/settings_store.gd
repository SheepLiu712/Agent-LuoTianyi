extends Resource
## Settings values only. Platform paths and serialization belong to implementations.
func load_settings() -> Error:
	return ERR_UNAVAILABLE
func get_value(_section: String, _key: String, fallback: Variant = null) -> Variant:
	return fallback
func set_value(_section: String, _key: String, _value: Variant) -> void:
	pass
func save_settings() -> Error:
	return ERR_UNAVAILABLE
