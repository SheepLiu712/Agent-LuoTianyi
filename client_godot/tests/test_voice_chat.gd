extends SceneTree
const Transport = preload("res://src/network/websocket_transport.gd")
const Session = preload("res://src/session/chat_session.gd")
const VIEW_SCENE := "res://scenes/ui/chat_view.tscn"
const Audio = preload("res://src/media/reply_audio.gd")
const Cache = preload("res://src/storage/audio_cache.gd")
const Log = preload("res://src/storage/client_log.gd")
var failures: Array[String] = []
var capture := AudioEffectCapture.new()
var peak := 0.0
var expressions: Array[String] = []
var mouth := -1.0
var mouth_max := 0.0

func check(value: bool, description: String) -> void:
	if not value:
		failures.append(description)
		print("FAIL: ", description)

func until(predicate: Callable, timeout: int = 2500) -> bool:
	var deadline := Time.get_ticks_msec() + timeout
	while not predicate.call() and Time.get_ticks_msec() < deadline:
		await process_frame
		for sample in capture.get_buffer(capture.get_frames_available()):
			peak = maxf(peak, absf(sample.x))
	return predicate.call()

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	AudioServer.add_bus_effect(0,capture)
	var directory := "user://voice-chat-test-%s" % Time.get_ticks_usec()
	var logger = Log.new(directory)
	var cache = Cache.new(directory + "/audio")
	var session = Session.new(Transport.new(),logger,Audio.new(logger,Callable(),cache))
	root.add_child(session)
	session.expression_requested.connect(func(value): expressions.append(value))
	session.mouth_changed.connect(func(value): mouth = value; mouth_max = maxf(mouth_max,value))
	session.start({"server":OS.get_environment("GODOT_TEST_SERVER") + "/prefix", "username":"audio", "message_token":"message-test"})
	check(await until(func(): return session.get_state().phase == "ready"), "loopback voice connection authenticates")
	session.send_text("stream")
	check(await until(func(): return session.get_state().get("speaking",false)), "received WAV reaches actual playing state")
	check(session.get_messages().size() == 2 and expressions == ["微笑脸"], "later text and expression wait for preceding sound")
	check(await until(func(): return session.get_messages().size() == 3 and session.get_audio_state().queued == 0), "both replies finish in order")
	check(peak > .05 and expressions == ["微笑脸","normal"], "real network audio reaches mixer")
	check(mouth_max > .05 and mouth == -1.0, "chat forwards actual mouth progress and restoration")
	peak = 0
	capture.clear_buffer()
	session.send_text("hidden")
	check(await until(func(): return session.get_state().get("speaking",false)), "hidden ephemeral voice still plays")
	check(await until(func(): return session.get_audio_state().queued == 0), "hidden reply finishes")
	check(peak > .05 and session.get_messages().size() == 4, "hidden audio has output without bubble")
	session.send_text("bad")
	check(await until(func(): return session.get_state().code == "AUDIO_ERROR"), "decode failure reported to UI")
	check(session.get_messages().any(func(message): return message.text == "voice-bad"), "malformed audio preserves text")
	root.size = Vector2i(1200,800)
	check(ResourceLoader.exists(VIEW_SCENE),"chat view scene exists")
	if not ResourceLoader.exists(VIEW_SCENE):
		quit(1)
		return
	var view = load(VIEW_SCENE).instantiate()
	view.setup(session)
	root.add_child(view)
	view.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	await process_frame
	var list: ScrollContainer = view.find_children("*","ScrollContainer",true,false).filter(func(n): return n.has_method("scroll_to_message"))[0]
	list.scroll_to_message("voice-first")
	for _frame in 4:
		await process_frame
	check(button(view,"重放") != null,"completed voice exposes visible replay control")
	if button(view,"重放") != null:
		var label: RichTextLabel
		for item in view.find_children("*","RichTextLabel",true,false):
			if item.text == "voice-first":
				label = item
		label.select_all()
		var original := label.get_instance_id()
		var snapshot: Array = session.get_messages()
		var expression_count := expressions.size()
		button(view,"重放").pressed.emit()
		check(await until(func(): return button(view,"暂停") != null),"replay button begins playback")
		if button(view,"暂停") != null:
			button(view,"暂停").pressed.emit()
			check(button(view,"继续") != null,"pause exposes resume")
			button(view,"继续").pressed.emit()
		await until(func(): return button(view,"暂停") == null)
		check(label.get_instance_id() == original and label.get_selected_text() == "voice-first","progress preserves bubble and selected text")
		check(session.get_messages() == snapshot and expressions.size() == expression_count,"local replay creates no messages or expression events")
		check(session.replay("missing") != OK,"session rejects undisplayed voice")
	var sliders = view.find_children("*", "HSlider",true,false)
	check(sliders.size() == 1, "chat exposes volume control")
	if sliders.size() == 1:
		sliders[0].value = .35
		check(is_equal_approx(session.get_audio_state().volume,.35), "volume UI calls public controller")
	session.send_text("stop")
	check(await until(func(): return session.get_state().speaking), "stop test begins real voice")
	for button in view.find_children("*", "Button",true,false):
		if button.text == "停止语音":
			button.pressed.emit()
	await process_frame
	check(not session.get_state().speaking and mouth == -1.0, "stop button silences and restores mouth")
	check(not session.get_messages().any(func(message): return message.text == "stop-next"), "stop before terminal does not advance next reply")
	session.send_text("continue")
	check(await until(func(): return session.get_messages().any(func(message): return message.text == "stop-final")), "stop still accepts final text update")
	check(await until(func(): return session.get_messages().any(func(message): return message.text == "stop-next") and session.get_audio_state().queued == 0), "next reply resumes after stopped reply terminal")
	session.send_text("disconnect")
	check(await until(func(): return session.get_state().get("speaking",false)), "unfinished stream begins")
	session.send_text("close")
	check(await until(func(): return session.get_state().phase != "ready"), "fixture disconnect observed")
	check(not session.get_state().get("speaking",false), "disconnect releases active voice")
	check(mouth == -1.0 and session.get_audio_state().queued == 0, "disconnect releases streams and mouth")
	check(session.get_messages().any(func(message): return message.text == "voice-disconnect"), "disconnect preserves displayed voice text")
	var logs := JSON.stringify(logger.read_entries())
	check(logs.contains("audio_playback_started") and logs.contains("audio_playback_finished") and logs.contains("audio_error"), "network to playback has diagnostic trail")
	var menu = view.find_child("ChatMore",true,false)
	menu.activated.emit("cache")
	var dialogs = view.find_children("*Dialog","Window",true,false)
	check(dialogs.size() == 1 and dialogs[0].visible,"clear cache requires confirmation")
	if not dialogs.is_empty():
		check(cache.lookup("voice-first").has("path"),"opening clear dialog does not delete cache")
		dialogs[0].get_cancel_button().pressed.emit()
		check(cache.lookup("voice-first").has("path"),"cancel keeps cache")
		menu.activated.emit("cache")
		dialogs[0].confirmed.emit()
		await process_frame
		check(button(view,"重放") == null and cache.lookup("voice-first").is_empty(),"confirmed clear removes replay buttons but keeps text")
	check(session.get_messages().any(func(message): return message.text == "voice-first"),"clearing cache preserves chat text")
	session.stop()
	check(cache.lookup("voice-first").is_empty(),"logout closes cache scope")
	view.queue_free()
	session.queue_free()
	await process_frame
	AudioServer.remove_bus_effect(0,AudioServer.get_bus_effect_count(0)-1)
	logger.finish()
	for file in DirAccess.get_files_at(directory):
		DirAccess.remove_absolute(directory.path_join(file))
	if DirAccess.dir_exists_absolute(directory + "/audio"):
		for scope in DirAccess.get_directories_at(directory + "/audio"):
			DirAccess.remove_absolute(directory + "/audio/" + scope)
		DirAccess.remove_absolute(directory + "/audio")
	DirAccess.remove_absolute(directory)
	print("Voice chat: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func button(view: Node, text: String) -> Button:
	for item in view.find_children("*","Button",true,false):
		if item.text == text and item.is_visible_in_tree():
			return item
	return null
