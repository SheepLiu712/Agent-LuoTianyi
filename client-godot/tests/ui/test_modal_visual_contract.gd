extends SceneTree

const Style = preload("res://src/application/ui_style.gd")
const Store = preload("res://src/storage/godot_settings_store.gd")
const ARTIFACTS := "res://artifacts/visual-unified"
var failures: Array[String] = []


func _initialize() -> void:
	run.call_deferred()


func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)


func run() -> void:
	DirAccess.make_dir_recursive_absolute(ARTIFACTS)
	var style_path := "user://modal-visual-%s.cfg" % Time.get_ticks_usec()
	var style = Style.new()
	style.configure(Store.new(style_path))
	root.gui_embed_subwindows = true
	for mode in ["flat", "crystal"]:
		style.save_preferences(mode, "svg")
		for size in [Vector2i(880, 760), Vector2i(720, 640), Vector2i(480, 690)]:
			root.size = size
			await process_frame
			await _check_decision(mode, size)
		for size in [Vector2i(880, 760), Vector2i(720, 640), Vector2i(480, 690)]:
			await _check_error(mode, size)
	style.save_preferences("flat", "svg")
	DirAccess.remove_absolute(style_path)
	print("Modal visual contract: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func _check_decision(mode: String, host_size: Vector2i) -> void:
	var dialog = load("res://scenes/ui/components/decision_dialog.tscn").instantiate()
	dialog.title = "退出登录前请确认"
	dialog.dialog_text = "将结束本机登录。聊天记录和已保存的设置不会删除；未提交的内容不会自动保存。"
	dialog.ok_button_text = "放弃并继续"
	dialog.cancel_button_text = "返回继续编辑"
	dialog.destructive_action = true
	root.add_child(dialog)
	dialog.popup_centered()
	await create_timer(.1).timeout
	check(dialog.visible, "decision visible: " + mode + "/" + str(host_size.x))
	check(not dialog.has_node("%CloseDecision"), "decision has no duplicate X: " + mode + "/" + str(host_size.x))
	check(dialog.size.x >= 360 and dialog.size.x <= host_size.x - 64 + 1, "decision width respects host and safe margins: " + mode + "/" + str(host_size.x))
	check(Rect2i(Vector2i.ZERO, host_size).encloses(Rect2i(dialog.position, dialog.size)), "decision fits host: " + mode + "/" + str(host_size.x))
	check(dialog.get_cancel_button().get_theme_type_variation() == &"SettingsPrimaryButton", "safe decision action is primary")
	check(dialog.get_ok_button().get_theme_type_variation() == &"SettingsDangerButton", "destructive decision action is outlined danger")
	_check_decision_surface(dialog, mode)
	if DisplayServer.get_name() != "headless":
		await RenderingServer.frame_post_draw
		var shot: Image = dialog.get_texture().get_image()
		check(shot.get_pixel(0, 0).a < 0.05 and shot.get_pixel(shot.get_width() - 1, shot.get_height() - 1).a < 0.05, "decision corners stay transparent")
		shot.save_png(ARTIFACTS.path_join("decision-%s-%s.png" % [mode, host_size.x]))
	dialog.get_cancel_button().pressed.emit()
	check(not dialog.visible, "decision cancel closes: " + mode + "/" + str(host_size.x))
	dialog.queue_free()
	await process_frame


func _check_decision_surface(dialog: Window, mode: String) -> void:
	var surface := dialog.get_node("%Panel").get_theme_stylebox("panel") as StyleBoxFlat
	check(surface != null and surface.corner_radius_top_left == (12 if mode == "crystal" else 8), "decision radius follows appearance mode")
	check(surface != null and surface.shadow_size > 0, "decision always keeps elevation")
	check(surface != null and surface.border_width_left == 0 and surface.border_width_top == 0 and surface.border_width_right == 0 and surface.border_width_bottom == 0, "decision has no outer border")
	check(dialog.size.x - dialog.get_node("%Panel").size.x >= 40, "decision leaves a transparent gutter for its shadow")


func _check_error(mode: String, host_size: Vector2i) -> void:
	root.size = host_size
	await process_frame
	var dialog = load("res://scenes/ui/components/error_dialog.tscn").instantiate()
	root.add_child(dialog)
	dialog.show_error("本次操作未完成，请稍后重试。", "提示")
	await create_timer(.1).timeout
	check(dialog.visible, "error visible: " + mode)
	check(not dialog.has_node("%ErrorClose"), "error has no duplicate X")
	check(dialog.get_node("%ErrorConfirm").text == "确认", "error keeps one explicit close action")
	check(dialog.get_node("%ErrorConfirm").get_theme_type_variation() == &"SettingsPrimaryButton", "error confirm uses settings primary")
	check(dialog.size.x >= 360 and dialog.size.x <= host_size.x - 64 + 1, "error width respects host and safe margins")
	var surface := dialog.get_node("%Panel").get_theme_stylebox("panel") as StyleBoxFlat
	check(surface != null and surface.shadow_size > 0, "error always keeps elevation")
	check(surface != null and surface.border_width_left == 0 and surface.border_width_top == 0 and surface.border_width_right == 0 and surface.border_width_bottom == 0, "error has no outer border")
	if DisplayServer.get_name() != "headless":
		await RenderingServer.frame_post_draw
		dialog.get_texture().get_image().save_png(ARTIFACTS.path_join("error-%s-%s.png" % [mode, host_size.x]))
	dialog.get_node("%ErrorConfirm").pressed.emit()
	check(not dialog.visible, "error confirm closes")
	dialog.queue_free()
	await process_frame
