extends SceneTree
const ARTIFACTS := "res://artifacts/ui-redraw-client"
var failures: Array[String] = []

func _initialize() -> void:
	run.call_deferred()

func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)

func until(predicate: Callable) -> bool:
	var deadline := Time.get_ticks_msec() + 6000
	while not predicate.call() and Time.get_ticks_msec() < deadline:
		await process_frame
	return predicate.call()

func run() -> void:
	print("Chat review layout: START")
	if DisplayServer.get_name() == "headless" or OS.get_environment("GODOT_TEST_SERVER").is_empty():
		print("FAIL: requires GPU and loopback fixture")
		quit(1)
		return
	create_timer(45).timeout.connect(func():
		print("FAIL: chat review layout watchdog")
		quit(1))
	DirAccess.make_dir_recursive_absolute(ARTIFACTS)
	root.content_scale_size = Vector2i.ZERO
	var directory := "user://chat-review-%s" % Time.get_ticks_usec()
	DirAccess.make_dir_recursive_absolute(directory)
	var security = ClassDB.instantiate("WindowsSecurity")
	var account = load("res://src/session/account_session.gd").new(
		load("res://src/network/account_api.gd").new(security),
		load("res://src/storage/godot_storage_service.gd").new(directory + "/account.cfg",
		load("res://src/storage/credential_store.gd").new(security, directory + "/tokens")))
	var app = load("res://scenes/main.tscn").instantiate()
	app.setup(account, directory + "/window.cfg")
	root.add_child(app)
	app.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	print("Chat review layout: mounted actual application")
	await account.perform("login", OS.get_environment("GODOT_TEST_SERVER"), {"username":"visual", "password":"synthetic", "request_token":false}, false)
	check(await until(func(): return app._chat_view != null and app._chat.get_state().phase == "ready"), "actual application login reaches chat")
	if app._chat_view == null:
		quit(1)
		return
	print("Chat review layout: actual application signed in")
	var chat: Control = app._chat_view
	var split: HSplitContainer = app.get_node("%Split")
	check(app._avatar.avatar.get_status().loaded, "real Live2D model loaded")
	check(await until(func(): return not app._dynamics.get_latest_unread().is_empty()), "actual unread dynamic fetched")
	check(app._avatar.get_node("%Heading").visible, "unread dynamic card is shown")
	check(app._avatar.get_node("Heading/Identity/Companion").text == app._dynamics.get_latest_unread().content, "card displays actual latest unread content")
	check(app._dynamics.get_state().unread == 123, "displaying the card does not mark it read")
	for frame in 4: await process_frame
	var default_framing: Transform2D = app._avatar.avatar.transform
	app._avatar.framing.zoom_by(1.25)
	app._avatar.framing.pan_by(Vector2(24, 16), app._avatar.get_node("%Stage").size)
	app._avatar._layout_avatar()
	check(not app._avatar.avatar.transform.is_equal_approx(default_framing), "framing changes before floating reset")
	var reset: Button = app._avatar.get_node("%Reset")
	var reset_point := reset.get_global_rect().get_center()
	var motion := InputEventMouseMotion.new()
	motion.position = reset_point
	motion.global_position = reset_point
	Input.parse_input_event(motion)
	await process_frame
	await _click_reset(reset_point)
	check(app._avatar.avatar.transform.is_equal_approx(default_framing), "clicking floating reset restores original framing")
	chat.get_node("%Input").text = "今天忙了一整天，有点累了。"
	chat.get_node("%Send").pressed.emit()
	check(await until(func(): return app._chat.get_message_audio("redesign-voice").available), "real loopback reply audio cached")
	app._chat.stop_voice()
	chat.get_node("%Input").text = "切换风格后仍然保留的草稿"
	chat.get_node("%Input").text_changed.emit()
	await _check_style_layouts(app, chat, split)
	chat.get_node("%Input").text = "第一行\n第二行\n第三行\n第四行\n第五行\n第六行"
	chat.get_node("%Input").text_changed.emit()
	chat._attach({"ok":false, "code":"IMAGE_TOO_LARGE"})
	await capture(app, chat, "compact-long-input-error")
	chat.get_node("%ImageStatus").hide()
	chat.get_node("%Input").clear()
	app.get_node("%NavDynamics").pressed.emit()
	var dynamics = app.find_child("DynamicsWindow", true, false)
	_check_navigation_opens_independent_dynamics_window(dynamics)
	if dynamics != null: dynamics.hide()
	app.get_node("%NavSettings").pressed.emit()
	var settings = app.find_child("SettingsWindow", true, false)
	_check_settings_entry_remains_functional(settings)
	if settings != null: settings.hide()
	app.get_node("%NavLogs").pressed.emit()
	var logs = app.find_child("LogWindow", true, false)
	_check_logs_entry_remains_functional(logs)
	if logs != null: logs.hide()
	await capture_samples(app, chat)
	await app._dynamics.mark_read()
	check(not app._avatar.get_node("%Heading").visible, "explicit mark read hides the card")
	await capture(app, chat, "review-no-unread-960x640")
	app.queue_free()
	await process_frame
	print("Chat review layout: ", "PASS" if failures.is_empty() else "FAIL: " + str(failures))
	quit(0 if failures.is_empty() else 1)
