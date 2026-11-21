extends SceneTree
var failures: Array[String] = []
func check(value: bool, label: String) -> void:
	if not value: failures.append(label); print("FAIL: ",label)
func _initialize() -> void:
	run.call_deferred()
func run() -> void:
	# No native decoder: receiving and playback still finish once, with an error.
	var audio = preload("res://src/media/reply_audio.gd").new()
	root.add_child(audio)
	var received: Array = []
	var played: Array = []
	audio.receive_finished.connect(func(id,code): received.append([id,code]))
	audio.playback_finished.connect(func(id,code): played.append([id,code]))
	var tone = preload("res://tests/support/audio_samples.gd").tone()
	audio.append_reply_audio("missing",Marshalls.raw_to_base64(tone),true)
	audio.play_reply("missing")
	await process_frame
	await process_frame
	check(received == [["missing","DECODER_UNAVAILABLE"]], "missing decoder reports receive failure once")
	check(played == received, "missing decoder releases the reply queue")
	audio.append_reply_audio("missing",Marshalls.raw_to_base64(tone),true)
	audio.reset()
	audio.reset()
	check(received.size() == 1 and played.size() == 1, "late final/reset cannot duplicate termination")
	audio.free()
	# Real cache stream is explicitly closeable without exposing FileAccess.
	var path := "user://capability-stream-%s.bin" % Time.get_ticks_usec()
	var file := FileAccess.open(path,FileAccess.WRITE)
	file.store_buffer(tone)
	file.close()
	var stream = preload("res://src/storage/godot_read_stream.gd").new(FileAccess.open(path,FileAccess.READ))
	check(stream.get_buffer(4).get_string_from_ascii() == "RIFF", "stream returns existing file bytes")
	var replay = preload("res://src/media/cache_replay.gd").new()
	root.add_child(replay)
	check(replay.start("missing",{"duration":.3},stream,preload("res://src/media/decoder_factory.gd").new()) == ERR_UNAVAILABLE, "replay rejects missing decoder")
	check(stream.get_buffer(1).is_empty(), "failed replay closes its stream")
	replay.stop()
	replay.free()
	DirAccess.remove_absolute(path)
	print("Capability failures: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
