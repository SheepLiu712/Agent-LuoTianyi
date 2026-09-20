extends SceneTree
var failures: Array[String] = []
func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ",label)
func _initialize() -> void:
	var script = load("res://src/storage/audio_cache.gd")
	var arguments: int = 0
	for method in script.get_script_method_list():
		if method.name == "clear": arguments = method.args.size()
	check(arguments == 1, "cache clear accepts a retention day count")
	if failures.is_empty():
		var path := "user://cache-age-%s" % Time.get_ticks_usec()
		var clock: Array[int] = [int(Time.get_unix_time_from_system()) + 60 * 86400]
		var cache = script.new(path, null, func(): return clock[0])
		cache.set_scope("https://cache-age.test", "alice")
		var bytes: PackedByteArray = load("res://tests/support/audio_samples.gd").tone(0.1)
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
		var other = script.new(path)
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
	print("Cache retention: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
func write_json(path: String, value: Dictionary) -> void:
	var file := FileAccess.open(path,FileAccess.WRITE)
	file.store_string(JSON.stringify(value))
	file.close()
func remove_folder(path: String) -> void:
	for folder in DirAccess.get_directories_at(path): remove_folder(path.path_join(folder))
	for file in DirAccess.get_files_at(path): DirAccess.remove_absolute(path.path_join(file))
	DirAccess.remove_absolute(path)
