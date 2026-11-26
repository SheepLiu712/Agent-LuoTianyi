extends SceneTree
var failures: Array[String] = []
func _initialize() -> void: run.call_deferred()
func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)
func run() -> void:
	check(ResourceLoader.exists("res://src/storage/godot_storage_service.gd"), "uniform storage implementation exists")
	check(ClassDB.class_exists("StorageVolume"), "platform capacity adapter exists")
	if failures.is_empty():
		var directory := "user://storage-service-%s" % Time.get_ticks_usec()
		DirAccess.make_dir_recursive_absolute(directory + "/nested")
		var bytes := PackedByteArray()
		bytes.resize(2048)
		var file := FileAccess.open(directory + "/nested/data",FileAccess.WRITE)
		file.store_buffer(bytes)
		file.close()
		var storage = load("res://src/storage/godot_storage_service.gd").new()
		var result: Dictionary = storage.query_directory(directory)
		check(result.directory_bytes == 2048 and result.file_count == 1, "directory measurement uses bytes")
		check(result.total_bytes is int and result.free_bytes is int and result.total_bytes > 0 and result.free_bytes >= 0 and result.free_bytes <= result.total_bytes, "real volume reports 64-bit byte capacities")
		DirAccess.remove_absolute(directory + "/nested/data")
		check(storage.query_directory(directory).directory_bytes == 0, "real empty directory reports zero")
		DirAccess.remove_absolute(directory + "/nested")
		DirAccess.remove_absolute(directory)
		check(storage.query_directory(directory).directory_bytes == -1, "unavailable directory reports minus one")
		var base = load("res://src/storage/storage_service.gd").new()
		var unknown: Dictionary = base.query_directory("unavailable")
		check(unknown.total_bytes == -1 and unknown.directory_bytes == -1, "unavailable implementation never fabricates zero usage")
	print("StorageService: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
