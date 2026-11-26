extends Control
@export var window_system: Resource = preload("res://src/platform/window_system.gd").new()
signal touched(areas: Array[String])
signal dynamic_requested(post: Dictionary)
## 指针手势归视图，持久化变换归 framing。
const Driver = preload("res://src/avatar/avatar_driver.gd")
const Framing = preload("res://src/avatar/avatar_framing.gd")
const ErrorDialog = preload("res://src/ui/error_dialog.gd")
const Tokens = preload("res://src/ui/design_tokens.gd")
const UiMotion = preload("res://src/ui/ui_motion.gd")
@export var settings: Resource = preload("res://src/storage/settings_store.gd").new()
const Ripple := preload("res://src/avatar/touch_ripple.gd")
@onready var avatar: Driver = %Driver
@onready var _error_label: Label = %Error
@onready var _reset_button: Button = %Reset
var framing: RefCounted
var _dragging := false
var _ui_style: RefCounted
var _heading_style: StyleBoxFlat
var _reset_styles: Array[StyleBoxFlat] = []
var _dynamic_post: Dictionary = {}
var _dynamic_opening := false
var _card_tween: Tween

func set_unread_dynamic(post: Dictionary) -> void:
	_cancel_card_tween()
	_dynamic_post = post.duplicate(true) if not post.is_empty() else {}
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
	var crystal: bool = _ui_style.is_crystal()
	var card_radius := 12 if crystal else 10
	if _heading_style == null:
		_heading_style = %Heading.get_theme_stylebox("panel").duplicate() as StyleBoxFlat
		%Heading.add_theme_stylebox_override("panel", _heading_style)
	_ui_style.apply_surface_style(_heading_style)
	_heading_style.bg_color = Tokens.AVATAR_HEADING_CRYSTAL if crystal else Tokens.AVATAR_HEADING_FLAT
	_apply_border_overlay_style(crystal, card_radius)
	_apply_stage_clip_style(card_radius)
	for reset_style in _reset_styles:
		_ui_style.apply_surface_style(reset_style)
		reset_style.set_corner_radius_all(8 if crystal else 6)
		reset_style.border_color = Tokens.BORDER_CRYSTAL if crystal else Tokens.BORDER_FLAT


func _apply_stage_clip_style(card_radius: int) -> void:
	var stage := get_node_or_null("%Stage") as Panel
	if stage == null:
		return
	var box := stage.get_theme_stylebox("panel").duplicate() as StyleBoxFlat
	if box == null:
		return
	box.set_corner_radius_all(card_radius)
	stage.add_theme_stylebox_override("panel", box)


func _apply_border_overlay_style(crystal: bool, card_radius: int) -> void:
	var border_overlay := get_node_or_null("%BorderOverlay") as Panel
	if border_overlay == null:
		return
	var box := border_overlay.get_theme_stylebox("panel").duplicate() as StyleBoxFlat
	box.set_corner_radius_all(card_radius)
	box.border_color = Tokens.BORDER_CRYSTAL if crystal else Tokens.BORDER_FLAT
	border_overlay.add_theme_stylebox_override("panel", box)


func _ready() -> void:
	for state in ["normal", "hover", "pressed"]:
		var reset_style := _reset_button.get_theme_stylebox(state).duplicate() as StyleBoxFlat
		reset_style.content_margin_left = 0.0
		reset_style.content_margin_right = 0.0
		reset_style.content_margin_top = 0.0
		reset_style.content_margin_bottom = 0.0
		reset_style.set_border_width_all(1)
		reset_style.border_color = Tokens.BORDER_FLAT
		reset_style.set_corner_radius_all(6)
		reset_style.bg_color = Tokens.AVATAR_RESET_STATES[state]
		_reset_button.add_theme_stylebox_override(state, reset_style)
		_reset_styles.append(reset_style)
	_apply_ui_style()
	framing = Framing.new(settings)
	if avatar.load_character("res://assets/live2d/character.json") != OK:
		_error_label.text = ""
		ErrorDialog.present(self, "角色资源缺失，请重新解压完整程序。")
		return
	var restored: Error = framing.load_settings()
	if restored != OK and restored != ERR_FILE_NOT_FOUND:
		push_warning("Avatar framing restore failed: %s" % restored)
	resized.connect(_layout_avatar)
	_layout_avatar()
	gui_input.connect(_handle_pointer)
	%Heading.gui_input.connect(_handle_heading_input)
	mouse_exited.connect(func(): avatar.set_gaze(Vector2.ZERO))
	_reset_button.visible = true
	_reset_button.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	UiMotion.bind_tactile_press(_reset_button, func(): return _ui_style)
	_reset_button.pressed.connect(func():
		framing.reset()
		_layout_avatar()
		_save())


func _layout_avatar() -> void:
	if avatar.get_status().loaded:
		avatar.transform = framing.get_transform(%Stage.size, avatar.get_status().canvas_size)
	_error_label.size.x = maxf(0, size.x - 40)


func _handle_pointer(event: InputEvent) -> void:
	if event is InputEventMouseButton:
		_handle_button(event)
	elif event is InputEventMouseMotion:
		_handle_motion(event)

func _handle_heading_input(event: InputEvent) -> void:
	if _dynamic_post.is_empty() or _dynamic_opening:
		return
	if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
		accept_event()
		_animate_dynamic_open()

func _animate_dynamic_open() -> void:
	var post := _dynamic_post.duplicate(true)
	if post.is_empty():
		return
	_cancel_card_tween()
	var heading := %Heading
	if UiMotion.should_reduce_motion(_ui_style):
		_emit_dynamic_post(post)
		return
	_dynamic_opening = true
	heading.pivot_offset = heading.size * 0.5
	_card_tween = create_tween()
	_card_tween.tween_property(heading, "scale", Vector2(0.97, 0.97), 0.07).set_trans(Tween.TRANS_QUAD).set_ease(Tween.EASE_OUT)
	_card_tween.parallel().tween_property(heading, "modulate", Color(0.92, 0.96, 0.99, 1), 0.07)
	_card_tween.tween_property(heading, "scale", Vector2.ONE, 0.12).set_trans(Tween.TRANS_QUART).set_ease(Tween.EASE_OUT)
	_card_tween.parallel().tween_property(heading, "modulate", Color.WHITE, 0.12)
	_card_tween.finished.connect(func(): _finish_dynamic_open(post))


func _finish_dynamic_open(post: Dictionary) -> void:
	_reset_heading_visuals()
	_emit_dynamic_post(post)


func _emit_dynamic_post(post: Dictionary) -> void:
	if _dynamic_post.is_empty() or str(_dynamic_post.get("id", "")) != str(post.get("id", "")):
		return
	dynamic_requested.emit(post)


func _cancel_card_tween() -> void:
	if _card_tween != null and _card_tween.is_valid():
		_card_tween.kill()
	_card_tween = null
	_reset_heading_visuals()


func _reset_heading_visuals() -> void:
	_dynamic_opening = false
	if is_instance_valid(%Heading):
		%Heading.scale = Vector2.ONE
		%Heading.modulate = Color.WHITE

func _save() -> void:
	if framing.save_settings() != OK:
		push_warning("Avatar framing save failed")


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
		mouse_default_cursor_shape = Control.CURSOR_MOVE if _dragging else Control.CURSOR_ARROW
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
		var ripple := Ripple.new() as Control
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
