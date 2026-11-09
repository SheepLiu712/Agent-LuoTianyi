extends SceneTree
## 语音兜底迁移：解析口径、原子写入、幂等、两种入口的切换。

const Import = preload("res://src/storage/audio_import.gd")
const Wav = preload("res://src/storage/wav_metadata.gd")
const Cache = preload("res://src/storage/audio_cache.gd")
const Migration = preload("res://src/storage/audio_migration.gd")
const Samples = preload("res://tests/support/audio_samples.gd")

const UUID_A := "11111111-2222-4333-8444-555555555555"
const UUID_B := "66666666-7777-4888-9999-aaaaaaaaaaaa"
const UUID_C := "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"

var failures: Array[String] = []
var _root := ""
var _sources := ""
var _cache: RefCounted
var _cache_dir := ""
var _migration: Node
var _landed: Array = []


func _initialize() -> void:
	run.call_deferred()


func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)


func run() -> void:
	_root = "user://audio-migration-%d" % Time.get_ticks_usec()
	_sources = _root.path_join("python/temp/tts_output")
	DirAccess.make_dir_recursive_absolute(_sources)
	_cache = Cache.new(_root.path_join("audio"))
	check(_cache.set_scope("https://migrate.invalid", "alice") == OK, "cache scope created")
	_cache_dir = _cache.get_directory()
	test_metadata()
	test_idempotent_import()
	test_rejects()
	await test_incremental()
	await test_bulk()
	_migration.stop()
	check(_migration.get_state().mode == "idle", "stop returns the migrator to idle")
	_migration.queue_free()
	await process_frame
	remove_folder(_root)
	print("Audio migration: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func test_metadata() -> void:
	var bytes := Samples.tone(0.05)
	var metadata: Dictionary = Wav.describe(bytes)
	check(metadata.get("ok", false), "valid wav header accepted")
	check(int(metadata.sample_rate) == 24000 and int(metadata.channels) == 1 and int(metadata.bits) == 16, "format fields parsed")
	check(int(metadata.frames) == 1200 and int(metadata.bytes) == bytes.size(), "frame count derived from data chunk")
	var waveform: PackedFloat32Array = Wav.waveform(bytes, metadata)
	check(waveform.size() == 24, "waveform has 24 buckets")
	var bounded := true
	for value in waveform:
		if value < 0.0 or value > 1.0:
			bounded = false
	check(bounded, "waveform stays within 0..1")
	check(not Wav.describe(bytes.slice(0, 20)).ok, "short buffer rejected")
	check(Wav.describe(PackedByteArray()).get("code", "") == "TRUNCATED_AUDIO", "empty buffer reports truncation")
	var broken := bytes.duplicate()
	broken[0] = 0
	check(not Wav.describe(broken).ok, "non-riff buffer rejected")
	check(not Wav.describe(bytes.slice(0, bytes.size() - 100)).ok, "cut data chunk rejected")


func test_idempotent_import() -> void:
	var path := _write_source(UUID_A)
	var first: Dictionary = Import.import_file(_cache_dir, UUID_A, path)
	check(first.status == "imported", "first import lands")
	var entry: Dictionary = _cache.lookup(UUID_A)
	check(not entry.is_empty(), "imported audio is visible to the player")
	if not entry.is_empty():
		check(is_equal_approx(float(entry.duration), 0.05), "duration matches the source")
		check(FileAccess.get_file_as_bytes(entry.path) == FileAccess.get_file_as_bytes(path), "bytes copied verbatim")
	var second: Dictionary = Import.import_file(_cache_dir, UUID_A, path)
	check(second.status == "skipped" and second.code == "ALREADY_CACHED", "re-import never overwrites")


func test_rejects() -> void:
	var broken := _root.path_join("broken.wav")
	var file := FileAccess.open(broken, FileAccess.WRITE)
	file.store_buffer(Samples.tone(0.05).slice(0, 200))
	file.close()
	var truncated: Dictionary = Import.import_file(_cache_dir, UUID_B, broken)
	check(truncated.status == "failed" and truncated.code == "TRUNCATED_AUDIO", "truncated source rejected")
	check(_cache.lookup(UUID_B).is_empty(), "rejected source leaves no cache entry")
	var missing: Dictionary = Import.import_file(_cache_dir, UUID_B, _root.path_join("nope.wav"))
	check(missing.status == "failed" and missing.code == "SOURCE_UNREADABLE", "missing source rejected")
	check(Import.import_file(_cache_dir, "not-a-uuid", broken).code == "INVALID_INPUT", "non-uuid name rejected")
	check(not Import.is_uuid("") and Import.is_uuid(UUID_A), "uuid filter is strict")


func test_incremental() -> void:
	_migration = Migration.new()
	root.add_child(_migration)
	_migration.bind(func() -> String: return _cache_dir, func() -> Array: return [_sources])
	_migration.imported.connect(func(ids: Array): _landed.append_array(ids))
	var path := _write_source(UUID_B)
	_migration.request_ids([UUID_B])
	var landed := await _wait_for(func() -> bool: return not _landed.is_empty(), 120)
	check(landed, "incremental import touches only the requested page")
	check(_landed.has(UUID_B), "incremental import reports the landed id back")
	check(not _cache.lookup(UUID_B).is_empty(), "incremental cache entry readable")
	check(FileAccess.file_exists(path), "source file is kept")
	_migration.request_ids([UUID_B])
	await process_frame
	check(_landed.size() == 1, "same id is never queued twice")


func test_bulk() -> void:
	_write_source(UUID_C)
	_migration.request_all()
	var finished := await _wait_for(func() -> bool: return _migration.get_state().mode == "done", 240)
	check(finished, "bulk migration finishes")
	var state: Dictionary = _migration.get_state()
	check(not state.busy, "bulk migration clears its busy flag")
	check(int(state.imported) >= 1, "bulk migration imports what incremental had not seen")
	check(int(state.failed) == 0, "bulk migration reports no failures for valid sources")
	check(not Import.read_marker(_cache_dir).is_empty(), "bulk migration records a completion marker")
	var skips := Import.import_file(_cache_dir, UUID_C, _sources.path_join(UUID_C + ".wav"))
	check(skips.status == "skipped", "bulk result is idempotent afterwards")
	# 标记存在时增量不再扫盘：直接请求也应被短路。
	_landed.clear()
	_migration.request_ids([UUID_B])
	await process_frame
	check(_landed.is_empty() and not _migration.is_busy(), "incremental stops scanning once bulk completed")


func _wait_for(predicate: Callable, frames: int) -> bool:
	for _index in frames:
		if predicate.call():
			return true
		await process_frame
	return predicate.call()


func _write_source(id: String) -> String:
	var path := _sources.path_join(id + ".wav")
	var file := FileAccess.open(path, FileAccess.WRITE)
	file.store_buffer(Samples.tone(0.05))
	file.close()
	return path


func remove_folder(path: String) -> void:
	for folder in DirAccess.get_directories_at(path):
		remove_folder(path.path_join(folder))
	for file in DirAccess.get_files_at(path):
		DirAccess.remove_absolute(path.path_join(file))
	DirAccess.remove_absolute(path)
