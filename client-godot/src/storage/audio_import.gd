extends RefCounted
## 语音导入器：把 Python 客户端留在 `temp/tts_output/<uuid>.wav` 的文件
## 转成当前账号的播放缓存（`<sha256(uuid)>.audio` + `<sha256(uuid)>.json`）。
## 这里只做文件系统操作，不持有队列、不碰网络与界面；
## 线程安全的前提是「同一条目只由一个写者负责」，用 `.part` 的存在性判断避让。
## 一致性约定：
##   - 只写缓存目录，绝不改动消息库；
##   - 成对原子：`.part` → `.audio`，`.json.tmp` → `.json`，缺一半就清理；
##   - 已存在的条目一律不覆盖，导入天然幂等；
##   - 源文件只读，不移动、不删除。

const Wav = preload("res://src/storage/wav_metadata.gd")

const UUID_PATTERN := "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
const AUDIO_EXTENSION := ".audio"
const MANIFEST_EXTENSION := ".json"
const VERSION := 1
const MARKER_DIRECTORY := "migration"

static var _uuid: RegEx


static func is_uuid(value: String) -> bool:
	if _uuid == null:
		_uuid = RegEx.create_from_string(UUID_PATTERN)
	return _uuid.search(value) != null


## Python 端音频目录的候选位置。路径来自客户端自己的工作目录，
## 所以只能按「常见的几种摆放」去猜，猜不到就让页面提示用户。
static func candidates() -> Array[String]:
	var roots: Array[String] = []
	var project := ProjectSettings.globalize_path("res://").trim_suffix("/")
	_append_root(roots, project)
	# 仓库形态下 Python 客户端与 client-godot 平级，所以要往上一级找。
	_append_root(roots, project.get_base_dir())
	_append_root(roots, OS.get_executable_path().get_base_dir())
	var ancestor := OS.get_executable_path().get_base_dir()
	for _index in 3:
		ancestor = ancestor.get_base_dir()
		if ancestor.is_empty():
			break
		_append_root(roots, ancestor)
	var result: Array[String] = []
	for root in roots:
		for relative in ["temp/tts_output", "client/temp/tts_output", "cli-client/temp/tts_output"]:
			var path: String = root.path_join(relative)
			if DirAccess.dir_exists_absolute(path) and not result.has(path):
				result.append(path)
	return result


## 目录里所有「文件名就是 UUID」的 wav：id → 绝对路径。
static func index(directory: String) -> Dictionary:
	var entries: Dictionary = {}
	for name in DirAccess.get_files_at(directory):
		if not name.to_lower().ends_with(".wav"):
			continue
		var id := name.get_basename()
		if not is_uuid(id):
			continue
		entries[id] = directory.path_join(name)
	return entries


static func find(sources: Array, id: String) -> String:
	for source in sources:
		var path: String = str(source).path_join(id + ".wav")
		if FileAccess.file_exists(path):
			return path
	return ""


static func import_file(cache_directory: String, id: String, source: String) -> Dictionary:
	if cache_directory.is_empty() or not is_uuid(id):
		return _result("failed", "INVALID_INPUT")
	var stem: String = cache_directory.path_join(id.sha256_text())
	if FileAccess.file_exists(stem + MANIFEST_EXTENSION):
		return _result("skipped", "ALREADY_CACHED")
	if FileAccess.file_exists(stem + ".part"):
		# 在线播放正在写同一条目：让出，避免两个写者抢同一个临时文件。
		return _result("skipped", "STREAM_ACTIVE")
	var bytes := _read(source)
	if bytes.is_empty():
		return _result("failed", "SOURCE_UNREADABLE")
	var decoded := _decode(bytes)
	if not decoded.ok:
		return _result("failed", str(decoded.code))
	if not _write(stem, bytes, decoded.metadata, decoded.waveform, _saved_at(source)):
		return _result("failed", "CACHE_WRITE_FAILED")
	return _result("imported", "OK")


static func marker_path(cache_directory: String) -> String:
	return cache_directory.get_base_dir().path_join(MARKER_DIRECTORY).path_join(cache_directory.get_file() + ".json")


static func read_marker(cache_directory: String) -> Dictionary:
	var path := marker_path(cache_directory)
	if not FileAccess.file_exists(path):
		return {}
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	return parsed if parsed is Dictionary else {}


static func write_marker(cache_directory: String, counts: Dictionary) -> void:
	var path := marker_path(cache_directory)
	if DirAccess.make_dir_recursive_absolute(path.get_base_dir()) != OK:
		return
	var temporary := path + ".tmp"
	var file := FileAccess.open(temporary, FileAccess.WRITE)
	if file == null:
		return
	file.store_string(JSON.stringify({
		"version": VERSION,
		"completed_at_unix": int(Time.get_unix_time_from_system()),
		"counts": counts,
	}))
	file.flush()
	var error := file.get_error()
	file.close()
	if error != OK or DirAccess.rename_absolute(temporary, path) != OK:
		DirAccess.remove_absolute(temporary)


