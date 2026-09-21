extends RefCounted
signal entry_added(entry: Dictionary)
signal write_failed(error: int)
const Release = preload("res://src/storage/release_info.gd")
const METRICS := ["has_audio", "audio_chars", "bytes", "frames", "sample_rate", "channels", "bits", "final", "audio_error", "queued", "volume", "latency_ms", "skips", "count", "status", "index", "duration_ms"]
const MODULES := ["app", "account", "network", "message", "audio", "cache", "history", "settings", "dynamics", "engine"]
const CODES := "OK UNKNOWN INVALID_INPUT INVALID_RESPONSE BUSY CANCELLED TIMEOUT NETWORK_ERROR HTTP_ERROR AUTH_REJECTED PUBLIC_KEY_ERROR ENCRYPTION_ERROR CREDENTIAL_UNAVAILABLE NO_SAVED_LOGIN LOGGED_OUT PENDING SEND_REJECTED DELIVERY_UNCERTAIN TRANSPORT_STOPPED ACK_TIMEOUT DISCONNECTED CONNECT_TIMEOUT AUTH_TIMEOUT INVALID_BASE64 AUDIO_ERROR AUDIO_TIMEOUT BUFFER_LIMIT DECODER_UNAVAILABLE PLAYBACK_FAILED REPLAY_FAILED CACHE_WRITE_FAILED CACHE_CLEAR_FAILED INVALID_WAV UNSUPPORTED_FORMAT TRUNCATED_AUDIO EMPTY_AUDIO STREAM_FINISHED STOPPED INTERRUPTED ENGINE_ERROR ENGINE_WARNING HISTORY_FAILED HISTORY_INVALID HISTORY_DUPLICATE MODEL_ERROR MODEL_DISABLED MODEL_INVALID SAVE_FAILED INVALID_JSON MODEL_BUSY UNKNOWN_MODEL_TYPE INVALID_CONFIG MODEL_KIND_MISMATCH MODEL_CAPABILITY_MISMATCH MODEL_FIELDS_REQUIRED STREAMING_NOT_SUPPORTED PLAINTEXT_CONFIRMATION_REQUIRED KEY_UNAVAILABLE NOT_FOUND COMMENT_NOT_ALLOWED INVALID_REPLY_TARGET"
const PHASES := "saving first_loading first_failed idle connecting authenticating ready reconnecting auth_rejected signed_out signed_in busy queued sending sent failed uncertain loading complete error skipped playing paused stopped"
const EXPLANATIONS := {"dynamics_state":"动态读取与写入状态", "settings_models":"模型配置状态", "settings_model_execution":"模型请求执行", "settings_preference":"相处偏好操作", "client_started":"客户端启动", "client_stopped":"客户端正常退出", "history_state":"历史同步状态", "account_state":"账户操作状态", "message_queued":"消息已进入发送队列", "message_delivery":"消息投递状态", "engine_error":"引擎报告异常（原始内容不写入日志）", "connection_state":"聊天连接状态变化", "reply_received":"收到回复分片", "system_error":"操作出现错误", "cache_committed":"完整语音已保存", "cache_error":"语音未能保存", "cache_cleared":"已执行语音缓存清理", "audio_received":"收到音频数据", "audio_format":"已识别音频格式", "audio_decoded":"音频解码完成", "audio_receive_finished":"音频接收结束", "audio_error":"音频处理失败", "audio_underrun":"音频缓冲暂时不足", "audio_playback_started":"开始播放在线语音", "audio_playback_finished":"在线语音播放结束", "replay_preempted":"在线语音打断本地重放", "replay_finished":"重放结束", "replay_started":"开始重放", "replay_paused":"重放已暂停", "replay_resumed":"继续重放", "replay_stopped":"重放已停止"}
var _environment: Resource
var _directory: String
var _token := RegEx.new()
var _id_pattern := RegEx.new()
var _id: String
var _entries: Array[Dictionary] = []
var _started := Time.get_ticks_msec()
var _meta: Dictionary
var _initialized := false
var _closed := false

