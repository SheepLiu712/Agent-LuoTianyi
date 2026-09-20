extends Window
const Style = preload("res://src/preview/preview_style.gd")
var _discard := ConfirmationDialog.new()
func _init() -> void:
	visible = false
func _ready() -> void:
	theme = Style.make_theme()
	_discard.title = "放弃未保存的修改？"
	_discard.dialog_text = "关闭后，本窗口未保存的内容将被丢弃。"
	_discard.ok_button_text = "放弃修改"
	_discard.cancel_button_text = "取消"
	add_child(_discard)
	_discard.confirmed.connect(queue_free)
	close_requested.connect(func():
		if is_dirty():
			_discard.popup_centered()
			_discard.get_cancel_button().grab_focus()
		else:
			queue_free())
func open() -> void:
	show()
	grab_focus()
func is_dirty() -> bool:
	return false
