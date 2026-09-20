extends Control
const Geometry = preload("res://src/storage/window_geometry.gd")
var _window: Window
var _store: RefCounted
var _key := ""
var _normal := Rect2i()
var _maximized := false
var _last := {}
var _quiet := 0.0

func _ready() -> void:
	_window = get_window()
	_window.borderless = false
	_window.gui_embed_subwindows = true
	_window.close_requested.connect(_save)
	_normal = Rect2i(_window.position,_window.size)
func _expanded_mode() -> bool:
	return _window.mode in [Window.MODE_MAXIMIZED,Window.MODE_FULLSCREEN,Window.MODE_EXCLUSIVE_FULLSCREEN]

func configure(path: String, key: String) -> void:
	_store = Geometry.new(path)
	_key = key
	_restore(_window.size,_window.min_size)

func select_layout(key: String, default_size: Vector2i, minimum: Vector2i) -> void:
	_save()
	_key = key
	_restore(default_size,minimum)

func _restore(default_size: Vector2i, minimum: Vector2i) -> void:
	var screens: Array[Rect2i] = []
	if DisplayServer.get_name() != "headless":
		for index in DisplayServer.get_screen_count():
			screens.append(DisplayServer.screen_get_usable_rect(index))
	var fallback := Rect2i(_window.position + (_window.size-default_size)/2,default_size)
	var state: Dictionary = _store.read_layout(_key,fallback,minimum,screens) if _store != null else {"rect":fallback,"maximized":false}
	_window.mode = Window.MODE_WINDOWED
	_window.min_size = minimum
	_window.size = state.rect.size
	_window.position = state.rect.position
	_normal = state.rect
	_maximized = state.maximized
	if _maximized: _window.mode = Window.MODE_MAXIMIZED
	_last = {"rect":_normal,"maximized":_maximized}
	_clamp_visible_frame.call_deferred()

func open_window() -> void:
	if _window.mode == Window.MODE_MINIMIZED:
		# Recreate the visible native surface: mode alone can leave a borderless HWND hidden.
		if _window != get_tree().root: _window.hide()
		_window.mode = Window.MODE_MAXIMIZED if _maximized else Window.MODE_WINDOWED
	_window.show()
	_window.grab_focus()
	_clamp_visible_frame.call_deferred()

func _clamp_visible_frame() -> void:
	if DisplayServer.get_name() == "headless" or not is_instance_valid(_window) or _window.is_embedded() or not _window.visible or _window.mode != Window.MODE_WINDOWED: return
	var outer_position := _window.get_position_with_decorations()
	var outer_size := _window.get_size_with_decorations()
	var work := DisplayServer.screen_get_usable_rect(_window.current_screen)
	var visible_position := Vector2i(clampi(outer_position.x, work.position.x, maxi(work.position.x, work.end.x - outer_size.x)), clampi(outer_position.y, work.position.y, maxi(work.position.y, work.end.y - outer_size.y)))
	_window.position += visible_position - outer_position
	_normal = Rect2i(_window.position, _window.size)

func _process(delta: float) -> void:
	if _window == null: return
	if not _window.visible or _window.mode == Window.MODE_MINIMIZED: return
	_maximized = _expanded_mode()
	if not _maximized: _normal = Rect2i(_window.position,_window.size)
	var current := {"rect":_normal,"maximized":_maximized}
	if current != _last:
		_last = current
		_quiet = .4
	elif _quiet > 0:
		_quiet -= delta
		if _quiet <= 0: _save()

func _save() -> void:
	if _store != null and not _key.is_empty():
		if _window != null and _window.mode != Window.MODE_MINIMIZED: _maximized = _expanded_mode()
		if _window != null and _window.mode == Window.MODE_WINDOWED and _window.visible:
			_normal = Rect2i(_window.position,_window.size)
		var error: Error = _store.write_layout(_key,_normal,_maximized)
		if error != OK: push_warning("Window geometry could not be saved (%s)" % error)

func _exit_tree() -> void:
	_save()
