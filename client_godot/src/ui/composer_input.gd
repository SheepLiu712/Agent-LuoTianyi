extends TextEdit
@export var input_service: Resource = preload("res://src/platform/input_service.gd").new()
signal send_requested
signal image_pasted(image: Image)

func _gui_input(event: InputEvent) -> void:
	if not event is InputEventKey or not event.pressed or event.echo:
		return
	if event.keycode == KEY_ENTER or event.keycode == KEY_KP_ENTER:
		var composing := has_ime_text()
		composing = composing or input_service.is_composing()
		if not event.shift_pressed and not composing:
			accept_event()
			send_requested.emit()
	elif event.keycode == KEY_V and event.ctrl_pressed and input_service.has_clipboard_image():
		accept_event()
		image_pasted.emit(input_service.get_clipboard_image())
