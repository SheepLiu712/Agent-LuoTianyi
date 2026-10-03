extends SceneTree
var failures: Array[String] = []
func check(value: bool, label: String) -> void:
	if not value: failures.append(label); print("FAIL: ",label)
func _initialize() -> void:
	run.call_deferred()
func run() -> void:
	var app = load("res://scenes/main.tscn").instantiate()
	app.password_encryption = load("res://src/platform/password_encryption.gd").new()
	var directory := "user://missing-encryption-%s" % Time.get_ticks_usec()
	app.setup(null,directory + "/layout.cfg")
	root.add_child(app)
	await process_frame
	check(app.get_node("%SecurityError").visible, "missing encryption blocks authentication explicitly")
	app.get_node("%AccountForm").log_requested.emit()
	var logs: Array = app.get_children().filter(func(node): return node is Window and node.title.begins_with("客户端日志"))
	check(logs.size() == 1 and logs[0].visible, "diagnostics remain available without authentication")
	app.queue_free()
	await process_frame
	for name in DirAccess.get_files_at(directory.path_join("logs")):
		DirAccess.remove_absolute(directory.path_join("logs").path_join(name))
	DirAccess.remove_absolute(directory.path_join("logs"))
	for name in DirAccess.get_files_at(directory): DirAccess.remove_absolute(directory.path_join(name))
	DirAccess.remove_absolute(directory)
	var panel = load("res://scenes/avatar/avatar_panel.tscn").instantiate()
	panel.get_node("%Driver").set_script(load("res://src/avatar/avatar_driver.gd"))
	root.add_child(panel)
	await process_frame
	check(not panel.avatar.get_status().loaded and not panel.get_node("%Error").text.is_empty(), "unavailable avatar reports failure without crashing the view")
	panel.queue_free()
	await process_frame
	print("Platform degradation: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