## 当前账号缓存里已完成的音频条目数；与标记文件一起判断「是否已完成全量迁移」。
static func cached_count(cache_directory: String) -> int:
	var count := 0
	for name in DirAccess.get_files_at(cache_directory):
		if name.ends_with(AUDIO_EXTENSION):
			count += 1
	return count


## 优先用原生解码器：它给出的帧数、格式和波形与在线播放口径完全一致。
## 原生扩展缺席时退回纯解析，保证功能仍可用。
static func _decode(bytes: PackedByteArray) -> Dictionary:
	var header := Wav.describe(bytes)
	if not header.get("ok", false):
		return {"ok": false, "code": str(header.get("code", "INVALID_WAV"))}
	if ClassDB.class_exists("PcmStreamDecoder"):
		var decoder: Object = ClassDB.instantiate("PcmStreamDecoder")
		if decoder != null:
			var appended: Dictionary = decoder.append(bytes)
			if appended.get("ok", false):
				var status: Dictionary = decoder.finish()
				if _playable(status, bytes.size()):
					var waveform: PackedFloat32Array = decoder.get_waveform(Wav.BUCKETS)
					if waveform.size() == Wav.BUCKETS:
						return {"ok": true, "code": "OK", "metadata": {
							"sample_rate": int(status.sample_rate), "channels": int(status.channels),
							"bits": int(status.bits), "frames": int(status.decoded_frames),
							"bytes": int(status.input_bytes), "data_offset": header.data_offset,
							"data_size": header.data_size, "format": header.format,
						}, "waveform": waveform}
			return {"ok": false, "code": "UNPLAYABLE_AUDIO"}
	var waveform := Wav.waveform(bytes, header, Wav.BUCKETS)
	if waveform.size() != Wav.BUCKETS:
		return {"ok": false, "code": "INVALID_WAV"}
	return {"ok": true, "code": "OK", "metadata": header, "waveform": waveform}


static func _playable(status: Dictionary, size: int) -> bool:
	if not status.get("ok", false) or not status.get("finished", false):
		return false
	if int(status.get("input_bytes", 0)) != size:
		return false
	if int(status.get("decoded_frames", 0)) <= 0:
		return false
	var rate := int(status.get("sample_rate", 0))
	return rate >= Wav.MIN_RATE and rate <= Wav.MAX_RATE and int(status.decoded_frames) <= rate * Wav.MAX_SECONDS


## 先写 `.part` 再改名，最后写 manifest；任何一步失败都回收半成品，
## 这样 `AudioCache.lookup()` 要么看到完整一对，要么什么都看不到。
static func _write(stem: String, bytes: PackedByteArray, metadata: Dictionary, waveform: PackedFloat32Array, saved_at: int) -> bool:
	var audio_path := stem + AUDIO_EXTENSION
	var manifest_path := stem + MANIFEST_EXTENSION
	var part_path := stem + ".part"
	var file := FileAccess.open(part_path, FileAccess.WRITE)
	if file == null:
		return false
	file.store_buffer(bytes)
	file.flush()
	var error := file.get_error()
	file.close()
	if error != OK or DirAccess.rename_absolute(part_path, audio_path) != OK:
		_remove([part_path])
		return false
	var manifest := {
		"version": VERSION,
		"sample_rate": int(metadata.sample_rate), "channels": int(metadata.channels),
		"bits": int(metadata.bits), "frames": int(metadata.frames), "bytes": bytes.size(),
		"waveform": Array(waveform), "saved_at_unix": saved_at,
	}
	var temporary := manifest_path + ".tmp"
	var json := FileAccess.open(temporary, FileAccess.WRITE)
	if json == null:
		_remove([audio_path])
		return false
	json.store_string(JSON.stringify(manifest))
	json.flush()
	error = json.get_error()
	json.close()
	if error != OK or DirAccess.rename_absolute(temporary, manifest_path) != OK:
		_remove([audio_path, temporary])
		return false
	return true


static func _read(path: String) -> PackedByteArray:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return PackedByteArray()
	var length := file.get_length()
	if length < Wav.HEADER_BYTES or length > Wav.MAX_BYTES:
		file.close()
		return PackedByteArray()
	var bytes := file.get_buffer(length)
	file.close()
	return bytes


## 保留源文件的修改时间：清理「N 天之前」按真实录制时间生效。
static func _saved_at(source: String) -> int:
	var modified := FileAccess.get_modified_time(source)
	return modified if modified > 0 else int(Time.get_unix_time_from_system())


static func _remove(paths: Array) -> void:
	for path in paths:
		if FileAccess.file_exists(path):
			DirAccess.remove_absolute(path)


static func _append_root(roots: Array[String], value: String) -> void:
	var path := value.trim_suffix("/")
	if path.is_empty() or roots.has(path):
		return
	roots.append(path)


static func _result(status: String, code: String) -> Dictionary:
	return {"status": status, "code": code}