func capture(app: Control, chat: Control, label: String) -> void:
	var started := Time.get_ticks_msec()
	print("Chat review capture begin: ", label)
	await create_timer(0.15).timeout
	var viewport := Rect2(Vector2.ZERO, Vector2(root.size))
	for name in ["Input", "Send", "ImageButton", "VolumeButton", "Latest", "Unread"]:
		var control: Control = chat.get_node("%" + name)
		if not control.is_visible_in_tree(): continue
		check(viewport.encloses(control.get_global_rect()), label + ": visible " + name)
		check(chat.get_global_rect().encloses(control.get_global_rect()), label + ": contained " + name)
	var input_rect: Rect2 = chat.get_node("%Input").get_global_rect()
	var send_rect: Rect2 = chat.get_node("%Send").get_global_rect()
	check(send_rect.position.x >= input_rect.end.x and send_rect.end.y <= input_rect.end.y + 1, label + ": icon send beside input")
	check(is_equal_approx(send_rect.size.x, send_rect.size.y), label + ": send remains square")
	check(chat.get_node("%ImageButton").get_global_rect().end.y <= input_rect.position.y, label + ": image above input")
	check(chat.get_node("%VolumeButton").get_global_rect().end.y <= input_rect.position.y, label + ": volume above input")
	check(chat.get_node("%Hint").horizontal_alignment == HORIZONTAL_ALIGNMENT_RIGHT, label + ": shortcut hint aligned right")
	for bubble in chat.get_node("%Scroll").get_node("%Canvas").get_children():
		if bubble._own and not bubble.get_node("%Caption").text.is_empty():
			check(bubble.get_node("%Caption").text in ["发送失败", "无法确认送达，请勿重复发送"], label + ": only exceptional delivery captions")
	var composer: Control = chat.get_node("Margin/Column/ComposerSurface")
	check(chat.get_node("%Scroll").get_global_rect().end.y <= composer.get_global_rect().position.y + 1, label + ": composer does not cover messages")
	check(chat.get_node("%Scroll").size.y >= 160, label + ": message area remains usable")
	check(absf(app.get_node("%Navigation").size.x - 80) < 1, label + ": 80px navigation")
	for name in ["NavChat", "NavDynamics", "NavSettings"]:
		check(app.get_node("%" + name).size.is_equal_approx(Vector2(64, 64)), label + ": square " + name)
	check(app.get_node("%Navigation").find_children("*", "TextureRect", true, false).is_empty(), label + ": navigation avatars removed")
	check(chat.get_node_or_null("%StopVoice") == null, label + ": stop voice removed")
	check(app._avatar.get_node_or_null("%Footer") == null and app._avatar.find_child("GestureHint", true, false) == null, label + ": avatar footer and hint removed")
	var stage: Control = app._avatar.get_node("%Stage")
	var reset: Button = app._avatar.get_node("%Reset")
	check(stage.size.is_equal_approx(app._avatar.size), label + ": full-height avatar stage")
	check(stage.get_global_rect().encloses(reset.get_global_rect()), label + ": reset floats inside avatar stage")
	check(reset.z_index > stage.z_index and reset.mouse_filter == Control.MOUSE_FILTER_STOP, label + ": reset overlays stage without passing through clicks")
	check(reset.size.is_equal_approx(Vector2(88, 36)), label + ": compact floating reset")
	check((stage.get_global_rect().end - reset.get_global_rect().end).is_equal_approx(Vector2(16, 16)), label + ": floating reset follows bottom-right resize")
	await RenderingServer.frame_post_draw
	check(root.get_texture().get_image().save_png(ARTIFACTS.path_join(label + ".png")) == OK, "native capture " + label)
	print("Chat review capture: ", label, " ", Time.get_ticks_msec() - started, "ms")

