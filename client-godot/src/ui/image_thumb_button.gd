extends TextureRect
## 图片入口：鼠标点击与键盘 Enter/Space 走同一条激活路径，焦点用共享主题的描边画出来，
## 这样图片不再只有鼠标可达。
signal activated

const FOCUS_TYPE := &"ImageEntry"

func _ready() -> void:
	focus_mode = Control.FOCUS_ALL
	mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND

func _gui_input(event: InputEvent) -> void:
	if event.is_action_pressed("ui_accept"):
		accept_event()
		activate()
	elif event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
		grab_focus()
		accept_event()
		activate()

## 只有真的能看到这张图时才允许激活，避免键盘在隐藏入口上误触发。
func activate() -> void:
	if is_visible_in_tree():
		activated.emit()

func _draw() -> void:
	if not has_focus():
		return
	draw_style_box(get_theme_stylebox("focus", FOCUS_TYPE), Rect2(Vector2.ZERO, size))

func _notification(what: int) -> void:
	if what == NOTIFICATION_FOCUS_ENTER or what == NOTIFICATION_FOCUS_EXIT:
		queue_redraw()
