extends Control
const Geometry = preload("res://src/storage/window_geometry.gd")
@onready var _title: Label = %WindowTitle
@onready var _maximize: Button = %WindowMaximize
var _window: Window
var _store: RefCounted
var _key := ""
var _normal := Rect2i()
var _maximized := false
var _last := {}
var _quiet := 0.0
var _drag_pending := false
var _drag_origin := Vector2.ZERO

func _ready() -> void:
	_window = get_window()
	_window.borderless = true
	_window.gui_embed_subwindows = true
	_window.close_requested.connect(_save)
	_normal = Rect2i(_window.position,_window.size)
	%WindowMinimize.pressed.connect(func(): _window.mode = Window.MODE_MINIMIZED)
	_maximize.pressed.connect(_toggle_maximize)
	%WindowClose.pressed.connect(func(): _window.close_requested.emit())
	%TitleBar.gui_input.connect(_title_input)
	for edge in $Edges.get_children():
		edge.gui_input.connect(func(event):
			if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT and _window.mode == Window.MODE_WINDOWED:
				_window.start_resize(edge.get_meta("edge"))
				accept_event())

func _title_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
		_drag_pending = event.pressed and not event.double_click
		_drag_origin = event.position
		if event.pressed and event.double_click: _toggle_maximize()
		accept_event()
	elif event is InputEventMouseMotion and _drag_pending and Input.is_mouse_button_pressed(MOUSE_BUTTON_LEFT):
		if event.position.distance_to(_drag_origin) >= 4:
			_drag_pending = false
			if _expanded_mode():
				var fraction := clampf(event.position.x/maxf(%TitleBar.size.x,1),.1,.9)
				_toggle_maximize()
				_window.position = DisplayServer.mouse_get_position()-Vector2i(int(_normal.size.x*fraction),roundi(_drag_origin.y*_window.get_final_transform().get_scale().y))
			_window.start_drag()
			accept_event()

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

func open_window() -> void:
	if _window.mode == Window.MODE_MINIMIZED:
		# Recreate the visible native surface: mode alone can leave a borderless HWND hidden.
		if _window != get_tree().root: _window.hide()
		_window.mode = Window.MODE_MAXIMIZED if _maximized else Window.MODE_WINDOWED
	_window.show()
	_window.grab_focus()

func _toggle_maximize() -> void:
	if _expanded_mode():
		_window.mode = Window.MODE_WINDOWED
		_window.size = _normal.size
		_window.position = _normal.position
		_maximized = false
	else:
		_normal = Rect2i(_window.position,_window.size)
		_maximized = true
		_window.mode = Window.MODE_MAXIMIZED

func _process(delta: float) -> void:
	if _window == null: return
	_title.text = _window.title
	_maximize.text = "❐" if _expanded_mode() else "□"
	_maximize.tooltip_text = "还原" if _expanded_mode() else "最大化"
	$Edges.visible = _window.mode == Window.MODE_WINDOWED
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
		if error != OK: _title.tooltip_text = "窗口位置无法保存（%s）" % error

func _exit_tree() -> void:
	_save()
