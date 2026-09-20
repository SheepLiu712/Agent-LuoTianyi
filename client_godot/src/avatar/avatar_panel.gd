extends Control
signal touched(areas: Array[String])
## View owns pointer gestures; framing owns the persisted transform.
const Driver = preload("res://src/avatar/avatar_driver.gd")
const Framing = preload("res://src/avatar/avatar_framing.gd")
const SETTINGS := "user://avatar_framing.cfg"
const Ripple := preload("res://scenes/avatar/touch_ripple.tscn")
@onready var avatar: Driver = %Driver
@onready var _error_label: Label = %Error
@onready var _reset_button: Button = %Reset
var framing = Framing.new()
var _dragging := false


func _ready() -> void:
	if avatar.load_character("res://assets/live2d/character.json") != OK:
		_error_label.text = "角色加载失败，请检查资源是否完整。"
		return
	var restored: Error = framing.load_settings(SETTINGS)
	if restored != OK and restored != ERR_FILE_NOT_FOUND:
		_error_label.text = "未能恢复角色位置，已使用默认构图。"
	resized.connect(_layout_avatar)
	_layout_avatar()
	gui_input.connect(_handle_pointer)
	mouse_exited.connect(func(): avatar.set_gaze(Vector2.ZERO))
	_reset_button.visible = true
	_reset_button.position = Vector2(18, size.y - 50)
	_reset_button.pressed.connect(func():
		framing.reset()
		_layout_avatar()
		_save())
	resized.connect(func(): _reset_button.position = Vector2(18, size.y - 50))


func _layout_avatar() -> void:
	if avatar.get_status().loaded:
		avatar.transform = framing.get_transform(size, avatar.get_status().canvas_size)
	_error_label.size.x = maxf(0, size.x - 40)


func _handle_pointer(event: InputEvent) -> void:
	if event is InputEventMouseButton:
		if event.button_index == MOUSE_BUTTON_LEFT and event.pressed:
			var local := avatar.to_local(get_global_transform() * event.position)
			var areas: Array[String] = avatar.hit_test(local)
			if not areas.is_empty():
				var ripple := Ripple.instantiate() as Control
				ripple.position = event.position - Vector2(60, 60)
				add_child(ripple)
				touched.emit(areas)
			accept_event()
		elif event.button_index == MOUSE_BUTTON_RIGHT:
			_dragging = event.pressed
			if not _dragging:
				_save()
			accept_event()
		elif event.pressed and event.button_index in [MOUSE_BUTTON_WHEEL_UP, MOUSE_BUTTON_WHEEL_DOWN]:
			framing.zoom_by(1.1 if event.button_index == MOUSE_BUTTON_WHEEL_UP else 1.0 / 1.1)
			_layout_avatar()
			_save()
			accept_event()
	elif event is InputEventMouseMotion:
		if size.x > 0 and size.y > 0:
			avatar.set_gaze(Vector2(event.position.x / size.x * 2 - 1, 1 - event.position.y / size.y * 2))
		if _dragging:
			if not Input.is_mouse_button_pressed(MOUSE_BUTTON_RIGHT):
				_dragging = false
				_save()
				return
			framing.pan_by(event.relative, size)
			_layout_avatar()
			accept_event()


func _save() -> void:
	if framing.save_settings(SETTINGS) != OK:
		_error_label.text = "当前角色位置无法保存，重启后将恢复上次设置。"


func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_WINDOW_FOCUS_OUT and is_instance_valid(avatar):
		avatar.set_gaze(Vector2.ZERO)
	if what == NOTIFICATION_WM_WINDOW_FOCUS_OUT and _dragging:
		_dragging = false
		_save()


func _process(_delta: float) -> void:
	var minimized := get_window().mode == Window.MODE_MINIMIZED
	avatar.visible = not minimized
	avatar.process_mode = Node.PROCESS_MODE_DISABLED if minimized else Node.PROCESS_MODE_INHERIT
