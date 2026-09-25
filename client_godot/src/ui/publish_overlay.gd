extends Control
signal close_requested
signal published(id: String)
var _controller: Node
@onready var _draft: TextEdit = %PublishDraft
@onready var _send: Button = %PublishButton
@onready var _status: Label = %PublishStatus
var _writing := false
func setup(controller: Node) -> void:
	_controller = controller
func _ready() -> void:
	close_requested.connect(_request_close)
	%ClosePublish.pressed.connect(func(): close_requested.emit())
	%CancelPublish.pressed.connect(func(): close_requested.emit())
	%DiscardDialog.confirmed.connect(queue_free)
	_send.pressed.connect(_publish)
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
		published.emit(result.item_id)
		queue_free()
	else:
		_status.text = "发布结果不确定，请先刷新核实；草稿已保留。" if result.code in ["TIMEOUT","NETWORK_ERROR"] else "发布失败，草稿已保留（%s）。"%result.code

func open() -> void:
	show()
	_draft.grab_focus()
func _request_close() -> void:
	if is_dirty():
		%DiscardDialog.popup_centered()
		%DiscardDialog.get_cancel_button().grab_focus()
	else: queue_free()
func _input(event: InputEvent) -> void:
	if is_visible_in_tree() and not %DiscardDialog.visible and event.is_action_pressed("ui_cancel"):
		get_viewport().set_input_as_handled()
		close_requested.emit()
