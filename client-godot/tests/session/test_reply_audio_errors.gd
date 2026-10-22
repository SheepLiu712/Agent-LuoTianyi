extends SceneTree

const Session = preload("res://src/session/chat_session.gd")
const Transport = preload("res://src/network/websocket_transport.gd")
const Audio = preload("res://tests/support/native_reply_audio.gd")
const Samples = preload("res://tests/support/audio_samples.gd")
const Cache = preload("res://src/storage/audio_cache.gd")
const Log = preload("res://src/storage/client_log.gd")
var failures: Array[String] = []
var mouth := -1.0

func _initialize() -> void:
	run.call_deferred()

func check(value: bool, description: String) -> void:
	if not value:
		failures.append(description)
		print("FAIL: ", description)

func until(predicate: Callable, timeout: int = 5000) -> bool:
	var deadline := Time.get_ticks_msec() + timeout
	while not predicate.call() and Time.get_ticks_msec() < deadline:
		await process_frame
	return predicate.call()

func event(id: String, text: String, audio: PackedByteArray, final: bool, failed: bool = false) -> Dictionary:
	return {"type":"agent_message", "payload":{"uuid":id, "text":text,
		"audio":Marshalls.raw_to_base64(audio) if not audio.is_empty() else "", "is_final_package":final, "audio_error":failed}}

