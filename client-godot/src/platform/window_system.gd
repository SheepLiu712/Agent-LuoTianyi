extends Resource
func minimized(_window: Window) -> bool:
	return false
func windowed(_window: Window) -> bool:
	return false
func geometry(_window: Window) -> Rect2i:
	return Rect2i()
func focus(_window: Window) -> void:
	pass
func focused(_window: Window) -> bool:
	return false
func drag(_window: Window) -> void:
	pass
func reparent_image(_window: Window, _source: Window) -> void:
	pass
