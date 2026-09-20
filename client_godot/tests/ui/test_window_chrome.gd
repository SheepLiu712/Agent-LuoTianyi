extends SceneTree
var failures: Array[String] = []
func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)
func _initialize() -> void:
	run.call_deferred()
func run() -> void:
	auto_accept_quit = false
	const SCENE := "res://scenes/ui/window_chrome.tscn"
	check(ResourceLoader.exists(SCENE), "shared window frame is available")
	if not failures.is_empty():
		quit(1)
		return
	var frame = load(SCENE).instantiate()
	root.add_child(frame)
	await process_frame
	var closed: Array[bool] = []
	root.close_requested.connect(func(): closed.append(true))
	if DisplayServer.get_name() != "headless":
		check(not root.borderless, "host uses the system title bar and window controls")
	check(frame.get_node_or_null("TitleBar") == null, "superseded custom controls are removed")
	root.close_requested.emit()
	check(closed == [true], "system close routes to host close request")
	var storage = load("res://src/storage/window_geometry.gd").new("user://window-frame-test-%s.cfg" % Time.get_ticks_usec())
	var screens: Array[Rect2i] = [Rect2i(0,0,1280,800), Rect2i(-1920,0,1920,1080)]
	check(storage.write_layout("main",Rect2i(4000,3000,1000,700),true) == OK, "geometry saves")
	check(storage.write_layout("logs",Rect2i(-1500,80,800,600),false) == OK, "other window saves")
	var loaded: Dictionary = storage.read_layout("main",Rect2i(0,0,660,800),Vector2i(480,640),screens)
	check(loaded.rect == Rect2i(280,100,1000,700) and loaded.maximized, "offscreen geometry clamps and preserves maximized")
	loaded = storage.read_layout("logs",Rect2i(0,0,660,800),Vector2i(480,400),screens)
	check(loaded.rect == Rect2i(-1500,80,800,600) and not loaded.maximized, "negative monitor coordinates and other keys survive")
	DirAccess.remove_absolute(storage.path)
	frame.queue_free()
	await process_frame
	print("Window chrome: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
