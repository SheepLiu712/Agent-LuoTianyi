extends "res://src/platform/input_service.gd"
func is_composing() -> bool:
	return DisplayServer.has_feature(DisplayServer.FEATURE_IME) and not DisplayServer.ime_get_text().is_empty()
func has_clipboard_image() -> bool:
	return DisplayServer.has_feature(DisplayServer.FEATURE_CLIPBOARD) and DisplayServer.clipboard_has_image()
func get_clipboard_image() -> Image:
	return DisplayServer.clipboard_get_image() if has_clipboard_image() else null
func copy_text(text: String) -> Error:
	if not DisplayServer.has_feature(DisplayServer.FEATURE_CLIPBOARD): return ERR_UNAVAILABLE
	DisplayServer.clipboard_set(text)
	return OK
