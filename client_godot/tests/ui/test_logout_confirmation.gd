extends SceneTree

var failures: Array[String] = []
const ARTIFACT := "res://artifacts/ui-refinement/settings-logout-confirm.png"

func _initialize() -> void: run.call_deferred()

func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)

func until(predicate: Callable) -> bool:
	var deadline := Time.get_ticks_msec() + 4000
	while not predicate.call() and Time.get_ticks_msec() < deadline: await process_frame
	return predicate.call()

func click(button: Button) -> void:
	if DisplayServer.get_name() == "headless":
		button.pressed.emit()
	else:
		await create_timer(.05).timeout
		var host := button.get_window()
		var point := button.get_global_rect().get_center()
		while host.is_embedded():
			point += Vector2(host.position)
			host = host.get_parent().get_window()
		var motion := InputEventMouseMotion.new()
		motion.position = point
		host.push_input(motion, true)
		var event := InputEventMouseButton.new()
		event.position = point
		event.button_index = MOUSE_BUTTON_LEFT
		event.pressed = true
		host.push_input(event, true)
		event = event.duplicate()
		event.pressed = false
		host.push_input(event, true)
	await process_frame

func inspect_dialog(dialog: Window, host: Window) -> void:
	check(dialog.visible, "exit decision is visible")
	check(dialog.title.contains("退出应用" if host == root else "退出登录"), "decision names the actual exit action")
	check(dialog.dialog_text.contains("尚未提交") and dialog.dialog_text.contains("不会自动保存或发送"), "decision explains draft loss and no automatic submission")
	check(dialog.get_parent().get_window() == host, "exit decision belongs to its triggering window")
	if DisplayServer.get_name() != "headless":
		await create_timer(.1).timeout
		check(dialog.get_cancel_button().has_focus(), "exit decision defaults to cancel")
		check(Rect2(Vector2.ZERO, Vector2(host.size)).encloses(Rect2(Vector2(dialog.position), Vector2(dialog.size))), "decision fits in its host")
		check(Rect2(Vector2.ZERO, Vector2(dialog.size)).encloses(dialog.get_cancel_button().get_global_rect()), "cancel remains reachable")

func run() -> void:
	var path := "user://logout-confirm-%s" % Time.get_ticks_usec()
	DirAccess.make_dir_recursive_absolute(path)
	var security = ClassDB.instantiate("WindowsSecurity")
	var session = load("res://src/session/account_session.gd").new(load("res://src/network/account_api.gd").new(security), load("res://src/storage/godot_storage_service.gd").new(path+"/account.cfg", load("res://src/storage/credential_store.gd").new(security, path+"/tokens")))
	var app = load("res://scenes/main.tscn").instantiate()
	app.setup(session, path+"/window.cfg")
	root.add_child(app)
	app.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	await session.perform("login", OS.get_environment("GODOT_TEST_SERVER"), {"username":"ui", "password":"synthetic", "request_token":false}, false)
	app.find_child("ChatView", true, false).get_node("%Input").text = "retain chat on cancel"
	app.get_node("%NavLogs").pressed.emit()
	var logs = app.find_child("LogWindow", true, false)
	app.get_node("%NavSettings").pressed.emit()
	var settings = app.find_child("SettingsWindow", true, false)
	var field = settings.find_child("CustomContextField", true, false)
	check(await until(func(): return field.editable), "preferences loaded")
	field.text = "retain settings on cancel"
	field.text_changed.emit()
	if DisplayServer.get_name() != "headless":
		settings.grab_focus()
		await create_timer(.1).timeout
	await click(settings.get_node("%LogoutButton"))
	var dialog = app.get_node("%ExitDialog")
	await inspect_dialog(dialog, settings)
	if DisplayServer.get_name() != "headless":
		DirAccess.make_dir_recursive_absolute(ARTIFACT.get_base_dir())
		await RenderingServer.frame_post_draw
		check(settings.get_texture().get_image().save_png(ARTIFACT) == OK, "capture decision in settings")
	await click(dialog.get_cancel_button())
	check(not dialog.visible and settings.is_dirty() and not session.get_session().is_empty(), "cancel keeps account and draft")
	settings.close_requested.emit()
	await click(settings.get_node("%UnsavedDialog").get_ok_button())
	await process_frame
	check(not is_instance_valid(settings) and is_instance_valid(dialog), "closing settings cannot destroy the shared exit decision")
	if not is_instance_valid(dialog):
		app.queue_free()
		await process_frame
		remove_folder(path)
		quit(1)
		return
	root.close_requested.emit()
	await inspect_dialog(dialog, root)
	await click(dialog.get_cancel_button())
	app.get_node("%NavSettings").pressed.emit()
	settings = app.find_child("SettingsWindow", true, false)
	await process_frame
	await click(settings.get_node("%LogoutButton"))
	await inspect_dialog(dialog, settings)
	await click(dialog.get_ok_button())
	await process_frame
	check(session.get_session().is_empty() and logs.visible and is_instance_valid(dialog), "discard logs out, preserves logs and reusable decision")
	await session.perform("login", OS.get_environment("GODOT_TEST_SERVER"), {"username":"fail_save", "password":"synthetic", "request_token":false}, false)
	app.get_node("%NavSettings").pressed.emit()
	settings = app.find_child("SettingsWindow", true, false)
	field = settings.find_child("CustomContextField", true, false)
	check(await until(func(): return field.editable), "second account preferences loaded")
	field.text = "failed save must retain this"
	field.text_changed.emit()
	settings.get_node("%SaveAll").pressed.emit()
	settings.get_node("%LogoutButton").pressed.emit()
	check(not session.get_session().is_empty(), "logout waits for save")
	check(await until(func(): return not settings.is_saving()), "failed save settles")
	await inspect_dialog(dialog, settings)
	await click(dialog.get_cancel_button())
	check(settings.is_dirty() and field.text == "failed save must retain this" and not session.get_session().is_empty(), "failed-save logout cancellation preserves draft and account")
	# A public save request may arrive after the original close snapshot.
	settings.get_node("%LogoutButton").pressed.emit()
	settings.save_changes()
	dialog.get_ok_button().pressed.emit()
	check(not session.get_session().is_empty(), "confirmation rechecks a save started after the close request")
	if session.get_session().is_empty():
		app.queue_free()
		await process_frame
		remove_folder(path)
		print("Logout confirmation: FAIL")
		quit(1)
		return
	check(await until(func(): return not settings.is_saving()), "save after confirmation settles before exit")
	await inspect_dialog(dialog, settings)
	await click(dialog.get_cancel_button())
	check(settings.is_dirty() and not session.get_session().is_empty(), "cancel after invalidated confirmation preserves failed draft")
	app.queue_free()
	await process_frame
	remove_folder(path)
	print("Logout confirmation: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func remove_folder(path: String) -> void:
	for folder in DirAccess.get_directories_at(path): remove_folder(path.path_join(folder))
	for file in DirAccess.get_files_at(path): DirAccess.remove_absolute(path.path_join(file))
	DirAccess.remove_absolute(path)
