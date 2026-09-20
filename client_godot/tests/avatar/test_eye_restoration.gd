extends SceneTree
var failures: Array[String] = []

func _initialize() -> void:
	run.call_deferred()

func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)

func run() -> void:
	var driver = load("res://src/avatar/avatar_driver.gd").new()
	root.add_child(driver)
	check(driver.load_character("res://assets/live2d/character.json") == OK, "real character loads")
	check(driver.get_status().has("eye_openness"), "driver reports actual eye openness")
	if failures.is_empty():
		await create_timer(0.35).timeout
		check(driver.get_status().eye_openness.is_equal_approx(Vector2.ONE), "normal eyes stay fully open after initial frames")
		var blink_observed := false
		var deadline := Time.get_ticks_msec() + 4800
		while Time.get_ticks_msec() < deadline:
			await process_frame
			if driver.get_status().eye_openness.x < 0.5: blink_observed = true
		check(blink_observed, "natural blinking remains enabled")
		check(driver.get_status().eye_openness.is_equal_approx(Vector2.ONE), "blink finishes with open eyes")
		driver.apply_expression("温柔脸")
		await create_timer(0.5).timeout
		check(driver.get_status().eye_openness.length() < 0.1, "intentional closed-eye expression is preserved")
		driver.apply_expression("normal")
		driver.set_mouth_openness(0.8)
		await create_timer(0.5).timeout
		check(driver.get_status().eye_openness.is_equal_approx(Vector2.ONE), "normal expression restores eyes independently of mouth")
	driver.free()
	print("Avatar eye restoration: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
