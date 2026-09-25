extends Node
const ImageScene = preload("res://scenes/ui/image_window.tscn")
var _window: Window
var _geometry: Resource
var _window_system: Resource
func _init(geometry: Resource = null, window_system: Resource = null) -> void:
	_geometry = geometry
	_window_system = window_system if window_system != null else preload("res://src/platform/window_system.gd").new()
func open_image(source: Window, provider: Callable, confirm: Callable = Callable()) -> Window:
	if not is_instance_valid(_window):
		_window = ImageScene.instantiate()
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