func run() -> void:
	var directory := "user://reply-errors-%s" % Time.get_ticks_usec()
	var logger := Log.new(directory)
	var cache := Cache.new(directory.path_join("audio"))
	var audio := Audio.new(logger, Callable(), cache)
	var session := Session.new(Transport.new(), logger, audio)
	root.add_child(session)
	check(audio.set_scope("http://localhost:8000", "test") == OK, "isolated cache scope starts")
	session._connection_changed({"phase":"ready", "code":""})
	session.mouth_changed.connect(func(value): mouth = value)
	await test_queued_remote_error(session, audio, cache, logger)
	await test_local_decode_error(session, logger)
	await test_error_without_audio(session, logger)
	await test_active_remote_error(session, logger)
	await test_partial_local_error(session, cache, logger)
	await test_failed_audio_tail(session, cache, logger)
	session.queue_free()
	await process_frame
	logger.finish()
	remove_directory(directory)
	print("Reply audio error ownership and recovery: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func test_queued_remote_error(session: Node, audio: Node, cache: RefCounted, logger: RefCounted) -> void:
	session._receive(event("before", "前一条", Samples.tone(.12), true))
	check(await until(func(): return session.get_audio_state().playing), "previous reply is actually playing")
	var wave := Samples.tone(.9, 32000)
	session._receive(event("remote", "保留的文字", wave.slice(0, 49152), false))
	session._receive(event("remote", "", wave.slice(49152), false))
	var status: Dictionary = audio._streams.remote.decoder.get_status()
	check(status.sample_rate == 32000 and status.decoded_frames == 28800, "diagnostic-shaped WAV decodes before remote failure")
	var terminal := event("remote", "", PackedByteArray(), true, true)
	terminal.payload.error_code = "TTS_STREAM_ERROR"
	session._receive(terminal)
	session._receive(terminal)
	session._receive(event("after", "后一条", Samples.tone(.12), true))
	check(await until(func(): return session.get_audio_state().queued == 0), "failed reply releases ordered queue")
	check(session.get_messages().map(func(message): return message.text) == ["前一条", "保留的文字", "后一条"], "failure retains text and subsequent reply order")
	check(system_errors(logger).size() == 1, "one remote failure produces exactly one reminder")
	check(session.get_state().code == "REMOTE_AUDIO_ERROR", "remote failure is not mislabelled as local decoding")
	check(cache.lookup("remote").is_empty() and cache._pending.is_empty(), "incomplete remote audio cannot become replayable cache")
	check(not cache.lookup("after").is_empty(), "subsequent valid audio still commits")
	check(mouth == -1.0 and not session.get_state().speaking, "failure and following completion restore mouth")
	check_remote_diagnostics(logger)
	check_remote_status(session)
	session._receive(terminal)
	check(system_errors(logger).size() == 1 and session.get_audio_state().queued == 0, "late duplicate failure after completion cannot restart or notify")

func check_remote_diagnostics(logger: RefCounted) -> void:
	var errors := system_errors(logger)
	if errors.size() == 1:
		check(errors[0].code == "REMOTE_AUDIO_ERROR" and errors[0].get("reply_id") == "remote".sha256_text().substr(0, 12), "sanitized diagnostic links remote error to its reply")
	var media_errors: Array = logger.read_entries().filter(func(entry): return entry.event == "audio_error")
	check(media_errors.size() == 1 and media_errors[0].code == "REMOTE_AUDIO_ERROR", "media diagnostic preserves remote failure classification")
	var terminals: Array = logger.read_entries().filter(func(entry): return entry.event == "reply_received" and entry.get("audio_error", false))
	check(terminals.all(func(entry): return entry.get("code") == "TTS_STREAM_ERROR"), "known upstream failure code survives diagnostic sanitization")

func check_remote_status(session: Node) -> void:
	var view: Control = load("res://scenes/ui/chat_view.tscn").instantiate()
	root.add_child(view)
	view.setup(session)
	check(view._status.text.contains("服务端语音生成失败") and not view._status.text.contains("服务器暂时无法处理请求"), "chat explains the actual remote audio failure")
	view.queue_free()

func test_local_decode_error(session: Node, logger: RefCounted) -> void:
	var malformed := event("local", "解码失败也保留文字", PackedByteArray(), true)
	malformed.payload.audio = "%%%"
	session._receive(malformed)
	check(await until(func(): return session.get_audio_state().queued == 0), "local decode failure terminates")
	check(system_errors(logger).size() == 2 and session.get_state().code == "AUDIO_ERROR", "local failure also reports once using existing UI code")
	session._receive(malformed)
	session._present_replies()
	check(system_errors(logger).size() == 2, "duplicate failed terminal cannot repeat local reminder")

func test_error_without_audio(session: Node, logger: RefCounted) -> void:
	var terminal := event("no-audio", "没有语音的文字", PackedByteArray(), true, true)
	terminal.payload.error_code = "secret_private_untrusted_error"
	session._receive(terminal)
	check(await until(func(): return session.get_audio_state().queued == 0), "remote failure with zero audio never waits for playback")
	check(system_errors(logger).size() == 3, "zero-audio remote failure also reports once")
	session._receive(event("text-only", "普通文字", PackedByteArray(), true))
	check(await until(func(): return session.get_audio_state().queued == 0), "following text-only reply completes")
	check(system_errors(logger).size() == 3, "normal text-only terminal is not a voice error")
	check(not JSON.stringify(logger.read_entries()).contains("secret_private_untrusted_error"), "untrusted upstream details never enter diagnostics")

func test_active_remote_error(session: Node, logger: RefCounted) -> void:
	session._receive(event("active-error", "正在播放时失败", Samples.tone(.9, 32000), false))
	check(await until(func(): return session.get_audio_state().playing), "active failure scenario starts real playback")
	var terminal := event("active-error", "", PackedByteArray(), true, true)
	terminal.payload.error_code = "TTS_CANCELLED"
	session._receive(terminal)
	check(not session.get_audio_state().playing and mouth == -1.0, "upstream terminal immediately stops active player and mouth")
	check(await until(func(): return session.get_audio_state().queued == 0), "active failure releases queue")
	check(system_errors(logger).size() == 4, "active remote error also reports exactly once")
	session._receive(event("recovered", "仍可继续", Samples.tone(.12), true))
	check(await until(func(): return session.get_audio_state().queued == 0), "valid reply recovers after active upstream failure")
	check(system_errors(logger).size() == 4, "recovery never repeats past errors")

func system_errors(logger: RefCounted) -> Array:
	return logger.read_entries().filter(func(entry): return entry.event == "system_error")

func test_partial_local_error(session: Node, cache: RefCounted, logger: RefCounted) -> void:
	for pair in [["invalid-fragment", "INVALID_BASE64"], ["truncated-final", "TRUNCATED_AUDIO"]]:
		var previous_count := system_errors(logger).size()
		var wave := Samples.tone(.9, 32000)
		session._receive(event(pair[0], pair[0], wave.slice(0, 49152), false))
		var terminal := event(pair[0], "", PackedByteArray(), true)
		if pair[1] == "INVALID_BASE64": terminal.payload.audio = "%%%"
		session._receive(terminal)
		check(await until(func(): return session.get_audio_state().queued == 0), "partial local failure ends without blocking: " + pair[0])
		check(system_errors(logger).size() == previous_count + 1 and session.get_state().code == "AUDIO_ERROR", "partial decode failure reports exactly once as local")
		var media_errors: Array = logger.read_entries().filter(func(entry): return entry.event == "audio_error")
		check(media_errors[-1].code == pair[1], "specific local decoder error survives diagnostics")
		check(cache.lookup(pair[0]).is_empty() and cache._pending.is_empty(), "partial failed audio is never committed")
		check(session.get_messages().any(func(message): return message.text == pair[0]), "partial local failure preserves text")

func test_failed_audio_tail(session: Node, cache: RefCounted, logger: RefCounted) -> void:
	var previous_count := system_errors(logger).size()
	var terminal := event("failed-tail", "失败尾包也保留文字", Samples.tone(.12), true, true)
	terminal.payload.error_code = "TTS_EMPTY"
	session._receive(terminal)
	check(await until(func(): return session.get_audio_state().queued == 0), "failure flag takes precedence over nonempty terminal audio")
	check(system_errors(logger).size() == previous_count + 1, "failed nonempty terminal reports once")
	var received: Array = logger.read_entries().filter(func(entry): return entry.event == "audio_received" and entry.reply_id == "failed-tail".sha256_text().left(12))
	check(received.is_empty() and cache.lookup("failed-tail").is_empty() and cache._pending.is_empty(), "failed terminal bytes never enter decoder or cache")
	session._receive(terminal)
	check(system_errors(logger).size() == previous_count + 1, "completed nonempty failure terminal remains idempotent")

func remove_directory(directory: String) -> void:
	for child in DirAccess.get_directories_at(directory):
		remove_directory(directory.path_join(child))
	for file in DirAccess.get_files_at(directory):
		DirAccess.remove_absolute(directory.path_join(file))
	DirAccess.remove_absolute(directory)
