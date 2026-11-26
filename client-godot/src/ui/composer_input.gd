extends TextEdit
@export var input_service: Resource = preload("res://src/platform/input_service.gd").new()
signal send_requested
signal image_pasted(image: Image)

func _gui_input(event: InputEvent) -> void:
	var key := event as InputEventKey
	if key == null or not key.pressed or key.echo:
		return
	if _is_submit_key(key.keycode):
		_submit_key(key)
	elif key.keycode == KEY_TAB:
		_move_focus(key)
	elif _is_paste_image(key):
		accept_event()
		image_pasted.emit(input_service.get_clipboard_image())


func _is_submit_key(code: int) -> bool:
	return code == KEY_ENTER or code == KEY_KP_ENTER


## TextEdit 默认把 Tab 插入正文，会让键盘用户困在输入框里。
func _move_focus(key: InputEventKey) -> void:
	accept_event()
	var next := find_prev_valid_focus() if key.shift_pressed else find_next_valid_focus()
	if next != null:
		next.grab_focus()


func _is_paste_image(key: InputEventKey) -> bool:
	return key.keycode == KEY_V and key.ctrl_pressed and input_service.has_clipboard_image()

func _submit_key(event: InputEventKey) -> void:
	var composing := has_ime_text()
	composing = composing or input_service.is_composing()
	if not event.shift_pressed and not composing:
		accept_event()
		send_requested.emit()
