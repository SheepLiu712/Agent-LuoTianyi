extends SceneTree
var close_requests := 0
func _initialize() -> void:
	run.call_deferred()
func run() -> void:
	if DisplayServer.get_name() == "headless" or OS.get_environment("GODOT_TEST_PYTHON").is_empty():
		print("Requires a graphical Windows session and GODOT_TEST_PYTHON")
		quit(2)
		return
	auto_accept_quit = false
	root.title = "天依 · 原生窗口交互验收"
	root.always_on_top = true
	root.min_size = Vector2i(480,360)
	root.size = Vector2i(800,600)
	root.add_child(load("res://scenes/ui/window_chrome.tscn").instantiate())
	root.close_requested.connect(func(): close_requests += 1)
	await create_timer(.3).timeout
	root.grab_focus()
	var result_path := "res://artifacts/native-window-controls.json"
	DirAccess.remove_absolute(result_path)
	var pid := OS.create_process(OS.get_environment("GODOT_TEST_PYTHON"),[ProjectSettings.globalize_path("res://tests/drive_native_window.py"),str(DisplayServer.window_get_native_handle(DisplayServer.WINDOW_HANDLE,root.get_window_id())),str(OS.get_process_id()),ProjectSettings.globalize_path(result_path)],false)
	var deadline := Time.get_ticks_msec()+30000
	while not FileAccess.file_exists(result_path) and Time.get_ticks_msec() < deadline:
		await create_timer(.05).timeout
	if not FileAccess.file_exists(result_path):
		if pid > 0 and OS.is_process_running(pid): OS.kill(pid)
		print("Native window controls: FAIL timeout")
		quit(1)
		return
	var result: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(result_path))
	await process_frame
	result["close_requests"] = close_requests
	result["ok"] = result.ok and close_requests == 2
	var file := FileAccess.open(result_path,FileAccess.WRITE)
	file.store_string(JSON.stringify(result,"  "))
	file.close()
	print(result)
	print("Native window controls: ","PASS" if result.ok else "FAIL")
	quit(0 if result.ok else 1)
