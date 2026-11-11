extends Window
## 统一错误弹窗：按当前窗口懒加载，队列串行展示，重复文本短时间去重。
const SCENE_PATH := "res://scenes/ui/error_dialog.tscn"
const ModalStack = preload("res://src/ui/modal_stack.gd")
const MAX_QUEUE := 8
const DEDUPE_MS := 3000

var _queue: Array[Dictionary] = []
var _current_text := ""
var _last_text := ""
var _last_at := 0
var _return_focus: WeakRef
static var _logger_ref


static func present(source: Node, text: String, title: String = "提示") -> void:
	var clean := text.strip_edges()
	if source == null or clean.is_empty() or not source.is_inside_tree():
		return
	var window: Window = source if source is Window else source.get_window()
	if window == null:
		return
	var dialog := _find(window)
	if dialog == null:
		dialog = load(SCENE_PATH).instantiate()
		window.add_child(dialog)
	dialog.show_error(clean, title)


static func set_logger(logger: RefCounted) -> void:
	_logger_ref = weakref(logger)


static func _find(window: Window) -> Node:
	for child in window.find_children("*", "", true, false):
		if child.is_in_group("error_dialog") and child.has_method("show_error"):
			return child
	return null


func _ready() -> void:
	add_to_group("error_dialog")
	%ErrorConfirm.pressed.connect(_dismiss)
	%ErrorClose.pressed.connect(_dismiss)
	close_requested.connect(_dismiss)


func show_error(text: String, title: String = "提示") -> void:
	var clean := text.strip_edges()
	if clean.is_empty():
		return
	if _is_duplicate(clean):
		return
	var logger = _logger_ref.get_ref() if _logger_ref != null else null
	if logger != null:
		logger.log_warning("warning_ui_error", {"code":"UI_ERROR", "detail":clean, "phase":"failed"})
	_queue.append({"text":clean, "title":title})
	if _queue.size() > MAX_QUEUE:
		_queue.pop_front()
	if not visible:
		_show_next()

func _is_duplicate(text: String) -> bool:
	if visible and text == _current_text:
		return true
	if text == _last_text and Time.get_ticks_msec() - _last_at < DEDUPE_MS:
		return true
	return not _queue.is_empty() and str(_queue.back().text) == text


func get_current_text() -> String:
	return _current_text


func _show_next() -> void:
	if _queue.is_empty():
		return
	var item: Dictionary = _queue.pop_front()
	_current_text = str(item.text)
	_last_text = _current_text
	_last_at = Time.get_ticks_msec()
	%ErrorTitle.text = str(item.title)
	%ErrorText.text = _current_text
	var owner := get_parent().get_viewport().gui_get_focus_owner() if get_parent() != null else null
	if owner != null and (_return_focus == null or _return_focus.get_ref() == null):
		_return_focus = weakref(owner)
	popup_centered()
	ModalStack.activate(self)
	%ErrorConfirm.grab_focus.call_deferred()


func _dismiss() -> void:
	var has_next := not _queue.is_empty()
	hide()
	_current_text = ""
	if has_next:
		_show_next.call_deferred()
	else:
		_restore_focus.call_deferred()


## Esc 与关闭按钮同义；弹窗是 exclusive 的，不能把键盘用户困在里面。
func _input(event: InputEvent) -> void:
	if visible and event.is_action_pressed("ui_cancel"):
		get_viewport().set_input_as_handled()
		_dismiss()


func _restore_focus() -> void:
	if _return_focus == null:
		return
	var target: Variant = _return_focus.get_ref()
	_return_focus = null
	if target is Control and is_instance_valid(target) and target.is_inside_tree() and target.is_visible_in_tree():
		target.grab_focus()
