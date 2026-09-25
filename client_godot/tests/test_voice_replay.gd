extends SceneTree
var Audio = load("res://tests/support/native_reply_audio.gd")
const Cache = preload("res://src/storage/audio_cache.gd")
const Samples = preload("res://tests/support/audio_samples.gd")
var failures: Array[String] = []
var capture := AudioEffectCapture.new()
var peak := 0.0
var online: Array[String] = []
var replayed: Array[String] = []
var mouth := -1.0

func check(value: bool, description: String) -> void:
	if not value:
		failures.append(description)
		print("FAIL: ",description)

func wait_for(predicate: Callable, timeout: int = 3500) -> bool:
	var deadline := Time.get_ticks_msec() + timeout
	while not predicate.call() and Time.get_ticks_msec() < deadline:
		await process_frame
		for frame in capture.get_buffer(capture.get_frames_available()):
			peak = maxf(peak,absf(frame.x))
	return predicate.call()

func delay(seconds: float) -> void:
	await wait_for(func(): return false, int(seconds*1000))

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	# Capability assertion produces a behavior failure on the pre-replay implementation.
	var probe = Audio.new()
	check(probe.has_method("replay"), "complete received voice exposes replay operations")
	probe.free()
	if not failures.is_empty():
		quit(1)
		return
	AudioServer.add_bus_effect(0,capture)
	var directory := "user://replay-test-%s" % Time.get_ticks_usec()
	var cache = Cache.new(directory)
	var audio = Audio.new(null,Callable(),cache)
	root.add_child(audio)
	check(audio.set_scope("https://example.test/", "alice") == OK,"cache scope configured")
	audio.playback_finished.connect(func(id,_code): online.append(id))
	audio.replay_finished.connect(func(id,_code): replayed.append(id))
	audio.mouth_changed.connect(func(value): mouth = value)
	var bytes := Samples.tone(1.2)
	audio.append_reply_audio("one",Marshalls.raw_to_base64(bytes),true)
	check(audio.get_message_audio("one").available,"successful terminal publishes replay")
	check(audio.get_message_audio("one").waveform.size() == 24,"real waveform available")
	audio.play_reply("one")
	check(await wait_for(func(): return online.has("one")),"online voice drains")
	peak = 0
	capture.clear_buffer()
	check(audio.replay("one") == OK,"complete voice starts replay")
	check(await wait_for(func(): return audio.get_message_audio("one").position > .18),"replay position follows mixer")
	check(peak > .05,"replay produces actual mixer output")
	audio.pause_replay()
	var paused: float = audio.get_message_audio("one").position
	await delay(.12)
	peak = 0
	capture.clear_buffer()
	await delay(.16)
	check(peak < .0001 and mouth == -1.0,"paused replay is silent and mouth restores")
	check(audio.get_message_audio("one").position == paused,"paused progress freezes")
	audio.resume_replay()
	check(await wait_for(func(): return audio.get_message_audio("one").position > paused + .08),"resume continues from paused position")
	check(await wait_for(func(): return replayed.has("one")),"natural replay completion")
	check(online == ["one"] and audio.get_message_audio("one").position == 0,"replay completion does not complete online twice")
	audio.replay("one")
	await delay(.1)
	audio.stop_replay()
	audio.stop_replay()
	check(audio.get_message_audio("one").status == "idle", "stop is idempotent")
	audio.replay("one")
	check(audio.get_message_audio("one").position < .05,"play after stop starts at beginning")
	audio.append_reply_audio("two",Marshalls.raw_to_base64(bytes),true)
	check(audio.replay("two") == OK and audio.get_message_audio("one").status == "idle","switch replay stops old message")
	audio.pause_replay()
	audio.play_reply("two")
	check(await wait_for(func(): return audio.get_state().playing),"online voice starts")
	check(audio.get_message_audio("two").status == "idle" and audio.replay("one") == ERR_BUSY,"online voice preempts paused replay and blocks replay")
	check(await wait_for(func(): return online.has("two")),"online preemption drains normally")
	audio.replay("one")
	audio.append_reply_audio("stopped",Marshalls.raw_to_base64(bytes.slice(0,15000)),false)
	audio.play_reply("stopped")
	await wait_for(func(): return audio.get_state().playing)
	check(audio.get_message_audio("one").status == "idle","online preempts playing replay")
	audio.stop_current()
	audio.append_reply_audio("stopped",Marshalls.raw_to_base64(bytes.slice(15000)),true)
	check(await wait_for(func(): return online.has("stopped")),"stopped online terminal still completes")
	check(audio.get_message_audio("stopped").available and is_equal_approx(audio.get_message_audio("stopped").duration,1.2),"stopped output still saves full stream")
	audio.append_reply_audio("ephemeral",Marshalls.raw_to_base64(bytes),true,false,true)
	audio.append_reply_audio("error",Marshalls.raw_to_base64(bytes.slice(0,100)),false)
	audio.append_reply_audio("error","",true,true)
	check(not audio.get_message_audio("ephemeral").available and not audio.get_message_audio("error").available,"temporary and failed voices not replayable")
	audio.append_reply_audio("clearing",Marshalls.raw_to_base64(bytes.slice(0,15000)),false)
	audio.play_reply("clearing")
	await wait_for(func(): return audio.get_state().playing)
	check(audio.clear_cache() == OK and audio.get_state().playing,"manual clear keeps online audio playing")
	audio.append_reply_audio("clearing",Marshalls.raw_to_base64(bytes.slice(15000)),true)
	check(not audio.get_message_audio("clearing").available and not audio.get_message_audio("one").available,"clear removes complete entries and suppresses current stream")
	audio.reset()
	audio.append_reply_audio("saved",Marshalls.raw_to_base64(bytes),true)
	audio.append_reply_audio("partial",Marshalls.raw_to_base64(bytes.slice(0,100)),false)
	audio.reset()
	check(not audio.get_message_audio("partial").available and audio.get_message_audio("saved").available,"reset aborts partial but preserves complete")
	audio.set_scope("https://example.test","bob")
	check(not audio.get_message_audio("saved").available,"account isolation")
	audio.set_scope("https://another.test","alice")
	check(not audio.get_message_audio("saved").available,"server isolation")
	audio.queue_free()
	await process_frame
	var restored = Audio.new(null,Callable(),Cache.new(directory))
	root.add_child(restored)
	restored.set_scope("https://example.test","alice")
	check(restored.get_message_audio("saved").available and restored.replay("saved") == OK,"new instance restores persisted voice")
	restored.clear_cache()
	restored.queue_free()
	await process_frame
	var blocker := directory.path_join("blocker")
	FileAccess.open(blocker,FileAccess.WRITE).close()
	var broken = Audio.new(null,Callable(),Cache.new(blocker + "/audio"))
	root.add_child(broken)
	broken.set_scope("https://example.test","alice")
	broken.append_reply_audio("unsaved",Marshalls.raw_to_base64(bytes),true)
	broken.play_reply("unsaved")
	check(await wait_for(func(): return broken.get_state().playing),"write failure does not prevent online output")
	check(not broken.get_message_audio("unsaved").available and broken.get_message_audio("unsaved").code == "CACHE_WRITE_FAILED","write failure gives explicit unavailable state")
	broken.queue_free()
	await process_frame
	DirAccess.remove_absolute(blocker)
	for scope in DirAccess.get_directories_at(directory):
		check(DirAccess.get_files_at(directory.path_join(scope)).is_empty(),"no interrupted temporary files remain")
		DirAccess.remove_absolute(directory.path_join(scope))
	DirAccess.remove_absolute(directory)
	AudioServer.remove_bus_effect(0,AudioServer.get_bus_effect_count(0)-1)
	print("Voice replay: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
