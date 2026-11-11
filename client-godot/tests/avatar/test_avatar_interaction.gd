extends SceneTree
var failures: Array[String] = []
func _initialize() -> void: run.call_deferred()
func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)
func run() -> void:
	if DisplayServer.get_name() == "headless":
		print("Avatar interaction requires a graphical window; minimized windows intentionally suspend the avatar")
		quit(2)
		return
	_setup_window()
	var panel = load("res://scenes/avatar/avatar_panel.tscn").instantiate()
	root.add_child(panel)
	await process_frame
	var driver = panel.avatar
	check(driver.has_method("set_gaze") and driver.has_method("hit_test") and panel.has_signal("touched"), "avatar exposes gaze and mesh touch")
	if failures.is_empty():
		await _exercise_avatar(panel, driver)
	panel.queue_free()
	await process_frame
	print("Avatar interaction: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func _setup_window() -> void:
	root.size = Vector2i(600, 800)
	root.content_scale_size = Vector2i(600, 800)
	root.content_scale_mode = Window.CONTENT_SCALE_MODE_CANVAS_ITEMS


func _exercise_avatar(panel, driver) -> void:
	_check_hit_areas(driver)
	await _check_gaze(panel, driver)
	await _check_touch(panel, driver)
	await _check_dynamic_card(panel)


func _check_hit_areas(driver) -> void:
	check(driver.hit_test(Vector2(25, 55)).has("头"), "actual head mesh accepts touch")
	check(driver.hit_test(Vector2(20, 245)).has("身体"), "actual body mesh accepts touch")
	check(driver.hit_test(Vector2(220, 425)).has("手"), "actual hand mesh accepts touch")
	check(driver.hit_test(Vector2(-2000, -2000)).is_empty(), "background is not touchable")


func _check_gaze(panel, driver) -> void:
	driver.set_gaze(Vector2(1, -1))
	await create_timer(0.4).timeout
	check(driver.get_status().gaze.x > 0.8 and driver.get_status().gaze.y < -0.8, "eyes smoothly follow target")
	panel.mouse_exited.emit()
	await create_timer(0.4).timeout
	check(driver.get_status().gaze.length() < 0.1, "leaving the panel restores neutral gaze")


func _check_touch(panel, driver) -> void:
	var touches: Array = []
	panel.touched.connect(func(areas): touches.append(areas))
	var click := InputEventMouseButton.new()
	click.button_index = MOUSE_BUTTON_LEFT
	click.pressed = true
	click.position = panel.get_global_transform().affine_inverse() * driver.to_global(Vector2(25, 55))
	panel.gui_input.emit(click)
	check(touches.size() == 1 and touches[0].has("头"), "view converts displayed coordinates into model touch")
	check(panel.find_children("TouchRipple*", "Panel", false, false).size() == 1, "touch produces a scene control ripple")
	await create_timer(0.12).timeout
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png("res://artifacts/avatar-touch-feedback.png")
	await create_timer(0.6).timeout
	check(panel.find_children("TouchRipple*", "Panel", false, false).is_empty(), "ripple releases after fading")


func _check_dynamic_card(panel) -> void:
	panel.set_unread_dynamic({"id":"card-test", "author_name":"洛天依", "content":"卡片点击回归"})
	var requested: Array = []
	panel.dynamic_requested.connect(func(post): requested.append(post))
	var heading: Control = panel.get_node("%Heading")
	var card_click := InputEventMouseButton.new()
	card_click.button_index = MOUSE_BUTTON_LEFT
	card_click.pressed = true
	heading.gui_input.emit(card_click)
	await process_frame
	check(panel._dynamic_opening and heading.scale.x < 1.0, "card click starts feedback animation")
	await create_timer(0.25).timeout
	check(requested.size() == 1 and requested[0].id == "card-test", "card click emits its dynamic")
	check(heading.scale.is_equal_approx(Vector2.ONE), "card returns to rest after feedback")
