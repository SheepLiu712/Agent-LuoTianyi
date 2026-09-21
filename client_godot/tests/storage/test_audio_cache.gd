extends SceneTree
const Cache = preload("res://src/storage/audio_cache.gd")
const Samples = preload("res://tests/support/audio_samples.gd")
var failures: Array[String] = []
func check(value: bool, description: String) -> void:
	if not value:
		failures.append(description)
		print("FAIL: ",description)

func _initialize() -> void:
	test_persistence()
	test_retention()
	print("Audio cache: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func test_persistence() -> void:
	var root := "user://cache-test-%s" % Time.get_ticks_usec()
	DirAccess.make_dir_recursive_absolute(root)
	var cache := Cache.new(root)
	check(cache.set_scope("https://TEST.invalid:443/", "A") == OK, "valid scope created")
	var bytes := Samples.tone(.08)
	var decoder = ClassDB.instantiate("PcmStreamDecoder")
	decoder.append(bytes)
	var status: Dictionary = decoder.finish()
	var waveform := PackedFloat32Array()
	waveform.resize(24)
	waveform.fill(.2)
	check(cache.begin("one") == OK, "cache begins")
	check(cache.append("one",bytes.slice(0,17)) == OK and cache.append("one",bytes.slice(17)) == OK, "cache stores split stream")
	check(cache.lookup("one").is_empty(), "partial stream invisible")
	check(cache.commit("one",status,waveform) == OK, "validated stream committed")
	var restored := Cache.new(root)
	restored.set_scope("https://test.invalid", "A")
	var entry := restored.lookup("one")
	check(not entry.is_empty(), "cache persists across instances and normalized server")
	if not entry.is_empty():
		check(FileAccess.get_file_as_bytes(entry.path) == bytes, "original bytes preserved")
		check(is_equal_approx(entry.duration,.08) and entry.waveform.size() == 24, "duration and waveform restored")
	check(restored.begin("one") == ERR_ALREADY_EXISTS, "complete file never overwritten")
	cache.begin("partial")
	cache.append("partial",bytes)
	cache.abort_all()
	check(cache.lookup("partial").is_empty(), "aborted stream not published")
	cache.begin("invalid")
	cache.append("invalid",bytes)
	var broken := status.duplicate()
	broken.finished = false
	check(cache.commit("invalid",broken,waveform) != OK and cache.lookup("invalid").is_empty(), "unfinished decoder cannot commit")
	cache.begin("truthy")
	cache.append("truthy",bytes)
	broken = status.duplicate()
	broken.finished = "false"
	check(cache.commit("truthy",broken,waveform) != OK and cache.lookup("truthy").is_empty(), "nonboolean finished state rejected")
	restored.set_scope("https://test.invalid", "B")
	check(restored.lookup("one").is_empty(), "account isolation")
	restored.begin("one")
	restored.append("one",bytes)
	restored.commit("one",status,waveform)
	check(cache.clear() == OK and cache.lookup("one").is_empty() and not restored.lookup("one").is_empty(), "manual clear only current account")
	restored.set_scope("https://other.invalid", "B")
	check(restored.lookup("one").is_empty(), "server isolation")
	restored.set_scope("https://test.invalid", "B")
	entry = restored.lookup("one")
	if not entry.is_empty():
		var file := FileAccess.open(entry.path,FileAccess.WRITE)
		file.store_8(0)
		file.close()
		check(restored.lookup("one").is_empty(), "truncated cache not exposed")
	var obstacle := root + "/obstacle"
	if DirAccess.dir_exists_absolute(root):
		var file := FileAccess.open(obstacle,FileAccess.WRITE)
		file.close()
		var unwritable := Cache.new(obstacle + "/child")
		check(unwritable.set_scope("https://test.invalid","A") != OK and unwritable.begin("x") != OK, "unwritable scope reports failure")
		DirAccess.remove_absolute(obstacle)
	restored.clear()
	var scope := root.path_join(JSON.stringify(["https://test.invalid","A"]).sha256_text())
	var stale := scope.path_join("locked".sha256_text() + ".part")
	var locked := FileAccess.open(stale,FileAccess.WRITE)
	locked.store_8(0)
	locked.close()
	FileAccess.set_read_only_attribute(stale,true)
	var stale_cache := Cache.new(root)
	check(stale_cache.set_scope("https://test.invalid","A") != OK, "failed stale-file cleanup is reported")
	FileAccess.set_read_only_attribute(stale,false)
	DirAccess.remove_absolute(stale)
	cache.abort_all()
	# Test owns this temporary root; remove only files/directories it generated.
	for folder in DirAccess.get_directories_at(root):
		for file in DirAccess.get_files_at(root.path_join(folder)):
			DirAccess.remove_absolute(root.path_join(folder).path_join(file))
		DirAccess.remove_absolute(root.path_join(folder))
	DirAccess.remove_absolute(root)

func test_retention() -> void:
	var path := "user://cache-age-%s" % Time.get_ticks_usec()
	var clock: Array[int] = [int(Time.get_unix_time_from_system()) + 60 * 86400]
	var cache = Cache.new(path, null, func(): return clock[0])
	cache.set_scope("https://cache-age.test", "alice")
	var bytes: PackedByteArray = Samples.tone(0.1)
	var decoder = ClassDB.instantiate("PcmStreamDecoder")
	decoder.append(bytes)
	var status: Dictionary = decoder.finish()
	var wave: PackedFloat32Array = decoder.get_waveform(24)
	for id in ["old", "recent", "legacy", "boundary", "locked"]:
		cache.begin(id)
		cache.append(id, bytes)
		cache.commit(id,status,wave)
	var old: Dictionary = cache.lookup("old")
	var meta_path: String = old.path.get_basename() + ".json"
	var meta: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(meta_path))
	meta.saved_at_unix = clock[0] - 40 * 86400
	write_json(meta_path, meta)
	meta_path = cache.lookup("boundary").path.get_basename() + ".json"
	meta = JSON.parse_string(FileAccess.get_file_as_string(meta_path))
	meta.saved_at_unix = clock[0] - 30 * 86400
	write_json(meta_path, meta)
	var locked_path: String = cache.lookup("locked").path
	meta_path = locked_path.get_basename() + ".json"
	meta = JSON.parse_string(FileAccess.get_file_as_string(meta_path))
	meta.saved_at_unix = clock[0] - 40 * 86400
	write_json(meta_path, meta)
	FileAccess.set_read_only_attribute(locked_path, true)
	meta_path = cache.lookup("legacy").path.get_basename() + ".json"
	meta = JSON.parse_string(FileAccess.get_file_as_string(meta_path))
	meta.erase("saved_at_unix")
	write_json(meta_path, meta)
	var other = Cache.new(path)
	other.set_scope("https://cache-age.test", "bob")
	other.begin("other")
	other.append("other",bytes)
	other.commit("other",status,wave)
	cache.begin("receiving")
	cache.append("receiving",bytes)
	check(cache.clear(-1) == ERR_INVALID_PARAMETER and not cache.lookup("old").is_empty(), "negative days cannot delete cache")
	check(cache.clear(30) != OK and not cache.lookup("locked").is_empty(), "partial deletion failure preserves the locked entry and reports error")
	FileAccess.set_read_only_attribute(locked_path, false)
	check(cache.clear(30) == OK and cache.lookup("locked").is_empty(), "retry clears only remaining eligible entries")
	check(cache.lookup("old").is_empty() and cache.lookup("legacy").is_empty(), "old metadata and legacy modified-time entries are cleared")
	check(not cache.lookup("recent").is_empty() and not cache.lookup("boundary").is_empty() and not other.lookup("other").is_empty(), "recent, exact-boundary and other account entries are kept")
	check(cache.commit("receiving",status,wave) == OK, "selective clear preserves an active receiving stream")
	check(cache.clear(0) == OK and cache.lookup("recent").is_empty(), "zero days explicitly clears all current account cache")
	other.clear()
	remove_folder(path)

func write_json(path: String, value: Dictionary) -> void:
	var file := FileAccess.open(path,FileAccess.WRITE)
	file.store_string(JSON.stringify(value))
	file.close()
func remove_folder(path: String) -> void:
	for folder in DirAccess.get_directories_at(path): remove_folder(path.path_join(folder))
	for file in DirAccess.get_files_at(path): DirAccess.remove_absolute(path.path_join(file))
	DirAccess.remove_absolute(path)
