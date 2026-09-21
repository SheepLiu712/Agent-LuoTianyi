extends Node
signal message_audio_changed(id: String, state: Dictionary)
signal replay_finished(id: String, code: String)
signal receive_finished(id: String, code: String)
signal playback_finished(id: String, code: String)
signal mouth_changed(value: float)
signal state_changed(state: Dictionary)

var _decoder_factory: Resource
var _cache: RefCounted
var _metadata: Dictionary = {}
var _cache_errors: Dictionary = {}
var _replay = preload("res://src/media/cache_replay.gd").new()
var _logger: RefCounted
var _streams: Dictionary = {}
var _completed: Dictionary = {}
var _clock: Callable
var _active := ""
var _player := AudioStreamPlayer.new()
var _playback: AudioStreamGeneratorPlayback
var _capacity := 0
var _pushed := 0
var _drain_at := 0
var _volume := 1.0
var _skips := 0
var _invalid_base64 := RegEx.new()

func _init(logger: RefCounted = null, clock: Callable = Callable(), cache: RefCounted = null, decoder_factory: Resource = null) -> void:
	_decoder_factory = decoder_factory if decoder_factory != null else preload("res://src/media/decoder_factory.gd").new()
	_cache = cache
	add_child(_replay)
	_replay.changed.connect(func(): _notify_audio(_replay.id))
	_replay.mouth_changed.connect(func(value): mouth_changed.emit(value))
	_replay.finished.connect(func(id,code):
		if not code.is_empty():
			_cache_errors[id] = code
			_metadata[id] = {}
			_notify_audio(id)
		_log("replay_finished",id,{"code":code})
		replay_finished.emit(id,code))
	_logger = logger
	_clock = clock if clock.is_valid() else Time.get_ticks_msec
	process_mode = Node.PROCESS_MODE_ALWAYS
	_invalid_base64.compile("^[A-Za-z0-9+/]*={0,2}$")
	add_child(_player)

func append_reply_audio(id: String, encoded: String, final: bool, audio_error: bool = false, ephemeral: bool = false) -> void:
	if _completed.has(id):
		return
	if not _streams.has(id):
		if _streams.size() >= 16:
			_completed[id] = true
			_log("audio_error", id, {"code":"BUFFER_LIMIT"})
			_log("audio_receive_finished", id, {"code":"BUFFER_LIMIT"})
			_log("audio_playback_finished", id, {"code":"BUFFER_LIMIT"})
			receive_finished.emit(id, "BUFFER_LIMIT")
			playback_finished.emit(id, "BUFFER_LIMIT")
			return
		_streams[id] = {"decoder":null, "final":false, "code":"", "stopped":false,
			"updated":_clock.call(), "format_logged":false, "cache_started":false, "cache_suppressed":false}
	var item: Dictionary = _streams[id]
	if item.final:
		return
	item.updated = _clock.call()
	if ephemeral:
		item.cache_suppressed = true
		if _cache != null:
			_cache.abort(id)
	if audio_error:
		_fail(id, "AUDIO_ERROR")
		return
	if not encoded.is_empty():
		if encoded.length() > 12 * 1024 * 1024 or encoded.length() % 4 != 0 or _invalid_base64.search(encoded) == null:
			_fail(id, "INVALID_BASE64")
			return
		var bytes := Marshalls.base64_to_raw(encoded)
		if bytes.is_empty() or Marshalls.raw_to_base64(bytes) != encoded:
			_fail(id, "INVALID_BASE64")
			return
		_log("audio_received", id, {"bytes":bytes.size()})
		if _cache != null and not item.cache_suppressed:
			if not item.cache_started:
				var result: Error = _cache.begin(id)
				if result == ERR_ALREADY_EXISTS:
					item.cache_suppressed = true
				elif result != OK:
					_cache_failed(id)
				else:
					item.cache_started = true
			if item.cache_started and not item.cache_suppressed and _cache.append(id,bytes) != OK:
				_cache_failed(id)
		if item.decoder == null:
			item.decoder = _decoder_factory.create_decoder()
			if item.decoder == null:
				_fail(id, "DECODER_UNAVAILABLE")
				return
		var status: Dictionary = item.decoder.append(bytes)
		if not status.ok:
			_fail(id, status.code)
			return
		if status.sample_rate > 0 and not item.format_logged:
			_log("audio_format", id, status)
			item.format_logged = true
		_log("audio_decoded", id, {"frames":status.decoded_frames, "queued":status.queued_frames})
		if item.stopped:
			item.decoder.read_frames(status.queued_frames)
		var queued_frames := 0
		for other in _streams.values():
			if other.decoder != null:
				queued_frames += int(other.decoder.get_status().queued_frames)
		if queued_frames > 128 * 1024 * 1024 / 8:
			_fail(id, "BUFFER_LIMIT")
			return
	if final:
		if item.decoder != null:
			var status: Dictionary = item.decoder.finish()
			if not status.ok:
				_fail(id, status.code)
				return
			if _cache != null and item.cache_started and not item.cache_suppressed:
				if _cache.commit(id,status,item.decoder.get_waveform()) != OK:
					_cache_failed(id)
				else:
					_metadata.erase(id)
					_notify_audio(id)
		_end_receive(id)

