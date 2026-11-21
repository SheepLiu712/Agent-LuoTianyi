extends SceneTree

const Style = preload("res://src/application/ui_style.gd")
const Store = preload("res://src/storage/godot_settings_store.gd")
var failures: Array[String] = []


func _initialize() -> void:
	run.call_deferred()


func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)


func run() -> void:
	var style_path := "user://action-icon-style-%s.cfg" % Time.get_ticks_usec()
	var style = Style.new()
	style.configure(Store.new(style_path))
	check(style.save_preferences("crystal", "svg") == OK, "crystal style enabled")

	var chat = load("res://scenes/ui/chat/chat_view.tscn").instantiate()
	chat.set_ui_style(style)
	root.add_child(chat)
	var settings = load("res://scenes/ui/windows/settings_window.tscn").instantiate()
	settings.set_ui_style(style)
	settings.setup(null, null, null, func(_days): return OK)
	root.add_child(settings)
	var detail = load("res://scenes/ui/dynamics/dynamic_detail.tscn").instantiate()
	detail.set_ui_style(style)
	root.add_child(detail)
	var dynamics = load("res://scenes/ui/windows/dynamics_window.tscn").instantiate()
	dynamics.set_ui_style(style)
	root.add_child(dynamics)
	await process_frame

	_check_chat_styles(chat, true)
	_check_settings_styles(settings, true)
	_check_detail_styles(detail, true)
	_check_dynamics_styles(dynamics, true)
	await _check_icon_hover(chat, "crystal")

	check(style.save_preferences("flat", "svg") == OK, "flat style enabled")
	await process_frame
	_check_chat_styles(chat, false)
	_check_settings_styles(settings, false)
	_check_detail_styles(detail, false)
	_check_dynamics_styles(dynamics, false)
	await _check_icon_hover(chat, "flat")

	chat.queue_free()
	settings.queue_free()
	detail.queue_free()
	dynamics.queue_free()
	await process_frame
	style.save_preferences("flat", "svg")
	DirAccess.remove_absolute(style_path)
	print("Action and icon styles: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func _check_chat_styles(chat: Node, crystal: bool) -> void:
	for name in ["ImageButton", "VolumeButton"]:
		var button: Button = chat.get_node("%" + name)
		check(button.get_theme_type_variation() == &"ChatIconButton", "icon button shares the gray hover variant: " + name)
		var normal := button.get_theme_stylebox("normal") as StyleBoxFlat
		var hover := button.get_theme_stylebox("hover") as StyleBoxFlat
		var pressed := button.get_theme_stylebox("pressed") as StyleBoxFlat
		var focus := button.get_theme_stylebox("focus") as StyleBoxFlat
		var radius := 12 if crystal else 8
		check(normal.corner_radius_top_left == radius and hover.corner_radius_top_left == radius, "icon hover radius follows mode: " + name)
		check(normal.bg_color.a == 0 and hover.bg_color.a > 0, "icon background is transparent until hover: " + name)
		check(is_equal_approx(hover.bg_color.a, 0.72 if crystal else 1.0), "icon hover gray opacity follows mode: " + name)
		check(pressed.bg_color.get_luminance() < hover.bg_color.get_luminance(), "icon pressed state is darker than hover: " + name)
		check(hover.shadow_size == (3 if crystal else 0), "icon hover shadow follows mode: " + name)
		check(focus.border_width_top == 1 and focus.bg_color.a > 0, "keyboard focus shares the gray state: " + name)
		check(hover.content_margin_left == 0 and hover.content_margin_top == 0, "hover state does not change icon layout: " + name)
		check(button.custom_minimum_size == Vector2(36, 32), "icon hover keeps the original minimum size: " + name)
		check(button.icon_alignment == HORIZONTAL_ALIGNMENT_CENTER, "icon stays centered inside its hover target: " + name)
	var send: Button = chat.get_node("%Send")
	_check_action(send, "chat send", crystal)


func _check_settings_styles(settings: Window, crystal: bool) -> void:
	for name in ["LogoutButton", "CloseSettings"]:
		_check_action(settings.get_node("%" + name), "settings " + name, crystal)
	_check_action(settings.get_node("%SaveAll"), "settings save", crystal)


func _check_detail_styles(detail: Node, crystal: bool) -> void:
	_check_action(detail.get_node("%Send"), "dynamic comment send", crystal)
	_check_action(detail.get_node("%ReplySend"), "dynamic reply send", crystal)
	var draft := detail.get_node("%CommentDraft").get_theme_stylebox("normal") as StyleBoxFlat
	check(draft.corner_radius_top_left == (12 if crystal else 8), "dynamic detail input follows mode")
	check(draft.shadow_size == (3 if crystal else 0), "dynamic detail input shadow follows mode")


func _check_dynamics_styles(window: Window, crystal: bool) -> void:
	var panel := window.get_node("Panel").get_theme_stylebox("panel") as StyleBoxFlat
	var right := window.get_node("%Right").get_theme_stylebox("panel") as StyleBoxFlat
	check(panel.corner_radius_top_left == 0, "dynamics outer window shell stays square")
	check(panel.shadow_size == 0 and is_equal_approx(panel.bg_color.a, 1.0), "dynamics outer window shell stays flat and opaque")
	check(right.corner_radius_top_left == (12 if crystal else 8), "dynamics detail panel applies the mode on first open")


func _check_icon_hover(chat: Control, mode: String) -> void:
	if DisplayServer.get_name() == "headless":
		return
	chat.size = Vector2(700, 560)
	chat.position = Vector2.ZERO
	await process_frame
	await process_frame
	var host := chat.get_window()
	for name in ["ImageButton", "VolumeButton"]:
		var button: Button = chat.get_node("%" + name)
		var point := button.get_global_rect().get_center()
		var enter := InputEventMouseMotion.new()
		enter.position = point
		host.push_input(enter, true)
		await process_frame
		check(button.is_hovered(), "mouse enter reveals gray icon state: " + name + "/" + mode)
		if name == "ImageButton":
			await RenderingServer.frame_post_draw
			DirAccess.make_dir_recursive_absolute("res://artifacts/visual-unified")
			root.get_texture().get_image().save_png("res://artifacts/visual-unified/icon-hover-%s.png" % mode)
		var leave := InputEventMouseMotion.new()
		leave.position = Vector2(2, chat.size.y - 2)
		host.push_input(leave, true)
		await process_frame
		check(not button.is_hovered(), "mouse leave restores the transparent icon state: " + name + "/" + mode)


func _check_action(button: Button, label: String, crystal: bool) -> void:
	var normal := button.get_theme_stylebox("normal") as StyleBoxFlat
	var hover := button.get_theme_stylebox("hover") as StyleBoxFlat
	check(normal.corner_radius_top_left == (12 if crystal else 8), label + " radius follows mode")
	check(hover.corner_radius_top_left == (12 if crystal else 8), label + " hover radius follows mode")
	check(normal.shadow_size == (6 if crystal else 0), label + " shadow follows mode")
	check(is_equal_approx(normal.bg_color.a, 0.94 if crystal else 1.0), label + " surface opacity follows mode")
