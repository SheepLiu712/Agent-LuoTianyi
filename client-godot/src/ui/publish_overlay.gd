extends Control
signal close_requested
signal published(id: String)
const ErrorDialog = preload("res://src/ui/error_dialog.gd")
const DraftAutosave = preload("res://src/ui/draft_autosave.gd")
const UiMotion = preload("res://src/ui/ui_motion.gd")

var _controller: Node
var _drafts: RefCounted
var _scope := ""
var _text_draft: RefCounted
var _ui_style: RefCounted
@onready var _panel: PanelContainer = %Panel
@onready var _draft: TextEdit = %PublishDraft
@onready var _cancel: Button = %CancelPublish
@onready var _send: Button = %PublishButton
@onready var _status: Label = %PublishStatus
@onready var _discard_dialog: Window = %DiscardDialog
var _writing := false
var _discarding := false
var _published := false


func set_ui_style(style: RefCounted) -> void:
	_ui_style = style


func setup(controller: Node, drafts: RefCounted = null, scope: String = "") -> void:
	_controller = controller
	_drafts = drafts
	_scope = scope
func _ready() -> void:
	close_requested.connect(_request_close)
	_cancel.pressed.connect(func(): close_requested.emit())
	_discard_dialog.confirmed.connect(_discard_now)
	_send.pressed.connect(_publish)
	if _drafts != null and not _scope.is_empty():
		_text_draft = DraftAutosave.new()
		_text_draft.bind(_draft, _drafts, _scope, "dynamics.publish")
	_cancel.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	_send.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	UiMotion.bind_tactile_press(_send, func(): return _ui_style)
	resized.connect(_layout_panel)
	_layout_panel()
func is_dirty() -> bool:
	return _writing or not _draft.text.is_empty()
func _publish() -> void:
	if _writing: return
	_writing = true
	_send.disabled = true
	_draft.editable = false
	var result: Dictionary = await _controller.publish(_draft.text)
	_writing = false
	_send.disabled = false
	_draft.editable = true
	if result.ok:
		_draft.clear()
		if _text_draft != null:
			_text_draft.clear()
		_published = true
		published.emit(result.item_id)
		queue_free()
	else:
		_set_status("")
		if result.code in ["TIMEOUT","NETWORK_ERROR"]:
			ErrorDialog.present(self, "发布结果不确定，请先刷新核实；草稿已保留。")
		elif result.code == "INVALID_INPUT":
			ErrorDialog.present(self, "发布内容不能为空。")
		else:
			ErrorDialog.present(self, "发布失败，草稿已保留。")

func open() -> void:
	show()
	_layout_panel()
	UiMotion.reveal_overlay(_panel, Vector2(0.5, 0.5), -6.0, 0.20, _ui_style)
	_draft.grab_focus()

func _layout_panel() -> void:
	if not is_node_ready() or size.x <= 0.0 or size.y <= 0.0:
		return
	_panel.custom_minimum_size = Vector2(
		minf(560.0, maxf(300.0, size.x - 48.0)),
		minf(400.0, maxf(240.0, size.y - 48.0))
	)

func _set_status(text: String) -> void:
	_status.text = text
	_status.visible = not text.is_empty()
func _request_close() -> void:
	flush_drafts()
	if is_dirty():
		_discard_dialog.popup_centered()
		_discard_dialog.get_cancel_button().grab_focus()
	else: queue_free()


func flush_drafts() -> bool:
	if _text_draft == null:
		return true
	return bool(_text_draft.flush())


func loss_warnings() -> Array[String]:
	var warnings: Array[String] = []
	if _drafts == null or _scope.is_empty():
		if is_dirty():
			warnings.append("动态发布草稿")
		return warnings
	if _writing:
		warnings.append("动态正在发布，退出后结果可能未确认")
	if not _draft.text.strip_edges().is_empty() and _text_draft != null and _text_draft.has_failure():
		warnings.append("动态发布草稿保存失败")
	return warnings


func clear_draft() -> void:
	_discarding = true
	_draft.clear()
	if _text_draft != null:
		_text_draft.clear()


func _discard_now() -> void:
	clear_draft()
	queue_free()


func _exit_tree() -> void:
	if not _discarding and not _published:
		flush_drafts()


func _input(event: InputEvent) -> void:
	if is_visible_in_tree() and event is InputEventKey and event.pressed and not event.echo and event.keycode == KEY_TAB:
		get_viewport().set_input_as_handled()
		_cycle_focus(event.shift_pressed)
		return
	if is_visible_in_tree() and not _discard_dialog.visible and event.is_action_pressed("ui_cancel"):
		get_viewport().set_input_as_handled()
		close_requested.emit()


## 浮层内循环焦点，避免 Tab 走到被遮罩的动态列表。
func _cycle_focus(reverse: bool) -> void:
	var controls: Array[Control] = [_draft, _cancel, _send]
	var current := get_viewport().gui_get_focus_owner()
	var index := controls.find(current)
	if reverse:
		index = controls.size() - 1 if index <= 0 else index - 1
	else:
		index = 0 if index < 0 or index >= controls.size() - 1 else index + 1
	controls[index].grab_focus()
