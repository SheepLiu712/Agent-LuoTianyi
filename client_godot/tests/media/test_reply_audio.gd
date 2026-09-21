extends SceneTree
const Audio = preload("res://src/media/reply_audio.gd")
const Samples = preload("res://tests/support/audio_samples.gd")
const Log = preload("res://src/storage/client_log.gd")
var failures: Array[String] = []
var received: Array[String] = []
var played: Array[String] = []
var codes: Dictionary = {}
var mouth := -1.0
var mouth_max := 0.0
var peak := 0.0
var capture := AudioEffectCapture.new()

func check(value: bool, description: String) -> void:
	if not value:
		failures.append(description)
		print("FAIL: ", description)

func collect() -> void:
	var buffer := capture.get_buffer(capture.get_frames_available())
	for sample in buffer:
		peak = maxf(peak, absf(sample.x))

func until(predicate: Callable, timeout: int = 2200) -> bool:
	var deadline := Time.get_ticks_msec() + timeout
	while not predicate.call() and Time.get_ticks_msec() < deadline:
		await process_frame
		collect()
	return predicate.call()

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	await test_mixer()
	await test_lifecycle()
	print("Reply audio mixer and lifecycle: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func test_mixer() -> void:
	AudioServer.add_bus_effect(0, capture)
	var directory := "user://audio-test-%s" % Time.get_ticks_usec()
	var logger = Log.new(directory)
	var audio := Audio.new(logger)
	root.add_child(audio)
	audio.receive_finished.connect(func(id, _code): received.append(id))
	audio.playback_finished.connect(func(id, code): played.append(id); codes[id] = code)
	audio.mouth_changed.connect(func(value): mouth = value; mouth_max = maxf(mouth_max, value))
	var bytes := Samples.tone()
	audio.append_reply_audio("first", Marshalls.raw_to_base64(bytes.slice(0,17)), false)
	audio.play_reply("first")
	audio.append_reply_audio("first", Marshalls.raw_to_base64(bytes.slice(17,5001)), false)
	check(await until(func(): return audio.get_state().playing), "stream starts before final packet")
	audio.append_reply_audio("second", Marshalls.raw_to_base64(Samples.tone(.12,48000)), true)
	check(not played.has("second"), "later reply buffered without playback")
	audio.append_reply_audio("first", Marshalls.raw_to_base64(bytes.slice(5001)), true)
	check(received.has("first") and not played.has("first"), "reception completes before actual playback")
	check(await until(func(): return played.has("first")), "generator drains after final")
	check(peak > .05 and mouth_max > .05 and mouth == -1.0, "mixer has nonzero audio and mouth restores")
	check(codes.get("first") == "", "valid audio completes without failure")
	audio.play_reply("second")
	check(await until(func(): return played.has("second")), "different sample rate next reply plays")
	check(played == ["first", "second"], "reply order preserved")
	audio.set_volume(0)
	check(audio.get_state().volume == 0.0, "volume applied")
	peak = 0
	capture.clear_buffer()
	audio.append_reply_audio("muted", Marshalls.raw_to_base64(bytes), true)
	audio.play_reply("muted")
	check(await until(func(): return played.has("muted")), "muted playback still completes")
	check(peak < .0001, "volume zero mutes real mixer output")
	audio.set_volume(NAN)
	check(audio.get_state().volume == 0.0, "nonfinite volume ignored")
	audio.set_volume(1)
	audio.append_reply_audio("stop", Marshalls.raw_to_base64(bytes), false)
	audio.play_reply("stop")
	await until(func(): return audio.get_state().playing)
	audio.stop_current()
	audio.stop_current()
	check(not audio.get_state().playing and mouth == -1.0, "stop is immediate and restores mouth")
	audio.append_reply_audio("stop", "", true)
	check(await until(func(): return played.has("stop")) and codes.get("stop") == "STOPPED", "stopped UUID consumes terminal without restart")
	for id in ["empty", "bad", "error"]:
		audio.append_reply_audio(id, "" if id == "empty" else ("%%%" if id == "bad" else Marshalls.raw_to_base64(bytes)), true, id == "error")
		audio.play_reply(id)
		check(await until(func(): return played.has(id)), "empty or failed reply terminates")
	check(codes.get("empty") == "" and codes.get("bad") == "INVALID_BASE64" and codes.get("error") == "AUDIO_ERROR", "terminal error codes distinguish no audio")
	audio.append_reply_audio("reset", Marshalls.raw_to_base64(bytes), false)
	audio.play_reply("reset")
	audio.reset()
	audio.reset()
	check(audio.get_state().queued == 0 and not audio.get_state().playing, "reset releases unfinished streams")
	check(not played.has("reset"), "reset does not emit old account completion")
	var log_text := JSON.stringify(logger.read_entries())
	for event in ["audio_received", "audio_format", "audio_decoded", "audio_receive_finished", "audio_playback_started", "audio_playback_finished", "INVALID_BASE64"]:
		check(log_text.contains(event), "diagnostic stage " + event)
	audio.queue_free()
	await process_frame
	AudioServer.remove_bus_effect(0,AudioServer.get_bus_effect_count(0)-1)
	logger.finish()
	for file in DirAccess.get_files_at(directory):
		DirAccess.remove_absolute(directory.path_join(file))
	DirAccess.remove_absolute(directory)

func test_lifecycle() -> void:
	var clock: Array[int] = [0]
	var lifecycle_received: Array[String] = []
	var lifecycle_played: Array[String] = []
	var lifecycle_codes: Dictionary = {}
	var audio := Audio.new(null,func(): return clock[0])
	root.add_child(audio)
	audio.receive_finished.connect(func(id, _code): lifecycle_received.append(id))
	audio.playback_finished.connect(func(id, code): lifecycle_played.append(id); lifecycle_codes[id] = code)
	audio.append_reply_audio("text", "", true)
	audio.play_reply("text")
	await process_frame
	await process_frame
	audio.append_reply_audio("text", "", true)
	audio.play_reply("text")
	await process_frame
	await process_frame
	check(lifecycle_received.count("text") == 1 and lifecycle_played.count("text") == 1, "completed UUID rejects duplicate termination")
	audio.append_reply_audio("bad", "A===", true)
	audio.play_reply("bad")
	audio.stop_current()
	await process_frame
	await process_frame
	check(lifecycle_codes.get("bad") == "INVALID_BASE64", "stop does not overwrite decode error")
	audio.append_reply_audio("timeout", "", false)
	audio.play_reply("timeout")
	clock[0] = 60001
	await process_frame
	await process_frame
	check(lifecycle_codes.get("timeout") == "AUDIO_TIMEOUT", "missing continuation terminates at 60 seconds")
	audio.reset()
	for i in 16:
		audio.append_reply_audio("queue-%s" % i, "", false)
	audio.append_reply_audio("overflow", "", true)
	check(lifecycle_codes.get("overflow") == "BUFFER_LIMIT", "17th pending reply rejected")
	audio.append_reply_audio("queue-0", "", true)
	audio.play_reply("queue-0")
	await process_frame
	await process_frame
	audio.append_reply_audio("overflow", "", true)
	audio.play_reply("overflow")
	await process_frame
	await process_frame
	check(lifecycle_played.count("overflow") == 1 and lifecycle_received.count("overflow") == 1, "rejected UUID cannot restart after capacity frees")
	audio.reset()
	var header := Samples.tone(0)
	header.encode_u32(40,0xffffffff)
	var pcm := PackedByteArray()
	pcm.resize(2*1024*1024)
	var encoded := Marshalls.raw_to_base64(pcm)
	for i in 8:
		var id := "memory-%s" % i
		audio.append_reply_audio(id,Marshalls.raw_to_base64(header),false)
		audio.append_reply_audio(id,encoded,false)
		audio.append_reply_audio(id,encoded,false)
	audio.append_reply_audio("memory-7",encoded,false)
	check(lifecycle_received.has("memory-7"), "aggregate memory bound fails receiving stream")
	audio.play_reply("memory-7")
	await process_frame
	await process_frame
	check(lifecycle_codes.get("memory-7") == "BUFFER_LIMIT", "aggregate decoder buffers bounded across UUIDs")
	audio.reset()
	audio.queue_free()
	await process_frame
