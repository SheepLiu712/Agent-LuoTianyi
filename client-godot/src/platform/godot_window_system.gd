extends "res://src/platform/window_system.gd"
func minimized(window: Window) -> bool:
	return window.mode == Window.MODE_MINIMIZED
func windowed(window: Window) -> bool:
	return window.mode == Window.MODE_WINDOWED
func geometry(window: Window) -> Rect2i:
	return Rect2i(window.position,window.size)
func focus(window: Window) -> void:
	window.grab_focus()
func focused(window: Window) -> bool:
	return window.has_focus() and not minimized(window)
func drag(window: Window) -> void:
	window.start_drag()
func reparent_image(window: Window, source: Window) -> void:
	window.hide()
	window.transient = false
	window.reparent(source)
	window.transient = true
