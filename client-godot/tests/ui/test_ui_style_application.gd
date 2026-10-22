extends SceneTree
## Uses run_feature_tests.py's loopback fixture and isolated user data.
const ARTIFACTS := "res://artifacts/ui-style"
var failures: Array[String] = []

func _initialize() -> void: run.call_deferred()
func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)

func until(predicate: Callable) -> bool:
	var deadline := Time.get_ticks_msec() + 6000
	while not predicate.call() and Time.get_ticks_msec() < deadline: await process_frame
	return predicate.call()

func capture(window: Window, label: String) -> void:
	if DisplayServer.get_name() == "headless": return
	await create_timer(.2).timeout
	await RenderingServer.frame_post_draw
	check(window.get_texture().get_image().save_png(ARTIFACTS.path_join(label + ".png")) == OK, "capture: " + label)

func check_icon(view: Node, name: String, resource: String, emoji: bool) -> void:
	var button: Button = view.get_node("%" + name)
	var suffix := "_emoji.png" if emoji else ".svg"
	check(button.icon != null and button.icon.resource_path.ends_with(resource + suffix), "application icon: " + name)
	check(button.get_theme_constant("icon_max_width") == 20, "fixed icon size: " + name)

func make_app(directory: String) -> Control:
	var security = ClassDB.instantiate("WindowsSecurity")
	var account = load("res://src/session/account_session.gd").new(
		load("res://src/network/account_api.gd").new(security),
		load("res://src/storage/godot_storage_service.gd").new(directory + "/account.cfg",
		load("res://src/storage/credential_store.gd").new(security, directory + "/tokens")))
	var app = load("res://scenes/main.tscn").instantiate()
	app.setup(account, directory + "/window.cfg")
	root.add_child(app)
	app.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	return app

func run() -> void:
	DirAccess.make_dir_recursive_absolute(ARTIFACTS)
	root.content_scale_size = Vector2i.ZERO
	var directory := "user://appearance-app-%s" % Time.get_ticks_usec()
	DirAccess.make_dir_recursive_absolute(directory)
	var app := make_app(directory)
	await create_timer(.4).timeout
	_check_compact_transparent_login_geometry_unchanged()
	_check_application_defaults_to_flat_svg(app)
	await capture(root, "login-flat")
	await app._session.perform("login", OS.get_environment("GODOT_TEST_SERVER"), {"username":"visual","password":"synthetic","request_token":false}, false)
	check(await until(func(): return app._chat_view != null and app._chat.get_state().phase == "ready"), "local fixture login and chat ready")
	if app._chat_view == null:
		app.queue_free()
		await process_frame
		quit(1)
		return
	var chat = app._chat_view
	chat.get_node("%Input").text = "今天也一起慢慢来吧。"
	chat.get_node("%Send").pressed.emit()
	check(await until(func(): return chat.find_child("MessageAudio", true, false) != null), "real reply creates audio controls")
	chat.get_node("%Input").text = "切换风格后保留的草稿"
	app.get_node("%NavSettings").pressed.emit()
	app.get_node("%NavLogs").pressed.emit()
	app.get_node("%NavDynamics").pressed.emit()
	var settings = app.find_child("SettingsWindow", true, false)
	var logs = app.find_child("LogWindow", true, false)
	var dynamics = app.find_child("DynamicsWindow", true, false)
	_check_all_application_windows_open(settings, logs, dynamics)
	check(await until(func(): return app._dynamics.get_posts().size() > 0), "dynamics fixture loaded")
	check(dynamics.select_post("visual-post"), "dynamic detail opens")
	var image: Texture2D = load("res://assets/ui/tianyi_icon.png")
	var viewer = app._images_presenter.open_image(root, func(): return image)
	viewer.hide()
	logs.hide()
	dynamics.hide()
	await _check_style_combinations(app, settings, chat, dynamics, logs, viewer, image)
	dynamics.close_requested.emit()
	viewer.queue_free()
	await process_frame
	app.get_node("%NavDynamics").pressed.emit()
	dynamics = app.find_child("DynamicsWindow", true, false)
	check_icon(dynamics, "Refresh", "action_refresh", true)
	viewer = app._images_presenter.open_image(root, func(): return image)
	check_icon(viewer, "ZoomIn", "zoom_in", true)
	viewer.hide()
	dynamics.hide()
	# The last choice must be applied before login on the next application instance.
	app.queue_free()
	await process_frame
	await process_frame
	app = make_app(directory)
	await create_timer(.3).timeout
	_check_new_application_restores_appearance_before_login(app)
	check_icon(app, "NavChat", "nav_chat", true)
	await capture(root, "login-restored-crystal")
	await app._session.perform("login", OS.get_environment("GODOT_TEST_SERVER"), {"username":"visual","password":"synthetic","request_token":false}, false)
	app.get_node("%NavSettings").pressed.emit()
	settings = app.find_child("SettingsWindow", true, false)
	check(settings.get_node("%StylePage").get_node("%UiStyleField").text == "清透", "reopened settings shows persisted choice")
	check_icon(app._chat_view, "Send", "action_send", true)
	check(app._services.ui_style.save_preferences("flat", "svg") == OK, "reset fixture to defaults")
	app.queue_free()
	await process_frame
	print("Application UI style: ", "PASS" if failures.is_empty() else "FAIL: " + str(failures))
	quit(0 if failures.is_empty() else 1)
