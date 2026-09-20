extends SceneTree
const Transport = preload("res://src/network/websocket_transport.gd")
const Session = preload("res://src/session/chat_session.gd")
const VIEW_SCENE := "res://scenes/ui/chat_view.tscn"
const Log = preload("res://src/storage/client_log.gd")
var failures: Array[String] = []
var expressions: Array[String] = []
var thinking_seen := false
var logout_seen := false

func check(value: bool, description: String) -> void:
	if not value:
		failures.append(description)
		print("FAIL: ", description)

func until(predicate: Callable) -> bool:
	var deadline := Time.get_ticks_msec() + 2000
	while not predicate.call() and Time.get_ticks_msec() < deadline:
		await process_frame
	return predicate.call()

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var directory := "user://chat-log-test-%s" % Time.get_ticks_usec()
	var logger = Log.new(directory)
	var session = Session.new(Transport.new(), logger)
	root.add_child(session)
	session.expression_requested.connect(func(command): expressions.append(command))
	session.state_changed.connect(func(state): thinking_seen = thinking_seen or state.thinking)
	check(session.start({"server":OS.get_environment("GODOT_TEST_SERVER") + "/prefix", "username":"conversation", "message_token":"message-test"}) == OK, "chat starts real transport")
	check(await until(func(): return session.get_state().phase == "ready"), "chat reports authenticated connection")
	check(session.send_text(" \n ").is_empty() and session.get_messages().is_empty(), "blank chat rejected")
	check(ResourceLoader.exists(VIEW_SCENE),"chat view scene exists")
	if not ResourceLoader.exists(VIEW_SCENE):
		quit(1)
		return
	var view = load(VIEW_SCENE).instantiate()
	view.setup(session)
	root.add_child(view)
	view.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	view.logout_requested.connect(func(): logout_seen = true)
	await process_frame
	var inputs = view.find_children("*", "TextEdit", true, false)
	check(inputs.size() == 1, "live chat exposes one composer")
	if inputs.size() == 1:
		var input: TextEdit = inputs[0]
		input.text = "你好"
		input.grab_focus()
		var key := InputEventKey.new()
		key.keycode = KEY_ENTER
		key.pressed = true
		Input.parse_input_event(key)
		await process_frame
		key.pressed = false
		Input.parse_input_event(key)
		check(input.text.is_empty(), "accepted text clears composer")
	check(await until(func(): return session.get_messages().size() == 4), "UUID aggregation hides reflection and retains ephemeral text")
	var messages: Array[Dictionary] = session.get_messages()
	if messages.size() == 4:
		check(messages[0].role == "user" and messages[0].status == "sent", "real ACK updates original bubble")
		check(messages[1].text == "第一句" and messages[2].text == "第二句", "audio error preserves text and reply ordering")
		check(messages[3].text == "临时可见消息", "ephemeral is independent of display flag")
		messages[0].text = "mutated"
		check(session.get_messages()[0].text == "你好", "message snapshots are independent")
	check(expressions == ["微笑脸", "温柔脸", "normal"], "expressions follow reply order and duplicate terminal is ignored")
	check(thinking_seen and not session.get_state().thinking, "thinking and waiting propagated")
	var log_text := JSON.stringify(logger.read_entries())
	check(log_text.contains("reply_received") and log_text.contains("audio_chars"), "actual reply arrival is diagnosable")
	check(not log_text.contains("message-test") and not log_text.contains("第一句"), "chat logs exclude tokens and text")
	await process_frame
	await process_frame
	var labels = view.find_children("*", "RichTextLabel", true, false)
	check(labels.any(func(label): return label.text == "第一句"), "actual response appears in visible bubble")
	var captions = view.find_children("*", "Label", true, false)
	check(not captions.any(func(label): return label.text.contains("演示")), "live delivery is not labelled simulated")
	var menus = view.find_children("ChatMore", "Button", true, false)
	check(menus.size() == 1, "chat exposes a compact more menu")
	if menus.size() == 1:
		var menu = menus[0]
		check(menu.get_items().any(func(item): return item.get("id") == "logs" and item.label == "打开日志"), "logs accessible through menu")
		check(menu.get_items().any(func(item): return item.get("id") == "logout" and item.label == "退出登录"), "logout accessible through menu")
		menu.activated.emit("logout")
	check(logout_seen, "logout request is exposed to application")
	session.stop()
	check(session.get_messages().is_empty() and session.get_state().phase == "idle", "stop clears old account messages")
	if inputs.size() == 1:
		inputs[0].text = "保留草稿"
		inputs[0].send_requested.emit()
		check(inputs[0].text == "保留草稿", "rejected send preserves draft")
	# Restart in the same frame: the view must reconcile the new snapshot even
	# when the empty state from stop() was coalesced by a deferred refresh.
	session.start({"server":OS.get_environment("GODOT_TEST_SERVER") + "/prefix", "username":"normal", "message_token":"message-test"})
	session.send_text("新的会话")
	await process_frame
	await process_frame
	labels = view.find_children("*", "RichTextLabel", true, false)
	check(not labels.any(func(label): return label.text == "第一句"), "same-frame restart removes previous account bubbles")
	session.stop()
	view.queue_free()
	session.queue_free()
	await process_frame
	logger.finish()
	for file in DirAccess.get_files_at(directory):
		DirAccess.remove_absolute(directory.path_join(file))
	DirAccess.remove_absolute(directory)
	print("Live text chat: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
