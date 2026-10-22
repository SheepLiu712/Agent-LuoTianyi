extends Node
const ImageScene = preload("res://scenes/ui/image_window.tscn")
var _window: Window
var _geometry: Resource
var _window_system: Resource
var _ui_style: RefCounted

func set_ui_style(style: RefCounted) -> void:
	_ui_style = style
	if is_instance_valid(_window): _style_window()

func _style_window() -> void:
	if _ui_style != null:
		_ui_style.apply_view(_window, {"ZoomIn":"zoom_in", "ZoomOut":"zoom_out", "FitImage":"zoom_fit", "OriginalSize":"zoom_1to1", "CloseImage":"action_close", "ConfirmImage":"action_send"})
func _init(geometry: Resource = null, window_system: Resource = null) -> void:
	_geometry = geometry
	_window_system = window_system if window_system != null else preload("res://src/platform/window_system.gd").new()
func open_image(source: Window, provider: Callable, confirm: Callable = Callable()) -> Window:
	if not is_instance_valid(_window):
		_window = ImageScene.instantiate()
		_style_window()
		source.add_child(_window)
		_window.get_node("%Chrome").configure(_geometry,"image")
	elif _window.get_parent() != source:
		_window_system.reparent_image(_window,source)
	_window.present(source,provider,confirm)
	return _window
func close() -> void:
	if is_instance_valid(_window): _window.close_image()
func close_confirmation(source: Window) -> void:
	if is_instance_valid(_window) and _window.get_parent() == source and _window.get_node("%ConfirmImage").visible:
		_window.close_requested.emit()
func _exit_tree() -> void:
	if is_instance_valid(_window): _window.queue_free()