func play_reply(id: String) -> void:
	if _active.is_empty() and _streams.has(id):
		_active = id
		state_changed.emit(get_state())

func get_state() -> Dictionary:
	return {"active_id":_active, "playing":_player.playing, "queued":_streams.size(), "volume":_volume}

func set_volume(value: float) -> void:
	if not is_finite(value):
		return
	_volume = clampf(value, 0, 1)
	_player.volume_linear = _volume
	_replay.set_volume(_volume)
	state_changed.emit(get_state())

func stop_current() -> void:
	if _streams.has(_active):
		var item: Dictionary = _streams[_active]
		item.stopped = true
		if item.code.is_empty():
			item.code = "STOPPED"
		if item.decoder != null:
			item.decoder.read_frames(item.decoder.get_status().queued_frames)
		_stop_player()

func reset() -> void:
	stop_replay()
	if _cache != null:
		_cache.abort_all()
	for id in _streams:
		_log("audio_playback_finished", id, {"code":"INTERRUPTED"})
	_streams.clear()
	_completed.clear()
	_active = ""
	_stop_player()

func _log(event: String, id: String, fields: Dictionary = {}) -> void:
	if _logger != null:
		fields["reply_id"] = id
		_logger.record(event, fields)

func _end_receive(id: String) -> void:
	var item: Dictionary = _streams[id]
	if not item.final:
		item.final = true
		_log("audio_receive_finished", id, {"code":item.code})
		receive_finished.emit(id, item.code)

func _fail(id: String, code: String) -> void:
	var item: Dictionary = _streams[id]
	item.code = code
	if _cache != null:
		_cache.abort(id)
	item.decoder = null
	_log("audio_error", id, {"code":code})
	_end_receive(id)
	if id == _active:
		_stop_player()

func _stop_player() -> void:
	_player.stop()
	_playback = null
	_pushed = 0
	_drain_at = 0
	mouth_changed.emit(-1.0)
	state_changed.emit(get_state())
	_notify_all_audio()

func _complete() -> void:
	var id := _active
	var code: String = _streams[id].code
	_completed[id] = true
	_streams.erase(id)
	_active = ""
	_stop_player()
	_log("audio_playback_finished", id, {"code":code})
	playback_finished.emit(id, code)

