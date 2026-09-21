extends Resource
## Cross-platform system input. TextEdit's own IME state is checked by the view.
func is_composing() -> bool:
	return false
func has_clipboard_image() -> bool:
	return false
func get_clipboard_image() -> Image:
	return null
func copy_text(_text: String) -> Error:
	return ERR_UNAVAILABLE
