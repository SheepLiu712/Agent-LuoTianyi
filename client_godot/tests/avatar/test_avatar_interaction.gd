extends SceneTree
var failures: Array[String] = []
func _initialize() -> void: run.call_deferred()
func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)
func run() -> void:
	var panel = load("res://scenes/avatar/avatar_panel.tscn").instantiate()
	root.add_child(panel)
	panel.size = Vector2(600, 800)
	await process_frame
	var driver = panel.avatar
	check(driver.has_method("set_gaze") and driver.has_method("hit_test") and panel.has_signal("touched"), "avatar exposes gaze and mesh touch")
	if failures.is_empty():
		check(driver.hit_test(Vector2(25, 55)).has("头"), "actual head mesh accepts touch")
		check(driver.hit_test(Vector2(20, 245)).has("身体"), "actual body mesh accepts touch")
		check(driver.hit_test(Vector2(220, 425)).has("手"), "actual hand mesh accepts touch")
		check(driver.hit_test(Vector2(-2000, -2000)).is_empty(), "background is not touchable")
		driver.set_gaze(Vector2(1, -1))
		await create_timer(0.4).timeout
		check(driver.get_status().gaze.x > 0.8 and driver.get_status().gaze.y < -0.8, "eyes smoothly follow target")
		panel.mouse_exited.emit()
		await create_timer(0.4).timeout
		check(driver.get_status().gaze.length() < 0.1, "leaving the panel restores neutral gaze")
		var touches: Array = []
		panel.touched.connect(func(areas): touches.append(areas))
		var click := InputEventMouseButton.new()
		click.button_index = MOUSE_BUTTON_LEFT
		click.pressed = true
		click.position = panel.get_global_transform().affine_inverse() * driver.to_global(Vector2(25, 55))
		panel.gui_input.emit(click)
		check(touches.size() == 1 and touches[0].has("头"), "view converts displayed coordinates into model touch")
		check(panel.find_children("TouchRipple*", "Panel", false, false).size() == 1, "touch produces a scene control ripple")
		await create_timer(0.6).timeout
		check(panel.find_children("TouchRipple*", "Panel", false, false).is_empty(), "ripple releases after fading")
	panel.queue_free()
	await process_frame
	print("Avatar interaction: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
