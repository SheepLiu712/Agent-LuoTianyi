extends Resource
## 跨平台系统输入；TextEdit 自身的 IME 状态由视图判定。
func is_composing() -> bool:
	return false
func has_clipboard_image() -> bool:
	return false
func get_clipboard_image() -> Image:
	return null
func copy_text(_text: String) -> Error:
	return ERR_UNAVAILABLE
func create_ime_controller() -> Object:
	return null
func set_ime_active(_active: bool) -> void:
	pass
