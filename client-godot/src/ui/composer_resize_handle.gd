extends Control
## 输入区上沿那条分隔线的拖动带：只认贴着线的那 6px，其余位置照旧交给输入框和按钮。
## 只报告位移，不持有高度，也不碰持久化；高度归 ChatView，写盘归应用层。
signal drag_delta(delta_y: float)
signal drag_committed

## 热区贴着这条线的深度：线的下方 6px 内按下才算抓到它。
const BAND := 6.0

var _dragging := false
var _moved := false

## 只有落在带内的按下才开拖，带外的点击必须原样往上冒泡，不能拦。
func _gui_input(event: InputEvent) -> void:
	if _dragging or not _is_left_press(event):
		return
	if event.position.y > BAND:
		return
	_begin_drag()
	accept_event()

## 指针一旦移出这条带，motion 就不再进 _gui_input，所以拖动期间改由全局输入兜住。
## 只在 _dragging 时接管，平时不碰别人的输入事件。
func _input(event: InputEvent) -> void:
	if not _dragging:
		return
	if _is_left_release(event):
		_end_drag()
		get_viewport().set_input_as_handled()
	elif event is InputEventMouseMotion:
		_report_motion(event.relative.y)
		get_viewport().set_input_as_handled()

## 光标跟着带子走：贴着线显示上下箭头，其余位置保持普通箭头。
func _get_cursor_shape(position: Vector2) -> CursorShape:
	return CURSOR_VSIZE if position.y <= BAND else CURSOR_ARROW

## 拖动中切走窗口会收不到松开事件，这里收尾，避免下次点进来还在拖。
func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_WINDOW_FOCUS_OUT and _dragging:
		_end_drag()

func is_dragging() -> bool:
	return _dragging

func _is_left_press(event: InputEvent) -> bool:
	return event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT and event.pressed

func _is_left_release(event: InputEvent) -> bool:
	return event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT and not event.pressed

func _begin_drag() -> void:
	_dragging = true
	_moved = false

func _end_drag() -> void:
	_dragging = false
	if _moved:
		drag_committed.emit()

func _report_motion(delta_y: float) -> void:
	if is_zero_approx(delta_y):
		return
	_moved = true
	drag_delta.emit(delta_y)