func capture_samples(app: Control, chat: Control) -> void:
	print("Chat review samples: begin")
	var audio: Dictionary = app._chat.get_message_audio("redesign-voice")
	app._chat.stop()
	var scroll = chat.get_node("%Scroll")
	scroll.visible_messages.disconnect(chat._visible_audio)
	var samples: Array[Dictionary] = [
		{"id":"date", "role":"system", "text":"今天 · 9 月 30 日"},
		{"id":"greeting", "role":"assistant", "text":"回来啦。今天过得怎么样？", "status":"sent", "code":""},
		{"id":"short", "role":"user", "text":"刚忙完，想和你一起放松一下。", "status":"sent", "code":"", "demo":true},
		{"id":"voice", "role":"assistant", "text":"辛苦啦，先让自己休息一会儿吧。\n我在这里陪着你，想说什么都可以。", "status":"sent", "code":""},
		{"id":"picture", "role":"user", "type":"image", "text":"今天窗边的光很好看。", "status":"sent", "code":"", "demo":true},
		{"id":"long", "role":"assistant", "text":"有些日子不一定要安排得满满当当。可以先喝一杯水，看看窗外，再慢慢聊今天发生的事。\n\n如果有不开心的片段，也可以一点一点说给我听。不用急着想好答案，我会在这里陪着你。", "status":"sent", "code":""}
	]
	chat.get_node("%Status").text = "布局样例 · 离线固定内容"
	chat.get_node("%Empty").hide()
	chat.get_node("%Latest").hide()
	chat.get_node("%Unread").show()
	chat.get_node("%Input").clear()
	chat.get_node("%Input").text_changed.emit()
	var photo: Image = load("res://assets/ui/bg2.jpg").get_image()
	photo.resize(156, 84)
	var photo_texture := ImageTexture.create_from_image(photo)
	for dimensions in [Vector2i(1280, 800)]:
		root.size = dimensions
		app._ratio = 1.0 / 3.0
		app._resize_split()
		await process_frame
		scroll.set_messages(samples)
		check(scroll.scroll_to_message("date"), "sample starts at the first message")
		for frame in 4: await process_frame
		scroll.set_audio_state("voice", audio)
		scroll.set_image_state("picture", {"status":"ready", "texture":photo_texture, "code":"", "original_size":Vector2i(156, 84)})
		for frame in 4: await process_frame
		for pair in [["flat", "svg"], ["crystal", "svg"]]:
			check(app._services.ui_style.save_preferences(pair[0], pair[1]) == OK, "sample theme switches")
			for frame in 4: await process_frame
			check(scroll.scroll_to_message("date"), "sample framing starts at date after content settles")
			await capture(app, chat, "review-%s-%sx%s" % [pair[0], dimensions.x, dimensions.y])
			check(chat.find_child("CompanionHint", true, false) == null, "decorative chat header hint removed")
			var selected_text: RichTextLabel = scroll.get_node("%Canvas").get_children().filter(func(bubble): return bubble.get_node("%Text").text == "回来啦。今天过得怎么样？")[0].get_node("%Text")
			selected_text.select_all()
			check(selected_text.get_selected_text() == selected_text.text, "chat text remains selectable")
			await capture(app, chat, "review-selection-%s-%sx%s" % [pair[0], dimensions.x, dimensions.y])
			selected_text.deselect()
	check(scroll.scroll_to_message("long"), "long sample remains scrollable")
	root.size = Vector2i(960, 640)
	await capture(app, chat, "review-long-message-960x640")

