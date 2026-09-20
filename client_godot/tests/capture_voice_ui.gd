extends SceneTree
const Session = preload("res://src/session/chat_session.gd")
const Transport = preload("res://src/network/websocket_transport.gd")
const Audio = preload("res://src/media/reply_audio.gd")
const Cache = preload("res://src/storage/audio_cache.gd")
const VIEW_SCENE := "res://scenes/ui/chat_view.tscn"
const AVATAR_SCENE := "res://scenes/avatar/avatar_panel.tscn"
var failures: Array[String] = []

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	if DisplayServer.get_name() == "headless" or OS.get_environment("GODOT_TEST_SERVER").is_empty():
		push_error("Requires --gpu and loopback fixture")
		quit(1)
		return
	root.content_scale_size = Vector2i.ZERO
	root.size = Vector2i(1200,800)
	root.content_scale_mode = Window.CONTENT_SCALE_MODE_CANVAS_ITEMS
	var directory := "user://capture-voice-%s" % Time.get_ticks_usec()
	var session := Session.new(Transport.new(),null,Audio.new(null,Callable(),Cache.new(directory)))
	root.add_child(session)
	var split := HSplitContainer.new()
	root.add_child(split)
	split.theme = preload("res://src/preview/preview_style.gd").make_theme()
	split.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	if not ResourceLoader.exists(AVATAR_SCENE):
		failures.append("avatar panel scene exists")
		print(failures)
		quit(1)
		return
	var avatar = load(AVATAR_SCENE).instantiate()
	split.add_child(avatar)
	avatar.custom_minimum_size.x = 290
	if not ResourceLoader.exists(VIEW_SCENE):
		failures.append("chat view scene exists")
		print(failures)
		quit(1)
		return
	var view = load(VIEW_SCENE).instantiate()
	view.setup(session)
	view.custom_minimum_size.x = 440
	split.add_child(view)
	split.split_offset = 540
	session.expression_requested.connect(avatar.avatar.apply_expression)
	session.mouth_changed.connect(avatar.avatar.set_mouth_openness)
	session.start({"server":OS.get_environment("GODOT_TEST_SERVER")+"/prefix","username":"visual","message_token":"message-test"})
	var deadline := Time.get_ticks_msec()+5000
	while session.get_state().phase != "ready" and Time.get_ticks_msec() < deadline:
		await process_frame
	session.send_text("今天忙了一整天，有点累了。")
	await create_timer(3.2).timeout
	if not session.get_message_audio("visual-voice").available:
		push_error("Actual loopback voice failed to cache")
		quit(1)
		return
	for dimensions in [Vector2i(1200,800),Vector2i(960,640)]:
		root.size = dimensions
		split.split_offset = roundi(dimensions.x*.45)
		await _capture(view,"agentluo-011-voice-ui-%sx%s" % [dimensions.x,dimensions.y])
	root.size = Vector2i(1200,800)
	split.split_offset = 540
	session.replay("visual-voice")
	await create_timer(.6).timeout
	session.pause_replay()
	await _capture(view,"agentluo-011-voice-ui-paused")
	for factor in [1.25,1.5]:
		root.content_scale_factor = factor
		root.size = Vector2i(Vector2(1200,800)*factor)
		split.split_offset = 540
		await _capture(view,"agentluo-011-voice-ui-scale-%s" % int(factor*100))
	session.clear_cache()
	session.stop()
	split.queue_free()
	session.queue_free()
	await process_frame
	for scope in DirAccess.get_directories_at(directory):
		DirAccess.remove_absolute(directory.path_join(scope))
	DirAccess.remove_absolute(directory)
	print(failures)
	print("Voice UI screenshots/layout: ","PASS" if failures.is_empty() else "FAIL", " (content scaling; not OS DPI switching)")
	quit(0 if failures.is_empty() else 1)

func _capture(view: Control, filename: String) -> void:
	await create_timer(.25).timeout
	for control in view.find_children("*","Control",true,false):
		if not control.is_visible_in_tree() or not (control is Button or control is TextEdit or control is HSlider):
			continue
		var area: Rect2 = control.get_global_rect()
		if not root.get_visible_rect().encloses(area):
			failures.append(filename + ": control outside viewport")
	for button in view.find_children("*","Button",true,false):
		if button.text == "继续":
			button.grab_focus()
	await RenderingServer.frame_post_draw
	var error := root.get_texture().get_image().save_png("res://artifacts/"+filename+".png")
	if error != OK:
		failures.append(filename+": save failed")
