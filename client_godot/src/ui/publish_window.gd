extends "res://src/ui/draft_window.gd"
signal published(id: String)
var _controller: Node
@onready var _draft: TextEdit = %PublishDraft
@onready var _send: Button = %PublishButton
@onready var _status: Label = %PublishStatus
var _writing := false
func setup(controller: Node) -> void:
	_controller = controller
func _ready() -> void:
	super._ready()
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