func _process(_delta: float) -> void:
	var now: int = _clock.call()
	for id in _streams.keys():
		if not _streams[id].final and now - int(_streams[id].updated) >= 60000:
			_fail(id, "AUDIO_TIMEOUT")
	if not _streams.has(_active):
		return
	var item: Dictionary = _streams[_active]
	if item.decoder == null or item.stopped:
		if item.final:
			_complete()
		return
	var status: Dictionary = item.decoder.get_status()
	if _playback == null:
		if status.sample_rate == 0 or status.queued_frames == 0 or (not item.final and status.queued_frames < status.sample_rate * .08):
			return
		if not _replay.id.is_empty():
			_log("replay_preempted",_replay.id)
			stop_replay()
		var generator := AudioStreamGenerator.new()
		generator.mix_rate = status.sample_rate
		generator.buffer_length = .25
		_player.stream = generator
		_player.play()
		_playback = _player.get_stream_playback()
		_capacity = _playback.get_frames_available()
		_pushed = 0
		_skips = _playback.get_skips()
		_log("audio_playback_started", _active, {"sample_rate":status.sample_rate, "volume":_volume,
			"latency_ms":AudioServer.get_output_latency() * 1000})
		state_changed.emit(get_state())
		_notify_all_audio()
	var available := _playback.get_frames_available()
	var buffered := _capacity - available
	var heard := _pushed - buffered - int(AudioServer.get_output_latency() * status.sample_rate)
	mouth_changed.emit(clampf(item.decoder.get_amplitude(heard) * 3.0, 0, 1))
	var skips := _playback.get_skips()
	if skips > _skips and not item.final:
		_log("audio_underrun", _active, {"skips":skips - _skips})
	_skips = skips
	var count := mini(available, mini(int(status.queued_frames), 16384))
	if count > 0:
		var frames: PackedVector2Array = item.decoder.read_frames(count)
		if not _playback.push_buffer(frames):
			_fail(_active, "PLAYBACK_FAILED")
			return
		_pushed += frames.size()
		_drain_at = 0
	elif item.final and buffered == 0:
		if _drain_at == 0:
			_drain_at = now + ceili((AudioServer.get_output_latency() + AudioServer.get_time_to_next_mix()) * 1000) + 10
		elif now >= _drain_at:
			_complete()

func _exit_tree() -> void:
	reset()

func set_scope(server: String, username: String) -> Error:
	reset()
	_metadata.clear()
	_cache_errors.clear()
	# A cache is optional for text chat.  Lack of the replay capability must
	# not make the transport/account session fail to start.
	return _cache.set_scope(server,username) if _cache != null else OK

func get_message_audio(id: String) -> Dictionary:
	if not _metadata.has(id):
		_metadata[id] = _cache.lookup(id) if _cache != null else {}
	var data: Dictionary = _metadata[id]
	return {"available":not data.is_empty(), "duration":data.get("duration",0.0),
		"waveform":data.get("waveform",PackedFloat32Array()), "blocked":_player.playing,
		"status":_replay.status if _replay.id == id else "idle",
		"position":_replay.position if _replay.id == id else 0.0, "code":_cache_errors.get(id,"")}

func replay(id: String) -> Error:
	if _player.playing:
		return ERR_BUSY
	if _replay.id == id and _replay.status == "playing":
		return OK
	_metadata.erase(id)
	if not get_message_audio(id).available:
		_notify_audio(id)
		return ERR_DOES_NOT_EXIST
	stop_replay()
	var result: Error = _replay.start(id,_metadata[id],_cache.open_stream(id),_decoder_factory)
	if result != OK:
		_cache_errors[id] = "REPLAY_FAILED"
		_metadata[id] = {}
		_notify_audio(id)
	else:
		_log("replay_started",id)
	return result

func pause_replay() -> void:
	if _replay.status == "playing":
		_log("replay_paused",_replay.id)
		_replay.pause()

func resume_replay() -> void:
	if not _player.playing and _replay.status == "paused":
		_log("replay_resumed",_replay.id)
		_replay.resume()

func stop_replay() -> void:
	if not _replay.id.is_empty():
		_log("replay_stopped",_replay.id)
		_replay.stop()

func clear_cache(older_than_days: int = 0) -> Error:
	if older_than_days < 0: return ERR_INVALID_PARAMETER
	stop_replay()
	if older_than_days == 0:
		for item in _streams.values(): item.cache_suppressed = true
	var ids := _metadata.keys()
	var result: Error = _cache.clear(older_than_days) if _cache != null else ERR_UNCONFIGURED
	_metadata.clear()
	_cache_errors.clear()
	for id in ids:
		_notify_audio(id)
	return result

func _cache_failed(id: String) -> void:
	_streams[id].cache_suppressed = true
	_cache.abort(id)
	_cache_errors[id] = "CACHE_WRITE_FAILED"
	_log("cache_error",id,{"code":"CACHE_WRITE_FAILED"})
	_notify_audio(id)

func _notify_audio(id: String) -> void:
	if not id.is_empty():
		message_audio_changed.emit(id,get_message_audio(id))

func _notify_all_audio() -> void:
	for id in _metadata.keys():
		_notify_audio(id)