func _init(directory: String = "user://logs", _legacy_max_bytes: int = 2097152, environment: Resource = null) -> void:
	_environment = environment if environment != null else preload("res://src/platform/godot_runtime_environment.gd").new()
	_directory = directory
	_token.compile("^[a-zA-Z0-9_]{1,64}$")
	_id_pattern.compile("^[0-9]{20}_[0-9]+_[a-f0-9]{12}$")
	_id = "%020d_%d_%s" % [int(Time.get_unix_time_from_system() * 1000000), _environment.process_id(), Crypto.new().generate_random_bytes(6).hex_encode()]
	_meta = {"id":_id, "started":Time.get_datetime_string_from_system(true) + "Z", "pid":_environment.process_id(), "closed":false, "complete":true,
		"release":Release.get_info(), "engine":Engine.get_version_info().string, "os":_environment.os_name(), "architecture":Engine.get_architecture_name()}

func record(event: String, fields: Dictionary = {}) -> Error:
	if _closed or _token.search(event) == null:
		return ERR_INVALID_PARAMETER
	var entry := {"time":Time.get_datetime_string_from_system(true) + "Z", "elapsed_ms":Time.get_ticks_msec() - _started, "event":event,
		"level":"ERROR" if event.contains("error") else "INFO", "module":_module(event), "message":EXPLANATIONS.get(event, "客户端活动")}
	for key in METRICS:
		var value: Variant = fields.get(key)
		if value is bool or value is int or (value is float and is_finite(value)):
			entry[key] = value
	for key in ["phase", "code"]:
		if fields.get(key) is String and _token.search(fields[key]) != null:
			entry[key] = _safe_code(key, fields[key])
	if fields.get("level") in ["INFO", "WARN", "ERROR"]:
		entry.level = fields.level
	if fields.get("module") in MODULES:
		entry.module = fields.module
	if fields.get("reply_id") is String:
		entry.reply_id = fields.reply_id.sha256_text().left(12)
	_entries.append(entry)
	var error := _ensure_directory()
	if error == OK:
		var path := _path(_id, ".jsonl")
		var file := FileAccess.open(path, FileAccess.READ_WRITE if FileAccess.file_exists(path) else FileAccess.WRITE)
		if file == null:
			error = FileAccess.get_open_error()
		else:
			file.seek_end()
			file.store_line(JSON.stringify(entry))
			file.flush()
			error = file.get_error()
			file.close()
	if error != OK:
		_meta.complete = false
		_save_metadata()
		write_failed.emit(error)
	entry_added.emit(entry.duplicate(true))
	return error

func get_directory() -> String:
	return ProjectSettings.globalize_path(_directory)

func get_run_id() -> String:
	return _id

func finish() -> void:
	if _closed:
		return
	record("client_stopped")
	_closed = true
	_meta.closed = true
	if _save_metadata() != OK:
		_meta.complete = false
		write_failed.emit(ERR_CANT_CREATE)

func list_runs() -> Array[Dictionary]:
	var runs: Array[Dictionary] = []
	if not DirAccess.dir_exists_absolute(_directory):
		return runs
	for file in DirAccess.get_files_at(_directory):
		var id := file.trim_suffix(".json")
		if not file.ends_with(".json") or _id_pattern.search(id) == null:
			continue
		var data: Variant = JSON.parse_string(FileAccess.get_file_as_string(_path(id, ".json")))
		if not data is Dictionary or data.get("id") != id or not data.get("pid") is float and not data.get("pid") is int:
			continue
		data.active = not data.get("closed",false) and _environment.process_running(int(data.pid))
		data.complete = data.get("complete",false) and _read_archive(id).complete
		runs.append(data)
	runs.sort_custom(func(a,b): return a.id > b.id)
	return runs

func read_entries(run_id: String = "") -> Array[Dictionary]:
	if run_id.is_empty() or run_id == _id:
		return _entries.duplicate(true)
	var result: Array[Dictionary] = []
	result.assign(_read_archive(run_id).entries)
	return result

