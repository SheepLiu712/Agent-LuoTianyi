extends SceneTree
var failures: Array[String] = []
func _initialize() -> void: run.call_deferred()
func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)


func _check_contract(page: Control) -> void:
	check(page.get_node_or_null("%OlderThanDays") is SpinBox, "user can choose cache age in days")
	check(page.get_node_or_null("%MigrateMedia") is Button, "cache page owns a media import entry")
	check(page.get_node_or_null("%BrowsePython") is Button, "cache page can pick a python client")
	check(page.get_node_or_null("%PythonPath") is LineEdit, "cache page shows the selected python client")
	check(page.get_node_or_null("%PythonPicker") is FileDialog, "cache page owns an exe picker")
	check(page.get_node_or_null("%StorageCard") is PanelContainer, "cache page starts with the storage card")
	check(page.get_node_or_null("%ImportCard") is PanelContainer, "cache page owns an import card")
	check(page.get_node_or_null("%CleanupCard") is PanelContainer, "cache page owns a cleanup card")
	var column: VBoxContainer = page.get_node("Column")
	check(column.get_node("StorageCard").get_index() < column.get_node("ImportCard").get_index() and column.get_node("ImportCard").get_index() < column.get_node("CleanupCard").get_index(), "cards follow storage, import, cleanup order")
	for removed in ["MigrationHint", "Scope", "AgeHint", "Hint"]:
		check(page.find_child(removed, true, false) == null, "redundant copy node removed: " + removed)
	check(page.get_node("%MigrateMedia").text == "导入媒体…", "import action names its result")
	check(page.get_node("%RefreshUsage").text == "刷新容量", "storage refresh is not confused with client scanning")
	check(page.get_node("%ClearCache").text == "清理语音…", "cleanup action stays scoped to voice")


func _exercise_cache(window: Window, page: Control, audio: Variant) -> void:
	page.get_node("%ClearCache").pressed.emit()
	await create_timer(0.3).timeout
	var dialog: Window = page.get_node("%ClearDialog")
	await _check_dialog_fit(window, dialog)
	var first_height: int = dialog.size.y
	dialog.get_cancel_button().pressed.emit()
	check(audio.get_message_audio("cached").available and not dialog.visible, "cancel preserves cache")
	page.get_node("%ClearCache").pressed.emit()
	await create_timer(0.3).timeout
	check(dialog.size.y == first_height, "cancel and reopen keeps the confirmation height")
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


func _check_dialog_fit(window: Window, dialog: Window) -> void:
	if DisplayServer.get_name() == "headless":
		return
	check(Rect2i(Vector2i.ZERO, window.size).encloses(Rect2i(dialog.position, dialog.size)), "confirmation fits inside owner")
	check(Rect2(Vector2.ZERO, Vector2(dialog.size)).encloses(dialog.get_cancel_button().get_global_rect()), "cancel button remains reachable")
	await RenderingServer.frame_post_draw
	window.get_texture().get_image().save_png("res://artifacts/audio-settings-confirm.png")


func run() -> void:
	var path := "user://audio-settings-%s" % Time.get_ticks_usec()
	var cache = load("res://src/storage/audio_cache.gd").new(path)
	var audio = load("res://tests/support/native_reply_audio.gd").new(null, Callable(), cache)
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
	var window = load("res://scenes/ui/windows/settings_window.tscn").instantiate()
	check(window.get_node_or_null("%AudioTab") is Button, "settings includes voice cache management")
	var page = window.get_node("%AudioPage")
	_check_contract(page)
	if failures.is_empty():
		window.setup(null, null, null, session.clear_cache)
		root.add_child(window)
		window.open()
		window.get_node("%AudioTab").pressed.emit()
		check(page.visible and not window.is_dirty(), "cache page is independent of unsaved preferences")
		check(page.get_node("%MigrateMedia").disabled, "media import entry stays disabled until a service is wired")
		check(page.get_node("%BrowsePython").disabled, "python picker stays disabled until a service is wired")
		check(page.get_node("%PythonPicker").file_mode == FileDialog.FILE_MODE_OPEN_FILE, "picker selects one executable")
		check(page.get_node("%PythonPicker").filters.size() == 1 and page.get_node("%PythonPicker").filters[0].contains("*.exe"), "picker filters executables")
		check(page.get_node("%MigrationStatus").text.contains("暂不可用"), "status explains a missing import service")
		await _exercise_cache(window, page, audio)
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
