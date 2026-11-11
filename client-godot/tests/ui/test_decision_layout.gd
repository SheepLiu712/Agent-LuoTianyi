extends SceneTree
func _initialize() -> void: run.call_deferred()
func run() -> void:
	if DisplayServer.get_name() == "headless":
		quit(2)
		return
	root.size = Vector2i(800, 640)
	root.gui_embed_subwindows = true
	var dialog = load("res://scenes/ui/decision_dialog.tscn").instantiate()
	dialog.title = "清理语音缓存"
	dialog.dialog_text = "清理当前服务器、本账号保存的全部语音？\n聊天文字保留；已清理的语音将无法重放。"
	root.add_child(dialog)
	dialog.popup_centered()
	await create_timer(0.5).timeout
	var ok: bool = Rect2i(Vector2i.ZERO, root.size).encloses(Rect2i(dialog.position, dialog.size))
	ok = ok and Rect2(Vector2.ZERO, Vector2(dialog.size)).encloses(dialog.get_cancel_button().get_global_rect())
	var cancel := InputEventKey.new()
	cancel.keycode = KEY_ESCAPE
	cancel.pressed = true
	dialog.push_input(cancel)
	await process_frame
	ok = ok and not dialog.visible
	dialog.queue_free()
	await process_frame
	print("Decision visible layout and Esc: ", "PASS" if ok else "FAIL")
	quit(0 if ok else 1)
