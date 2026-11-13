extends Window
## Centralized queued error modal with deterministic sizing, transparent gutter, and focus restoration.

const SCENE_PATH := "res://scenes/ui/components/error_dialog.tscn"
const ModalStack = preload("res://src/ui/modal_stack.gd")
const ModalWindowLayout = preload("res://src/ui/modal_window_layout.gd")
const MAX_QUEUE := 8
const DEDUPE_MS := 3000
const COMPACT_MIN_HEIGHT := 128

@onready var _panel: PanelContainer = %Panel
@onready var _title_label: Label = %ErrorTitle
@onready var _text_label: Label = %ErrorText
@onready var _confirm_button: Button = %ErrorConfirm

var _queue: Array[Dictionary] = []
var _current_text := ""
var _last_text := ""
var _last_at := 0
var _return_focus: WeakRef
var _refine_nonce := 0
static var _logger_ref


static func present(source: Node, text: String, dialog_title: String = "提示") -> void:
	var clean := text.strip_edges()
	if source == null or clean.is_empty() or not source.is_inside_tree():
		return
	var window: Window = source if source is Window else source.get_window()
	if window == null:
		return
	var dialog := _find(window)
	if dialog == null:
		dialog = (load(SCENE_PATH) as PackedScene).instantiate()
		window.add_child(dialog)
	dialog.show_error(clean, dialog_title)


static func set_logger(logger: RefCounted) -> void:
	_logger_ref = weakref(logger)


static func _find(window: Window) -> Node:
	for child in window.find_children("*", "", true, false):
		if child.is_in_group("error_dialog") and child.has_method("show_error"):
			return child
	return null


func _ready() -> void:
	add_to_group("error_dialog")
	_confirm_button.pressed.connect(_dismiss)
	close_requested.connect(_dismiss)


func show_error(text: String, dialog_title: String = "提示") -> void:
	var clean := text.strip_edges()
	if clean.is_empty() or _is_duplicate(clean):
		return
	var logger = _logger_ref.get_ref() if _logger_ref != null else null
	if logger != null:
		logger.log_warning("warning_ui_error", {"code": "UI_ERROR", "detail": clean, "phase": "failed"})
	_queue.append({"text": clean, "title": dialog_title})
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
	var blocker := _blocking_exclusive_window()
	if blocker != null:
		_defer_until_unblocked(blocker)
		return
	var item: Dictionary = _queue.pop_front()
	_current_text = str(item.text)
	_last_text = _current_text
	_last_at = Time.get_ticks_msec()
	_title_label.text = str(item.title)
	_text_label.text = _current_text
	var owner := get_parent().get_viewport().gui_get_focus_owner() if get_parent() != null else null
	if owner != null and (_return_focus == null or _return_focus.get_ref() == null):
		_return_focus = weakref(owner)
	_refine_nonce += 1
	ModalWindowLayout.present(self, _panel, _text_label, COMPACT_MIN_HEIGHT)
	ModalStack.activate(self)
	_confirm_button.grab_focus.call_deferred()


func _blocking_exclusive_window() -> Window:
	var tree := get_tree()
	if tree == null or tree.root == null:
		return null
	return _find_exclusive_window(tree.root)


func _find_exclusive_window(node: Node) -> Window:
	for child in node.get_children():
		if child is Window and child != self and child.visible and child.exclusive:
			return child
		var nested := _find_exclusive_window(child)
		if nested != null:
			return nested
	return null


func _defer_until_unblocked(blocker: Window) -> void:
	if not blocker.visibility_changed.is_connected(_retry_show_next):
		blocker.visibility_changed.connect(_retry_show_next, CONNECT_ONE_SHOT)
	if not blocker.tree_exited.is_connected(_retry_show_next):
		blocker.tree_exited.connect(_retry_show_next, CONNECT_ONE_SHOT)


func _retry_show_next() -> void:
	if is_inside_tree() and not visible:
		_show_next.call_deferred()


func _refine_modal_height() -> void:
	var token := _refine_nonce
	for _pass in 4:
		await get_tree().process_frame
		if not visible or token != _refine_nonce:
			return
		var expected_width := float(size.x - ModalWindowLayout.DIALOG_GUTTER * 2)
		if absf(_panel.size.x - expected_width) <= 2.0 and _text_label.size.x > 1.0:
			break
	if visible and token == _refine_nonce:
		ModalWindowLayout.refine_height(self, _panel, _text_label, COMPACT_MIN_HEIGHT)


func _dismiss() -> void:
	var has_next := not _queue.is_empty()
	hide()
	_current_text = ""
	if has_next:
		_show_next.call_deferred()
	else:
		_restore_focus.call_deferred()


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
