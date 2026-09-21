extends TextEdit
signal send_requested
signal image_pasted(image: Image)

func _gui_input(event: InputEvent) -> void:
	if not event is InputEventKey or not event.pressed or event.echo:
		return
	if event.keycode == KEY_ENTER or event.keycode == KEY_KP_ENTER:
		var composing := has_ime_text()
		if DisplayServer.has_feature(DisplayServer.FEATURE_IME):
			composing = composing or not DisplayServer.ime_get_text().is_empty()
		if not event.shift_pressed and not composing:
			accept_event()
			send_requested.emit()
	elif event.keycode == KEY_V and event.ctrl_pressed and DisplayServer.clipboard_has_image():
		accept_event()
		image_pasted.emit(DisplayServer.clipboard_get_image())
