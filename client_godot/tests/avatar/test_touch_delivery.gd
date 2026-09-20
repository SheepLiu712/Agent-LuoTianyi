extends SceneTree
var failures: Array[String] = []
var received: Array = []
func _initialize() -> void: run.call_deferred()
func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)
func until(predicate: Callable) -> void:
	var deadline := Time.get_ticks_msec() + 2500
	while not predicate.call() and Time.get_ticks_msec() < deadline: await process_frame
func run() -> void:
	var transport = load("res://src/network/websocket_transport.gd").new()
	var audio = load("res://src/media/reply_audio.gd").new()
	var session = load("res://src/session/chat_session.gd").new(transport, null, audio)
	root.add_child(session)
	check(session.has_method("record_touch"), "session accepts avatar touches")
	if failures.is_empty():
		transport.event_received.connect(func(event):
			if event.type == "touch_seen": received.append(event.payload))
		var account := {"server":OS.get_environment("GODOT_TEST_SERVER") + "/prefix", "username":"touch", "message_token":"message-test"}
		session.start(account)
		await until(func(): return session.get_state().phase == "ready")
		session.record_touch(["头"])
		await until(func(): return received.size() == 1)
		check(received.size() == 1 and received[0].touchArea == ["头"] and received[0].touchCount == 1, "first touch uses existing wire fields")
		session.record_touch(["手"])
		session.record_touch(["身体"])
		await create_timer(1.05).timeout
		check(received.size() == 1, "cooldown avoids extra sends")
		session.record_touch(["手"])
		await until(func(): return received.size() == 2)
		check(received.size() == 2 and received[1].touchCount == 3 and received[1].touchArea.size() == 2, "cooldown merges regions and click count")
		var bytes: PackedByteArray = load("res://tests/support/audio_samples.gd").tone(0.5)
		audio.append_reply_audio("touch-speaking", Marshalls.raw_to_base64(bytes), true)
		audio.play_reply("touch-speaking")
		await until(func(): return audio.get_state().playing)
		session.record_touch(["头"])
		await create_timer(0.7).timeout
		check(received.size() == 2, "online voice suppresses touch reporting")
		session.stop()
		session.start(account)
		await until(func(): return session.get_state().phase == "ready")
		session.record_touch(["手"])
		await until(func(): return received.size() == 3)
		check(received.size() == 3 and received[2].touchCount == 1, "relogin does not restore old touch counts")
	session.queue_free()
	await process_frame
	print("Touch delivery: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
