extends SceneTree
var failures: Array[String] = []
func _initialize() -> void: run.call_deferred()
func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)
func run() -> void:
	var path := "user://audio-settings-%s" % Time.get_ticks_usec()
	var cache = load("res://src/storage/audio_cache.gd").new(path)
	var audio = load("res://src/media/reply_audio.gd").new(null, Callable(), cache)
	var session = load("res://src/session/chat_session.gd").new(load("res://src/network/websocket_transport.gd").new(), null, audio)
	root.add_child(session)
	audio.set_scope("http://audio-settings.test", "alice")
	audio.append_reply_audio("cached", Marshalls.raw_to_base64(load("res://tests/support/audio_samples.gd").tone(0.1)), true)
	audio.append_reply_audio("old", Marshalls.raw_to_base64(load("res://tests/support/audio_samples.gd").tone(0.1)), true)
	var meta_path: String = cache.lookup("old").path.get_basename() + ".json"
	var meta: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(meta_path))
	meta.saved_at_unix = int(Time.get_unix_time_from_system()) - 40 * 86400
	var file := FileAccess.open(meta_path, FileAccess.WRITE)
	file.store_string(JSON.stringify(meta))
	file.close()
	var window = load("res://scenes/ui/settings_window.tscn").instantiate()
	check(window.get_node_or_null("%AudioTab") is Button, "settings includes voice cache management")
	check(window.get_node("%AudioPage").get_node_or_null("%OlderThanDays") is SpinBox, "user can choose cache age in days")
	if failures.is_empty():
		window.setup(null, null, null, session.clear_cache)
		root.add_child(window)
		window.open()
		window.get_node("%AudioTab").pressed.emit()
		var page = window.get_node("%AudioPage")
		check(page.visible and not window.is_dirty(), "cache page is independent of unsaved preferences")
		page.get_node("%ClearCache").pressed.emit()
		await create_timer(0.3).timeout
		var dialog: Window = page.get_node("%ClearDialog")
		if DisplayServer.get_name() != "headless":
			check(Rect2i(Vector2i.ZERO, window.size).encloses(Rect2i(dialog.position, dialog.size)), "confirmation fits inside owner")
			check(Rect2(Vector2.ZERO, Vector2(dialog.size)).encloses(dialog.get_cancel_button().get_global_rect()), "cancel button remains reachable")
			await RenderingServer.frame_post_draw
			window.get_texture().get_image().save_png("res://artifacts/audio-settings-confirm.png")
		dialog.get_cancel_button().pressed.emit()
		check(audio.get_message_audio("cached").available and not dialog.visible, "cancel preserves cache")
		page.get_node("%ClearCache").pressed.emit()
		check(dialog.dialog_text.contains("30"), "confirmation states the chosen day limit")
		page.get_node("%OlderThanDays").value = 0
		dialog.get_ok_button().pressed.emit()
		await create_timer(0.1).timeout
		check(not audio.get_message_audio("old").available and audio.get_message_audio("cached").available, "confirmation uses its frozen age and preserves recent cache")
		page.get_node("%ClearCache").pressed.emit()
		dialog.get_ok_button().pressed.emit()
		await create_timer(0.1).timeout
		check(not audio.get_message_audio("cached").available, "confirm clears the current scope through real audio cache")
		check(page.get_node("%CacheStatus").text.contains("已清理"), "page reports successful clear")
		window.queue_free()
	else: window.free()
	session.queue_free()
	await process_frame
	remove_folder(path)
	print("Audio settings: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
func remove_folder(path: String) -> void:
	for folder in DirAccess.get_directories_at(path): remove_folder(path.path_join(folder))
	for file in DirAccess.get_files_at(path): DirAccess.remove_absolute(path.path_join(file))
	DirAccess.remove_absolute(path)
