extends Node
## Internal media sink; only ReplyAudio arbitrates ownership of sound and mouth.
signal changed
signal finished(id: String, code: String)
signal mouth_changed(value: float)
var id := ""
var status := "idle"
var position := 0.0
var _file: RefCounted
var _decoder: RefCounted
var _player := AudioStreamPlayer.new()
var _playback: AudioStreamGeneratorPlayback
var _capacity := 0
var _pushed := 0
var _drain_at := 0
var _notify_at := 0
var _duration := 0.0

func _init() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	add_child(_player)

func start(reply_id: String, metadata: Dictionary, stream: RefCounted, factory: Resource) -> Error:
	stop()
	_file = stream
	if _file == null:
		return ERR_CANT_OPEN
	_decoder = factory.create_decoder()
	if _decoder == null:
		stop()
		return ERR_UNAVAILABLE
	id = reply_id
	_duration = metadata.duration
	status = "playing"
	changed.emit()
	return OK

func set_volume(value: float) -> void:
	_player.volume_linear = value

func pause() -> void:
	if status == "playing":
		_player.stream_paused = true
		status = "paused"
		mouth_changed.emit(-1.0)
		changed.emit()

func resume() -> void:
	if status == "paused":
		_player.stream_paused = false
		status = "playing"
		_drain_at = 0
		changed.emit()

func stop() -> void:
	var previous := id
	_player.stop()
	_player.stream_paused = false
	_playback = null
	if _file != null:
		_file.close()
	_file = null
	_decoder = null
	status = "idle"
	position = 0
	_pushed = 0
	_drain_at = 0
	if not previous.is_empty():
		mouth_changed.emit(-1.0)
		changed.emit()
	id = ""

func _end(code: String) -> void:
	var previous := id
	stop()
	finished.emit(previous,code)

func _process(_delta: float) -> void:
	if status != "playing":
		return
	var decoded: Dictionary = _decoder.get_status()
	if _file != null and decoded.queued_frames < maxi(4096,int(decoded.sample_rate)/2):
		decoded = _decoder.append(_file.get_buffer(65536))
		if _file.get_position() >= _file.get_length():
			_file.close()
			_file = null
			decoded = _decoder.finish()
		if not decoded.ok:
			_end("REPLAY_FAILED")
			return
	if _playback == null:
		if decoded.sample_rate == 0 or decoded.queued_frames == 0:
			return
		var generator := AudioStreamGenerator.new()
		generator.mix_rate = decoded.sample_rate
		generator.buffer_length = .25
		_player.stream = generator
		_player.play()
		_playback = _player.get_stream_playback()
		_capacity = _playback.get_frames_available()
	var available := _playback.get_frames_available()
	var buffered := _capacity - available
	var heard := maxi(0,_pushed - buffered - int(AudioServer.get_output_latency()*decoded.sample_rate))
	position = minf(_duration,float(heard)/decoded.sample_rate)
	mouth_changed.emit(clampf(_decoder.get_amplitude(heard)*3.0,0,1))
	var count := mini(available,mini(int(decoded.queued_frames),16384))
	if count > 0:
		var frames: PackedVector2Array = _decoder.read_frames(count)
		if not _playback.push_buffer(frames):
			_end("REPLAY_FAILED")
			return
		_pushed += frames.size()
		_drain_at = 0
	elif decoded.finished and buffered == 0:
		if _drain_at == 0:
			_drain_at = Time.get_ticks_msec() + ceili((AudioServer.get_output_latency()+AudioServer.get_time_to_next_mix())*1000) + 10
		elif Time.get_ticks_msec() >= _drain_at:
			_end("")
			return
	if Time.get_ticks_msec() >= _notify_at:
		_notify_at = Time.get_ticks_msec() + 50
		changed.emit()

func _exit_tree() -> void:
	stop()
