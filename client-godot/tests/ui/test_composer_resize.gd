extends SceneTree
## 输入区上沿那条分隔线的拖动契约：只有贴着线的 6px 带能抓，带外的点击必须照旧落到输入框和按钮上。
## 移动/松开走 `_input`：真实拖动会跑出这条带，只测 `_gui_input` 掩盖不了这个问题。
## 另外用真实指针事件走一遍 viewport 命中，确认抓的确实是「那条线」而不是别的控件。
const SCENE := "res://scenes/ui/chat_view.tscn"
var failures: Array[String] = []
var _changes: Array[float] = []

func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)

func _initialize() -> void:
	run.call_deferred()

func run() -> void:
	var chat: Control = load(SCENE).instantiate()
	root.add_child(chat)
	await process_frame
	await process_frame
	chat.composer_height_changed.connect(func(height): _changes.append(height))
	var line: Control = chat.get_node("%ComposerSurface")
	var input: TextEdit = chat.get_node("%Input")
	_check_binding(chat, line)
	_check_band(chat, line)
	_check_pointer(chat, line)
	_check_drag(chat, line)
	_check_focus_out(chat, line)
	_check_auto(chat, input)
	await _check_tab_focus(chat, input)
	chat.queue_free()
	await process_frame
	print("Composer resize: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

## 拖动由分隔线自己承担：旧的手柄节点必须消失，信号挂在线上。
func _check_binding(chat: Control, line: Control) -> void:
	check(chat.get_node_or_null("%ComposerResizeHandle") == null, "the old input-band handle is gone")
	check(line.name == "ComposerSurface", "the separator line owns the drag")
	check(line.has_signal("drag_delta") and line.has_signal("drag_committed"), "the line exposes drag signals")
	check(line.get_node_or_null("ComposerMargin") != null, "the line keeps its layout child")
	check(line.mouse_filter != Control.MOUSE_FILTER_IGNORE, "the line stays reachable for the pointer")
	check(is_equal_approx(chat.get_composer_height(), 48.0), "composer starts at 48px")

## 带内才开拖，带外一律不拦；光标也只贴着线时才变上下箭头。
func _check_band(chat: Control, line: Control) -> void:
	_press(line, 40.0)
	_move(line, -50.0)
	check(is_equal_approx(chat.get_composer_height(), 48.0), "a press outside the band never starts a drag")
	_release(line)
	check(_changes.is_empty(), "an outside press persists nothing")
	_press(line, 3.0)
	_move(line, -40.0)
	check(is_equal_approx(chat.get_composer_height(), 88.0), "dragging inside the band grows the composer")
	check(_changes.is_empty(), "dragging does not persist before release")
	_release(line)
	check(_changes.size() == 1 and is_equal_approx(_changes[0], 88.0), "release persists exactly one height")
	check(line._get_cursor_shape(Vector2(10.0, 2.0)) == Control.CURSOR_VSIZE, "the cursor follows the band")
	check(line._get_cursor_shape(Vector2(10.0, 40.0)) == Control.CURSOR_ARROW, "the cursor stays normal elsewhere")

## 真实指针：命中测试必须把紧贴分隔线的按下交给这条线。
func _check_pointer(chat: Control, line: Control) -> void:
	chat.set_composer_height(48.0)
	_changes.clear()
	var rect := line.get_global_rect()
	_push_button(rect.position + Vector2(rect.size.x * 0.5, 3.0), true)
	check(line.is_dragging(), "a real press on the line starts the drag")
	_push_motion(Vector2(0.0, -30.0))
	check(is_equal_approx(chat.get_composer_height(), 78.0), "a real pointer drag resizes through the line")
	_push_button(rect.position + Vector2(rect.size.x * 0.5, 30.0), false)
	check(not line.is_dragging(), "a real release ends the drag")
	check(_changes.size() == 1 and is_equal_approx(_changes[0], 78.0), "the real drag commits once")
	_push_button(rect.position + Vector2(rect.size.x * 0.5, 80.0), true)
	check(not line.is_dragging(), "a press inside the input field is not a drag")
	_push_button(rect.position + Vector2(rect.size.x * 0.5, 80.0), false)
	check(_changes.size() == 1, "clicking the input never resizes the composer")

func _check_drag(chat: Control, line: Control) -> void:
	_press(line)
	_release(line)
	check(_changes.size() == 1, "a click without dragging does not persist")
	_press(line)
	_move(line, 20.0)
	check(is_equal_approx(chat.get_composer_height(), 58.0), "dragging down shrinks the composer")
	_move(line, 1000.0)
	check(is_equal_approx(chat.get_composer_height(), 48.0), "height stops at the 48px floor")
	_move(line, -1000.0)
	check(is_equal_approx(chat.get_composer_height(), 320.0), "height stops at the 320px ceiling")
	_release(line)
	check(_changes.size() == 2 and is_equal_approx(_changes[1], 320.0), "release persists the clamped height")

## 拖动中切换窗口收不到松开事件，必须收尾，否则下次进窗口还在拖。
func _check_focus_out(chat: Control, line: Control) -> void:
	chat.set_composer_height(120.0)
	_press(line)
	_move(line, -24.0)
	check(is_equal_approx(chat.get_composer_height(), 144.0), "drag from a restored height keeps working")
	line._notification(Node.NOTIFICATION_WM_WINDOW_FOCUS_OUT)
	_move(line, -24.0)
	check(is_equal_approx(chat.get_composer_height(), 144.0), "focus loss ends the drag")
	check(_changes.size() == 3 and is_equal_approx(_changes[2], 144.0), "focus loss commits the height it reached")

func _check_auto(chat: Control, input: TextEdit) -> void:
	chat.set_composer_height(0.0)
	input.text = "一\n二\n三\n四\n五\n六"
	chat._update_auto_height()
	check(is_equal_approx(chat.get_composer_height(), 128.0), "six lines auto-grow to the auto maximum")
	chat.set_composer_height(200.0)
	check(is_equal_approx(chat.get_composer_height(), 200.0), "manual height above auto is kept")
	input.text = "一"
	chat._update_auto_height()
	check(is_equal_approx(chat.get_composer_height(), 200.0), "auto shrink never undercuts manual")
	chat.set_composer_height(0.0)
	check(is_equal_approx(chat.get_composer_height(), 48.0), "zero restores pure auto height")


func _check_tab_focus(chat: Control, input: TextEdit) -> void:
	input.grab_focus()
	await process_frame
	var event := InputEventKey.new()
	event.keycode = KEY_TAB
	event.pressed = true
	input._gui_input(event)
	await process_frame
	var owner: Control = root.gui_get_focus_owner()
	check(owner != null and owner != input, "Tab leaves the composer instead of inserting a tab")

func _press(line: Control, y: float = 3.0) -> void:
	var event := InputEventMouseButton.new()
	event.button_index = MOUSE_BUTTON_LEFT
	event.pressed = true
	event.position = Vector2(20.0, y)
	line._gui_input(event)

func _release(line: Control) -> void:
	var event := InputEventMouseButton.new()
	event.button_index = MOUSE_BUTTON_LEFT
	event.pressed = false
	line._input(event)

func _move(line: Control, delta_y: float) -> void:
	var event := InputEventMouseMotion.new()
	event.relative = Vector2(0.0, delta_y)
	line._input(event)

func _push_button(position: Vector2, pressed: bool) -> void:
	var event := InputEventMouseButton.new()
	event.button_index = MOUSE_BUTTON_LEFT
	event.pressed = pressed
	event.position = position
	event.global_position = position
	root.push_input(event, true)

func _push_motion(relative: Vector2) -> void:
	var event := InputEventMouseMotion.new()
	event.relative = relative
	event.position = root.get_visible_rect().size * 0.5
	event.global_position = event.position
	root.push_input(event, true)
