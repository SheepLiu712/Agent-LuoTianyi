extends Window
@onready var _discard: Window = %DiscardDialog


func _init() -> void:
	visible = false


func _ready() -> void:
	_discard.title = "放弃未保存的修改？"
	_discard.dialog_text = "关闭后，本窗口未保存的内容将被丢弃。"
	_discard.ok_button_text = "放弃修改"
	_discard.cancel_button_text = "取消"
	_discard.confirmed.connect(_discard_and_close)
	close_requested.connect(_request_close)


func open() -> void:
	%Chrome.open_window()


func is_dirty() -> bool:
	return false


func flush_drafts() -> bool:
	return true


func loss_warnings() -> Array[String]:
	return ["未保存的修改"] if is_dirty() else []


func clear_drafts() -> void:
	pass


func _request_close() -> void:
	flush_drafts()
	var warnings: Array[String] = []
	for item in loss_warnings():
		warnings.append(str(item))
	if warnings.is_empty():
		queue_free()
		return
	_discard.dialog_text = "以下内容尚未保存，关闭后将丢失：\n• " + "\n• ".join(warnings)
	_discard.popup_centered()
	_discard.get_cancel_button().grab_focus()


func _discard_and_close() -> void:
	clear_drafts()
	queue_free()
