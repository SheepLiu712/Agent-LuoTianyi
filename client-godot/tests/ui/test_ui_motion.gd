extends SceneTree

const UiMotion = preload("res://src/ui/ui_motion.gd")
const UiStyle = preload("res://src/application/ui_style.gd")
const Store = preload("res://src/storage/godot_settings_store.gd")

var failures: Array[String] = []


func _initialize() -> void:
	run.call_deferred()


func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)


func run() -> void:
	var store_path := "user://ui-motion-%s.cfg" % Time.get_ticks_usec()
	var style := UiStyle.new()
	style.configure(Store.new(store_path))

	await _check_tactile_press(style)
	await _check_overlay_motion(style)
	await _check_reduced_motion(style)

	DirAccess.remove_absolute(store_path)
	print("UI motion: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func _check_tactile_press(style: RefCounted) -> void:
	var btn := Button.new()
	btn.size = Vector2(120, 40)
	root.add_child(btn)
	UiMotion.bind_tactile_press(btn, style)
	btn.button_down.emit()
	await create_timer(0.11).timeout
	check(btn.pivot_offset.is_equal_approx(Vector2(60, 20)), "tactile press centers pivot")
	check(btn.scale.x < 0.99, "tactile press scales down cleanly")
	btn.button_up.emit()
	await create_timer(0.18).timeout
	check(btn.scale.is_equal_approx(Vector2.ONE), "tactile release restores unit scale")
	btn.queue_free()
	await process_frame


func _check_overlay_motion(style: RefCounted) -> void:
	var host := Control.new()
	host.size = Vector2(400, 300)
	root.add_child(host)
	var panel := PanelContainer.new()
	panel.size = Vector2(200, 120)
	panel.visible = false
	host.add_child(panel)
	UiMotion.reveal_overlay(panel, Vector2(0.5, 0.5), -6.0, 0.18, style)
	check(panel.visible and panel.scale.x >= 0.94, "overlay never starts at scale zero")
	await create_timer(0.22).timeout
	check(panel.scale.is_equal_approx(Vector2.ONE) and is_equal_approx(panel.modulate.a, 1.0), "overlay settles at full scale and opacity")
	UiMotion.dismiss_overlay(panel, Callable(), Vector2(0.5, 0.5), 0.12, style)
	await create_timer(0.16).timeout
	check(not panel.visible and panel.scale.is_equal_approx(Vector2.ONE), "dismiss hides and resets scale")
	host.queue_free()
	await process_frame


func _check_reduced_motion(style: RefCounted) -> void:
	check(style.save_preferences("flat", "svg", true) == OK, "reduced motion preference persists")
	var panel := PanelContainer.new()
	panel.size = Vector2(180, 100)
	panel.visible = false
	root.add_child(panel)
	UiMotion.reveal_overlay(panel, Vector2(0.5, 0.5), -6.0, 0.18, style)
	check(panel.visible and panel.scale.is_equal_approx(Vector2.ONE) and is_equal_approx(panel.modulate.a, 1.0), "reduced motion reveals instantly")
	UiMotion.dismiss_overlay(panel, Callable(), Vector2(0.5, 0.5), 0.12, style)
	check(not panel.visible, "reduced motion dismisses instantly")
	panel.queue_free()
	await process_frame