func _click_reset(reset_point: Vector2) -> void:
	for pressed in [true, false]:
		var click := InputEventMouseButton.new()
		click.position = reset_point
		click.global_position = reset_point
		click.button_index = MOUSE_BUTTON_LEFT
		click.pressed = pressed
		Input.parse_input_event(click)
		await process_frame

func _check_volume_icon_opens_an_interactive_slider(chat: Variant) -> void:
	check(chat.get_node("%VolumePopup").visible and chat.get_node("%Volume").is_visible_in_tree(), "volume icon opens an interactive slider")

func _check_volume_popup_slider_remains_usable(chat: Variant) -> void:
	check(chat.get_node("%Volume").size.x >= 180 and chat.get_node("%Volume").size.y >= 24, "volume popup slider remains usable")

func _check_navigation_opens_independent_dynamics_window(dynamics: Variant) -> void:
	check(dynamics != null and dynamics.visible, "navigation opens independent dynamics window")

func _check_settings_entry_remains_functional(settings: Variant) -> void:
	check(settings != null and settings.visible, "settings entry remains functional")

func _check_logs_entry_remains_functional(logs: Variant) -> void:
	check(logs != null and logs.visible, "logs entry remains functional")

func _check_style_layouts(app: Variant, chat: Variant, split: HSplitContainer) -> void:
	for dimensions in [Vector2i(1280, 800), Vector2i(960, 640)]:
		root.size = dimensions
		await process_frame
		await process_frame
		chat.get_node("%Latest").show()
		chat.get_node("%Unread").show()
		for pair in [["flat", "svg"], ["crystal", "svg"]]:
			var offset: int = split.split_offset
			var anchor: Dictionary = chat.get_node("%Scroll").get_reading_anchor()
			check(app._services.ui_style.save_preferences(pair[0], pair[1]) == OK, "appearance saves " + str(pair))
			await create_timer(0.15).timeout
			check(split.split_offset == offset, "theme switch preserves split ratio")
			check(chat.get_node("%Scroll").get_reading_anchor().get("id") == anchor.get("id"), "theme switch preserves reading message")
			check(chat.get_node("%Input").text == "切换风格后仍然保留的草稿", "theme switch preserves input")
			var label: String = "%s-%s-%sx%s" % [pair[0], pair[1], dimensions.x, dimensions.y]
			await capture(app, chat, label)
		check(app._services.ui_style.save_preferences("crystal", "emoji") == OK, "emoji switch saves")
		check(chat.get_node("%Send").icon.resource_path.ends_with("action_send_emoji.png"), "original emoji icon applied")
		check(chat.get_node("%VolumeButton").icon.resource_path.ends_with("media_volume_emoji.png"), "original volume emoji applied")
		check(chat.get_node("%Input").text == "切换风格后仍然保留的草稿", "emoji switch preserves input")
		check(app._services.ui_style.save_preferences("crystal", "svg") == OK, "SVG switch saves")
		check(chat.get_node("%Send").icon.resource_path.ends_with("action_send.svg"), "original SVG icon applied")
		check(chat.get_node("%VolumeButton").icon.resource_path.ends_with("media_volume.svg"), "original volume SVG applied")
		chat.get_node("%VolumeButton").pressed.emit()
		await process_frame
		_check_volume_icon_opens_an_interactive_slider(chat)
		_check_volume_popup_slider_remains_usable(chat)
		chat.get_node("%Volume").value = 0.37
		check(is_equal_approx(app._chat.get_audio_state().volume, 0.37), "popup slider changes actual voice volume")
		await RenderingServer.frame_post_draw
		check(root.get_texture().get_image().save_png(ARTIFACTS.path_join("volume-popup-%sx%s.png" % [dimensions.x, dimensions.y])) == OK, "volume popup capture")
		chat.get_node("%VolumePopup").hide()
		split.split_offset += 32
		await process_frame
		split.dragged.emit(split.split_offset)
		await process_frame
		check(absf(app._ratio - app._avatar.size.x / split.size.x) < 0.01, "native splitter updates persisted ratio")
		app._ratio = 1.0 / 3.0
		app._resize_split()
		await process_frame
