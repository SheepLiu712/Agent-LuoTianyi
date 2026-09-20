extends SceneTree
var failures: Array[String] = []
func _initialize() -> void: run.call_deferred()
func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)
func until(predicate: Callable) -> bool:
	var end := Time.get_ticks_msec() + 4000
	while not predicate.call() and Time.get_ticks_msec() < end: await process_frame
	return predicate.call()
func run() -> void:
	var history = load("res://src/session/history_sync.gd").new(load("res://src/network/history_api.gd").new())
	var images = load("res://src/storage/history_images.gd").new("user://image-send-%s" % Time.get_ticks_usec())
	var chat = load("res://src/session/chat_session.gd").new(load("res://src/network/websocket_transport.gd").new(),null,null,history,null,images)
	root.add_child(chat)
	var view = load("res://scenes/ui/chat_view.tscn").instantiate()
	view.setup(chat)
	root.add_child(view)
	check(chat.has_method("send_image") and view.get_node_or_null("%ImageButton") != null, "live chat offers image sending")
	if failures.is_empty():
		var image := Image.create(24,16,false,Image.FORMAT_RGB8)
		image.fill(Color("66ccff"))
		var png := image.save_png_to_buffer()
		var account := {"server":OS.get_environment("GODOT_TEST_SERVER"),"username":"send-image","message_token":"message-test"}
		chat.start(account)
		var id: String = chat.send_image(png,"image/png")
		check(not id.is_empty() and chat.get_messages()[0].status == "waiting_history", "image waits for first history boundary")
		check(chat.preview_message_image(id).get_size() == Vector2(24,16), "queued image has original preview")
		check(await until(func(): return chat.get_messages().any(func(m): return m.id == id and m.status == "sent")), "real image protocol is acknowledged after history")
		check(chat.send_image("not a png".to_utf8_buffer(),"image/png").is_empty(), "invalid image cannot enter reliable queue")
		var preview: Array[Callable] = []
		view.attachment_requested.connect(func(_provider,confirm): preview.append(confirm))
		view.get_node("%Input").image_pasted.emit(image)
		check(view.is_dirty() and view.get_node("%AttachmentBar").visible and preview.size() == 1, "clipboard image becomes a retained pending attachment")
		var before: int = chat.get_messages().size()
		view.get_node("%RemoveImage").pressed.emit()
		check(not view.is_dirty() and chat.get_messages().size() == before, "removing attachment never sends")
		view.get_node("%Input").image_pasted.emit(image)
		check(preview[-1].call(null), "preview confirmation accepts image")
		check(not view.is_dirty(), "accepted image clears attachment")
		chat.stop()
		view.get_node("%Input").image_pasted.emit(image)
		check(not preview[-1].call(null) and view.is_dirty(), "send failure retains pending image")
		check(chat.get_messages().is_empty() and chat.get_message_image(id).status == "idle", "logout clears previous account image state")
	view.queue_free()
	chat.queue_free()
	await process_frame
	print("Live image sending: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
