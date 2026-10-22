extends Control
@export var window_system: Resource = preload("res://src/platform/window_system.gd").new()
signal touched(areas: Array[String])
## View owns pointer gestures; framing owns the persisted transform.
const Driver = preload("res://src/avatar/avatar_driver.gd")
const Framing = preload("res://src/avatar/avatar_framing.gd")
@export var settings: Resource = preload("res://src/storage/settings_store.gd").new()
const Ripple := preload("res://scenes/avatar/touch_ripple.tscn")
@onready var avatar: Driver = %Driver
@onready var _error_label: Label = %Error
@onready var _reset_button: Button = %Reset
var framing: RefCounted
var _dragging := false
var _ui_style: RefCounted
var _reset_styles: Array[StyleBoxFlat] = []

func set_unread_dynamic(post: Dictionary) -> void:
	%Heading.visible = not post.is_empty()
	if post.is_empty():
		get_node("Heading/Identity/Companion").text = ""
		%Heading.tooltip_text = ""
		return
	get_node("Heading/Identity/Name").text = "%s · 未读动态" % post.get("author_name", "洛天依")
	get_node("Heading/Identity/Companion").text = post.get("content", "")
	%Heading.tooltip_text = post.get("content", "")

func set_ui_style(style: RefCounted) -> void:
	if _ui_style != null and _ui_style.style_changed.is_connected(_apply_ui_style):
		_ui_style.style_changed.disconnect(_apply_ui_style)
	_ui_style = style
	_ui_style.style_changed.connect(_apply_ui_style)
	if is_node_ready(): _apply_ui_style()

func _apply_ui_style() -> void:
	if _ui_style == null or not is_node_ready(): return
	var heading := %Heading.get_theme_stylebox("panel") as StyleBoxFlat
	_ui_style.apply_surface_style(heading)
	heading.bg_color = Color(1, 1, 1, 0.82 if _ui_style.is_crystal() else 0.94)
	for reset_style in _reset_styles:
		_ui_style.apply_surface_style(reset_style)
	var border := get_node("Border").get_theme_stylebox("panel") as StyleBoxFlat
	_ui_style.apply_surface_style(border)
	border.bg_color = Color(0, 0, 0, 0)
	get_node("Stage/Background").material.set_shader_parameter("corner_radius", 12.0 if _ui_style.is_crystal() else 8.0)


func _ready() -> void:
	for state in ["normal", "hover", "pressed"]:
		var reset_style := _reset_button.get_theme_stylebox(state).duplicate() as StyleBoxFlat
		reset_style.content_margin_left = 12
		reset_style.content_margin_right = 12
		reset_style.content_margin_top = 8
		reset_style.content_margin_bottom = 8
		reset_style.bg_color = {"normal":Color(1, 1, 1, 0.94), "hover":Color(0.94, 0.98, 1, 1), "pressed":Color(0.86, 0.95, 1, 1)}[state]
		_reset_button.add_theme_stylebox_override(state, reset_style)
		_reset_styles.append(reset_style)
	_apply_ui_style()
	framing = Framing.new(settings)
	if avatar.load_character("res://assets/live2d/character.json") != OK:
		_error_label.text = "角色加载失败，请检查资源是否完整。"
		return
	var restored: Error = framing.load_settings()
	if restored != OK and restored != ERR_FILE_NOT_FOUND:
		_error_label.text = "未能恢复角色位置，已使用默认构图。"
	resized.connect(_layout_avatar)
	_layout_avatar()
	gui_input.connect(_handle_pointer)
	mouse_exited.connect(func(): avatar.set_gaze(Vector2.ZERO))
	_reset_button.visible = true
	_reset_button.pressed.connect(func():
		framing.reset()
		_layout_avatar()
		_save())


func _layout_avatar() -> void:
	get_node("Stage/Background").material.set_shader_parameter("panel_size", %Stage.size)
	if avatar.get_status().loaded:
		avatar.transform = framing.get_transform(%Stage.size, avatar.get_status().canvas_size)
	_error_label.size.x = maxf(0, size.x - 40)


func _handle_pointer(event: InputEvent) -> void:
	if event is InputEventMouseButton:
		_handle_button(event)
	elif event is InputEventMouseMotion:
		_handle_motion(event)
func _save() -> void:
	if framing.save_settings() != OK:
		_error_label.text = "当前角色位置无法保存，重启后将恢复上次设置。"


func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_WINDOW_FOCUS_OUT and is_instance_valid(avatar):
		avatar.set_gaze(Vector2.ZERO)
	if what == NOTIFICATION_WM_WINDOW_FOCUS_OUT and _dragging:
		_dragging = false
		_save()


func _process(_delta: float) -> void:
	var minimized: bool = window_system.minimized(get_window())
	avatar.visible = not minimized
	avatar.process_mode = Node.PROCESS_MODE_DISABLED if minimized else Node.PROCESS_MODE_INHERIT

func _handle_button(event: InputEventMouseButton) -> void:
	if event.button_index == MOUSE_BUTTON_LEFT and event.pressed:
		_handle_touch(event)
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

func _handle_touch(event: InputEventMouseButton) -> void:
	var local := avatar.to_local(get_global_transform() * event.position)
	var areas: Array[String] = avatar.hit_test(local)
	if not areas.is_empty():
		var ripple := Ripple.instantiate() as Control
		ripple.position = event.position - Vector2(60, 60)
		add_child(ripple)
		touched.emit(areas)
	accept_event()

func _handle_motion(event: InputEventMouseMotion) -> void:
	if %Stage.size.x > 0 and %Stage.size.y > 0:
		avatar.set_gaze(Vector2(event.position.x / %Stage.size.x * 2 - 1, 1 - event.position.y / %Stage.size.y * 2))
	if _dragging:
		if not Input.is_mouse_button_pressed(MOUSE_BUTTON_RIGHT):
			_dragging = false
			_save()
			return
		framing.pan_by(event.relative, %Stage.size)
		_layout_avatar()
		accept_event()