func _check_compact_transparent_login_geometry_unchanged() -> void:
	check(root.size == Vector2i(480,690) and root.unresizable and root.borderless and root.transparent_bg, "compact transparent login geometry unchanged")

func _check_scene_roots_retain_the_single_shared_theme(app: Variant, theme: Variant, settings: Variant, dynamics: Variant) -> void:
	check(app.theme == theme and settings.theme == theme and dynamics.theme == theme, "scene roots retain the single shared theme")

func _check_all_application_windows_open(settings: Variant, logs: Variant, dynamics: Variant) -> void:
	check(settings != null and logs != null and dynamics != null, "all application windows open")

func _check_existing_message_changes_without_rebuilding_chat(panel: Variant, crystal: Variant) -> void:
	check(panel.corner_radius_top_left == (12 if crystal else 8), "existing message changes without rebuilding chat")

func _check_run_result(result: Variant, settings: Variant, pair: Variant) -> void:
	check(result.ok and not settings.is_dirty(), "settings saves combination: " + str(pair))

func _check_open_surfaces_hot_switch_shadows(theme: Variant, crystal: Variant) -> void:
	check(theme.get_stylebox("panel", "AppSurface").shadow_size == (12 if crystal else 0), "open surfaces hot-switch shadows")

func _check_application_defaults_to_flat_svg(app: Variant) -> void:
	check(app._services.ui_style.ui_style == "flat" and app._services.ui_style.icon_style == "svg", "application defaults to flat/svg")

func _check_new_application_restores_appearance_before_login(app: Variant) -> void:
	check(app._services.ui_style.ui_style == "crystal" and app._services.ui_style.icon_style == "emoji", "new application restores appearance before login")

func _check_style_combinations(app: Variant, settings: Variant, chat: Variant, dynamics: Variant, logs: Variant, viewer: Variant, image: Texture2D) -> void:
	for pair in [["flat","svg"],["flat","emoji"],["crystal","svg"],["crystal","emoji"]]:
		settings.open()
		settings.select_page("style")
		var page = settings.get_node("%StylePage")
		page.get_node("%UiStylePresets").activated.emit(pair[0])
		page.get_node("%IconStylePresets").activated.emit(pair[1])
		var result: Dictionary = await settings.save_changes()
		_check_run_result(result, settings, pair)
		var emoji: bool = pair[1] == "emoji"
		var crystal: bool = pair[0] == "crystal"
		for entry in [["NavChat","nav_chat"],["NavDynamics","nav_at"],["NavSettings","nav_settings"],["NavLogs","nav_scroll"]]:
			check_icon(app, entry[0], entry[1], emoji)
		for frame in 2: await process_frame
		for name in ["NavChat", "NavDynamics", "NavSettings"]:
			check(app.get_node("%" + name).size.is_equal_approx(Vector2(64, 64)), "square navigation in " + str(pair) + ": " + name)
		for entry in [["Send","action_send"],["ImageButton","action_image"],["Latest","action_arrow_down"],["VolumeButton","media_volume"]]:
			check_icon(chat, entry[0], entry[1], emoji)
		for entry in [["Publish","action_edit"],["Refresh","action_refresh"],["ReadAll","action_check_all"]]:
			check_icon(dynamics, entry[0], entry[1], emoji)
		check_icon(logs, "CopyButton", "action_copy", emoji)
		check_icon(logs, "ExportButton", "action_export", emoji)
		for entry in [["ZoomIn","zoom_in"],["ZoomOut","zoom_out"],["FitImage","zoom_fit"],["OriginalSize","zoom_1to1"],["CloseImage","action_close"]]:
			check_icon(viewer, entry[0], entry[1], emoji)
		var theme: Theme = load("res://theme/app_theme.tres")
		_check_scene_roots_retain_the_single_shared_theme(app, theme, settings, dynamics)
		for kind in ["LineEdit", "TextEdit", "RichTextLabel"]:
			check(theme.get_color("selection_color", kind).is_equal_approx(Color("0078d7")), "text selection stays blue in " + str(pair) + ": " + kind)
			check(theme.get_color("font_selected_color", kind).is_equal_approx(Color.WHITE), "selected text stays white in " + str(pair) + ": " + kind)
		_check_open_surfaces_hot_switch_shadows(theme, crystal)
		for bubble in chat.get_node("%Scroll").get_node("%Canvas").get_children():
			var panel: StyleBoxFlat = bubble.get_node("%Bubble").get_theme_stylebox("panel")
			_check_existing_message_changes_without_rebuilding_chat(panel, crystal)
		check(chat.get_node("%Input").text == "切换风格后保留的草稿", "application preserves composer draft")
		var label: String = pair[0] + "-" + pair[1]
		var form_scroll: ScrollContainer = page.find_child("Scroll", true, false)
		await create_timer(.2).timeout
		form_scroll.ensure_control_visible(page.get_node("%IconStylePresets"))
		await process_frame
		await process_frame
		check(form_scroll.get_global_rect().encloses(page.get_node("%IconStylePresets").get_global_rect()), "icon style selector remains reachable")
		await capture(settings, "settings-" + label)
		settings.hide()
		await capture(root, "chat-" + label)
		logs.open()
		await capture(logs, "logs-" + label)
		logs.hide()
		dynamics.get_node("%Chrome").open_window()
		await capture(dynamics, "dynamics-" + label)
		dynamics.hide()
		viewer.present(root, func(): return image)
		await capture(viewer, "image-" + label)
		viewer.hide()
