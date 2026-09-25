extends SceneTree
const Framing = preload("res://src/avatar/avatar_framing.gd")
var failures: Array[String] = []


func check(value: bool, label: String) -> void:
	if not value:
		failures.append(label)
		print("FAIL: ", label)


func _initialize() -> void:
	var path := "user://test-framing-%s.cfg" % Time.get_ticks_usec()
	var framing = Framing.new(preload("res://src/storage/godot_settings_store.gd").new(path))
	var panel := Vector2(500, 800)
	var canvas := Vector2(1000, 1000)
	var initial: Transform2D = framing.get_transform(panel, canvas)
	check(initial.origin.is_equal_approx(Vector2(250, 400)), "default centered")
	check(initial.get_scale().is_equal_approx(Vector2(0.6, 0.6)), "default proportional scale")
	framing.pan_by(Vector2(50, 80), panel)
	check(framing.get_transform(panel * 2, canvas).origin.is_equal_approx(Vector2(600, 960)), "normalized position survives resize")
	framing.zoom_by(100)
	check(is_equal_approx(framing.get_transform(panel, canvas).get_scale().x, 1.2), "zoom upper bound")
	framing.pan_by(Vector2(100000, -100000), panel)
	check(framing.get_transform(panel, canvas).origin.is_equal_approx(Vector2(450, 80)), "pan bounded")
	var bounded: Transform2D = framing.get_transform(panel, canvas)
	framing.zoom_by(NAN)
	framing.pan_by(Vector2(INF, 0), panel)
	check(framing.get_transform(panel, canvas).is_equal_approx(bounded), "invalid input preserves frame")
	check(framing.save_settings() == OK, "settings save")
	var restored = Framing.new(preload("res://src/storage/godot_settings_store.gd").new(path))
	check(restored.load_settings() == OK, "settings load")
	check(restored.get_transform(panel, canvas).is_equal_approx(bounded), "new instance restores frame")
	check(Framing.new(preload("res://src/storage/godot_settings_store.gd").new("user://missing-framing-contract.cfg")).load_settings() == ERR_FILE_NOT_FOUND, "missing config reported")
	var corrupt := FileAccess.open(path, FileAccess.WRITE)
	corrupt.store_string("[framing]\nzoom=\"bad\"\noffset=Vector2(0,0)\n")
	corrupt.close()
	check(restored.load_settings() == ERR_INVALID_DATA, "corrupt fields rejected")
	check(restored.get_transform(panel, canvas).is_equal_approx(bounded), "corrupt config preserves state")
	DirAccess.remove_absolute(path)
	restored.reset()
	check(restored.get_transform(panel, canvas).is_equal_approx(initial), "reset defaults")
	print("Avatar framing: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
