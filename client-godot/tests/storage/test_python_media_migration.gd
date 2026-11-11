extends SceneTree
## Python 媒体导入：定位口径、语音/图片原子写入、幂等、换源与账号比对。

const Locator = preload("res://src/storage/python_client_locator.gd")
const Import = preload("res://src/storage/audio_import.gd")
const ImageImport = preload("res://src/storage/image_import.gd")
const Wav = preload("res://src/storage/wav_metadata.gd")
const Cache = preload("res://src/storage/audio_cache.gd")
const Migration = preload("res://src/storage/python_media_migration.gd")
const Store = preload("res://src/storage/godot_settings_store.gd")
const Samples = preload("res://tests/support/audio_samples.gd")

const UUID_A := "11111111-2222-4333-8444-555555555555"
const UUID_B := "66666666-7777-4888-9999-aaaaaaaaaaaa"
const UUID_C := "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"

var failures: Array[String] = []
var _root := ""
var _client := ""
var _audio_sources := ""
var _image_sources := ""
var _audio_cache: RefCounted
var _audio_dir := ""
var _image_dir := ""
var _migration: Node
var _landed: Dictionary = {"audio":[], "image":[]}


func _initialize() -> void:
	run.call_deferred()


func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)


func run() -> void:
	_root = "user://python-media-%d" % Time.get_ticks_usec()
	_client = _root.path_join("python")
	_audio_sources = _client.path_join("temp/tts_output")
	_image_sources = _client.path_join("temp/images")
	_audio_cache = Cache.new(_root.path_join("audio"))
	check(_audio_cache.set_scope("https://migrate.invalid", "alice") == OK, "cache scope created")
	_audio_dir = _audio_cache.get_directory()
	_image_dir = _root.path_join("images")
	_make_client()
	test_locator()
	test_audio_import()
	test_image_import()
	await test_incremental()
	await test_bulk()
	await test_history_image_source()
	test_settings()
	_migration.stop()
	check(_migration.get_state().mode == "idle", "stop returns the migrator to idle")
	_migration.queue_free()
	await process_frame
	remove_folder(_root)
	print("Python media migration: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func _make_client() -> void:
	DirAccess.make_dir_recursive_absolute(_audio_sources)
	DirAccess.make_dir_recursive_absolute(_image_sources)
	var model := _client.path_join("res/live2d/models/luo/model.model3.json")
	DirAccess.make_dir_recursive_absolute(model.get_base_dir())
	_write_text(model, "{}")
	_write_text(_client.path_join("config/config.json"), JSON.stringify({
		"is_debug":false,
		"release_config":{"base_url":"https://client.invalid"},
		"live2d":{"model":{"model_path":"res/live2d/models/luo/model.model3.json"}},
	}))
	_write_text(_client.path_join("temp/user.json"), JSON.stringify({
		"username":"alice", "auto_login":true, "server_url":"https://client.invalid",
	}))


func test_locator() -> void:
	var result := Locator.inspect(_client.path_join("Chat with Luotianyi.exe"))
	check(result.ok and result.root == _client, "exe path resolves to its directory")
	check(result.has_audio and result.has_images, "cache subdirectories detected")
	check(result.account.username == "alice", "account username read without decrypting")
	check(not Locator.inspect(_root.path_join("missing")).ok, "missing directory rejected")
	var other := _root.path_join("other")
	DirAccess.make_dir_recursive_absolute(other)
	_write_text(other.path_join("logs/AgentLuo.log"), "x")
	check(not Locator.inspect(other).ok, "logs-only directory rejected")
	check(Locator.is_uuid(UUID_A) and not Locator.is_uuid("not-a-uuid"), "uuid filter is strict")


func test_audio_import() -> void:
	var bytes := Samples.tone(0.05)
	check(Wav.describe(bytes).ok, "valid wav header accepted")
	var path := _write_audio(UUID_A)
	var first: Dictionary = Import.import_file(_audio_dir, UUID_A, path)
	check(first.status == "imported", "first audio import lands")
	var entry: Dictionary = _audio_cache.lookup(UUID_A)
	check(not entry.is_empty() and is_equal_approx(float(entry.duration), 0.05), "imported audio is visible")
	var second: Dictionary = Import.import_file(_audio_dir, UUID_A, path)
	check(second.status == "skipped" and second.code == "ALREADY_CACHED", "audio re-import never overwrites")
	var broken := _root.path_join("broken.wav")
	_write_bytes(broken, bytes.slice(0, 200))
	check(Import.import_file(_audio_dir, UUID_B, broken).code == "TRUNCATED_AUDIO", "truncated audio rejected")
	check(Import.import_file(_audio_dir, "not-a-uuid", path).code == "INVALID_INPUT", "non-uuid audio rejected")


func test_image_import() -> void:
	var path := _write_png(UUID_A)
	var target := _image_dir.path_join(UUID_A.sha256_text() + ".image")
	var first: Dictionary = ImageImport.import_file(_image_dir, UUID_A, path)
	check(first.status == "imported" and FileAccess.file_exists(target), "image import lands as account cache")
	check(not FileAccess.file_exists(target + ".import.tmp"), "image import leaves no temporary file")
	var second: Dictionary = ImageImport.import_file(_image_dir, UUID_A, path)
	check(second.status == "skipped" and second.code == "ALREADY_CACHED", "image re-import never overwrites")
	var gif := _image_sources.path_join(UUID_B + ".gif")
	_write_bytes(gif, "GIF89a-not-an-image-but-long-enough".to_utf8_buffer())
	var unsupported: Dictionary = ImageImport.import_file(_image_dir, UUID_B, gif)
	check(unsupported.status == "failed" and unsupported.code == "UNSUPPORTED_IMAGE", "unsupported image rejected")


func test_incremental() -> void:
	_migration = Migration.new()
	root.add_child(_migration)
	_migration.bind(func() -> String: return _audio_dir, func() -> String: return _image_dir)
	_migration.set_scope_provider(func() -> Dictionary: return {"username":"alice", "server":"https://client.invalid"})
	_migration.imported.connect(func(kind: String, ids: Array): _landed[kind].append_array(ids))
	var scan: Dictionary = _migration.set_target(_client)
	check(scan.ok and not _migration.get_state().mismatch, "same account is not flagged")
	var path := _write_audio(UUID_B)
	_migration.request_ids([UUID_B])
	var landed := await _wait_for(func() -> bool: return not _landed.audio.is_empty(), 120)
	check(landed, "incremental import touches only the requested page")
	check(_landed.audio.has(UUID_B) and not _audio_cache.lookup(UUID_B).is_empty(), "incremental audio readable")
	check(FileAccess.file_exists(path), "source file is kept")
	_migration.request_ids([UUID_B])
	await process_frame
	check(_landed.audio.size() == 1, "same id is never queued twice")


func test_bulk() -> void:
	_write_audio(UUID_C)
	_write_png(UUID_C)
	_migration.request_import()
	var finished := await _wait_for(func() -> bool: return _migration.get_state().mode == "done", 240)
	check(finished, "bulk import finishes")
	var state: Dictionary = _migration.get_state()
	check(not state.busy, "bulk import clears its busy flag")
	check(int(state.audio_total) >= 2 and int(state.image_total) >= 1, "bulk import counts both kinds")
	check(int(state.failed) == 0, "bulk import reports no failures for valid sources")
	var marker: Dictionary = Import.read_marker(_audio_dir)
	check(not marker.is_empty() and not str(marker.get("source_hash", "")).is_empty(), "bulk marker records the source")
	_landed.audio.clear()
	_migration.request_ids([UUID_B])
	await process_frame
	check(_landed.audio.is_empty() and not _migration.is_busy(), "incremental stops scanning once bulk completed")
	# 换源后旧标记失效：同一文件在新目录里仍可被按需处理。
	var second := _root.path_join("python2")
	_make_second_client(second)
	check(_migration.set_target(second).ok, "second client accepted")
	check(_migration.get_state().mismatch, "different account is flagged")
	_migration.request_ids([UUID_B])
	await process_frame
	check(_migration.get_state().mode != "bulk", "source change resets bulk state")


func test_history_image_source() -> void:
	var images = load("res://src/storage/history_images.gd").new(_root.path_join("history-images"))
	root.add_child(images)
	images.start({"server":"https://client.invalid", "username":"alice", "message_token":"token"})
	images.set_local_source(func() -> String: return _image_sources)
	images.ensure(UUID_A)
	var ready := await _wait_for(func() -> bool: return images.get_state(UUID_A).status == "ready", 60)
	check(ready, "selected python image is used before network")
	if ready:
		check(FileAccess.file_exists(images.get_directory().path_join(UUID_A.sha256_text() + ".image")), "on-demand image copies into account cache")
	var bulk_path := _write_png(UUID_C)
	check(ImageImport.import_file(images.get_directory(), UUID_C, bulk_path).status == "imported", "bulk image written to account cache")
	images.refresh([UUID_C])
	var refreshed := await _wait_for(func() -> bool: return images.get_state(UUID_C).status == "ready", 60)
	check(refreshed, "refresh makes a bulk-imported image visible")
	images.queue_free()
	await process_frame


func test_settings() -> void:
	var store = Store.new(_root.path_join("settings.cfg"))
	check(store.load_settings() != OK, "settings start empty")
	var migration = Migration.new()
	root.add_child(migration)
	migration.set_settings(store)
	check(migration.set_target(_client).ok, "target saved through settings")
	var reloaded = Store.new(_root.path_join("settings.cfg"))
	check(reloaded.load_settings() == OK, "settings file written")
	check(str(reloaded.get_value("migration", "python_client_path", "")) == _client, "selected path persisted")
	var restored = Migration.new()
	root.add_child(restored)
	restored.set_settings(reloaded)
	var restored_scan: Dictionary = restored.scan()
	check(restored_scan.ok and restored.get_images_directory() == _image_sources, "saved path is revalidated when the page opens")
	restored.queue_free()
	migration.queue_free()
	await process_frame


func _make_second_client(root_path: String) -> void:
	var previous := _client
	_client = root_path
	_audio_sources = _client.path_join("temp/tts_output")
	_image_sources = _client.path_join("temp/images")
	_make_client()
	_write_text(_client.path_join("temp/user.json"), JSON.stringify({
		"username":"bob", "auto_login":false, "server_url":"https://other.invalid",
	}))
	_write_audio(UUID_B)
	_client = previous
	_audio_sources = _client.path_join("temp/tts_output")
	_image_sources = _client.path_join("temp/images")


func _wait_for(predicate: Callable, frames: int) -> bool:
	for _index in frames:
		if predicate.call():
			return true
		await process_frame
	return predicate.call()


func _write_audio(id: String) -> String:
	var path := _audio_sources.path_join(id + ".wav")
	_write_bytes(path, Samples.tone(0.05))
	return path


func _write_png(id: String) -> String:
	var path := _image_sources.path_join(id + ".png")
	var image := Image.create(2, 2, false, Image.FORMAT_RGBA8)
	image.fill(Color(1, 0, 0, 1))
	_write_bytes(path, image.save_png_to_buffer())
	return path


func _write_text(path: String, text: String) -> void:
	DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	var file := FileAccess.open(path, FileAccess.WRITE)
	file.store_string(text)
	file.close()


func _write_bytes(path: String, bytes: PackedByteArray) -> void:
	DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	var file := FileAccess.open(path, FileAccess.WRITE)
	file.store_buffer(bytes)
	file.close()


func remove_folder(path: String) -> void:
	for folder in DirAccess.get_directories_at(path):
		remove_folder(path.path_join(folder))
	for file in DirAccess.get_files_at(path):
		DirAccess.remove_absolute(path.path_join(file))
	DirAccess.remove_absolute(path)
