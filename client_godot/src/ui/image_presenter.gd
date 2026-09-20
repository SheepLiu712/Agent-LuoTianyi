extends Node
const ImageScene = preload("res://scenes/ui/image_window.tscn")
var _window: Window
var _geometry_path: String
func _init(geometry_path: String = "user://window-geometry.cfg") -> void:
	_geometry_path = geometry_path
func open_image(source: Window, provider: Callable, confirm: Callable = Callable()) -> Window:
	if not is_instance_valid(_window):
		_window = ImageScene.instantiate()
		source.add_child(_window)
		_window.get_node("%Chrome").configure(_geometry_path,"image")
	elif _window.get_parent() != source:
		_window.hide()
		_window.transient = false
		_window.reparent(source)
		_window.transient = true
	_window.present(source,provider,confirm)
	return _window
func close() -> void:
	if is_instance_valid(_window): _window.close_image()
func close_confirmation(source: Window) -> void:
	if is_instance_valid(_window) and _window.get_parent() == source and _window.get_node("%ConfirmImage").visible:
		_window.close_requested.emit()
func _exit_tree() -> void:
	if is_instance_valid(_window): _window.queue_free()