func export_run(run_id: String, destination_zip: String) -> Error:
	if FileAccess.file_exists(destination_zip):
		return ERR_ALREADY_EXISTS
	var metadata: Dictionary = {}
	for run in list_runs():
		if run.id == run_id:
			metadata = run
	if run_id == _id:
		metadata = _meta.duplicate(true)
	if metadata.is_empty():
		return ERR_DOES_NOT_EXIST
	var read := _read_archive(run_id) if run_id != _id else {"entries":read_entries(), "complete":_meta.complete}
	var events := ""
	var readable := ""
	for entry in read.entries:
		events += JSON.stringify(entry) + "\n"
		readable += "%s [%s] [%s] %s (%s) %s\n" % [entry.time,entry.level,entry.module,entry.message,entry.event,entry.get("code", "")]
	# Do not export arbitrary on-disk metadata, paths or environment variables.
	var summary := {"release":metadata.get("release",Release.get_info()), "engine":Engine.get_version_info().string,
		"os":_environment.os_name(), "architecture":Engine.get_architecture_name(), "closed":metadata.get("closed",false),
		"complete":metadata.get("complete",false) and read.complete, "count":read.entries.size()}
	var zip := ZIPPacker.new()
	var error := zip.open(destination_zip)
	if error != OK:
		return error
	for pair in [["events.jsonl",events],["readable.txt",readable],["environment.json",JSON.stringify(summary)]]:
		error = zip.start_file(pair[0])
		if error == OK:
			error = zip.write_file(pair[1].to_utf8_buffer())
		if error == OK:
			error = zip.close_file()
		if error != OK:
			break
	var closed := zip.close()
	if error == OK:
		error = closed
	if error != OK:
		DirAccess.remove_absolute(destination_zip)
	return error

func _ensure_directory() -> Error:
	if _initialized:
		return OK
	var ancestor := _directory
	while not ancestor.is_empty():
		if FileAccess.file_exists(ancestor):
			return ERR_CANT_CREATE
		var parent := ancestor.get_base_dir()
		if parent == ancestor:
			break
		ancestor = parent
	var error := DirAccess.make_dir_recursive_absolute(_directory)
	if error != OK:
		return error
	error = _save_metadata()
	if error == OK:
		_initialized = true
		_prune()
	return error

func _save_metadata() -> Error:
	var file := FileAccess.open(_path(_id, ".json"), FileAccess.WRITE)
	if file == null:
		return FileAccess.get_open_error()
	file.store_string(JSON.stringify(_meta))
	file.flush()
	var error := file.get_error()
	file.close()
	return error

func _prune() -> void:
	var runs := list_runs()
	var excess := runs.size() - 50
	runs.reverse()
	for run in runs:
		if excess <= 0:
			break
		if run.active or run.id == _id:
			continue
		var error := OK
		for suffix in [".jsonl", ".json"]:
			var path := _path(run.id, suffix)
			if FileAccess.file_exists(path):
				error = DirAccess.remove_absolute(path)
				if error != OK:
					break
		if error == OK:
			excess -= 1
		else:
			write_failed.emit(error)

func _path(id: String, suffix: String) -> String:
	return _directory.path_join(id + suffix)

func _module(event: String) -> String:
	for module in MODULES:
		if event.begins_with(module + "_"):
			return module
	if event.begins_with("replay_"):
		return "audio"
	if event == "connection_state":
		return "network"
	if event == "reply_received":
		return "message"
	return "app"

func _read_archive(id: String) -> Dictionary:
	var result := {"entries":[], "complete":true}
	if _id_pattern.search(id) == null or not FileAccess.file_exists(_path(id,".jsonl")):
		result.complete = false
		return result
	var file := FileAccess.open(_path(id,".jsonl"), FileAccess.READ)
	if file == null:
		result.complete = false
		return result
	while file.get_position() < file.get_length():
		var value: Variant = JSON.parse_string(file.get_line())
		if not value is Dictionary or not value.get("event") is String or _token.search(value.event) == null or not value.get("time") is String or not value.get("level") in ["INFO","WARN","ERROR"] or not value.get("module") in MODULES:
			result.complete = false
			continue
		var safe := {"event":value.event,"time":value.time.left(32),"level":value.level,"module":value.module,"message":EXPLANATIONS.get(value.event,"客户端活动")}
		for key in METRICS + ["elapsed_ms"]:
			if value.get(key) is bool or value.get(key) is int or value.get(key) is float:
				safe[key] = value[key]
		for key in ["code","phase","reply_id"]:
			if value.get(key) is String and _token.search(value[key]) != null:
				safe[key] = value[key] if key == "reply_id" else _safe_code(key, value[key])
		result.entries.append(safe)
	file.close()
	return result

func _safe_code(key: String, value: String) -> String:
	return value if value in (CODES if key == "code" else PHASES).split(" ") else "UNKNOWN"
