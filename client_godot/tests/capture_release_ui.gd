extends SceneTree
const APP_SCENE := "res://scenes/main.tscn"
var failures: Array[String] = []
func _initialize() -> void:
	_run.call_deferred()
func _run() -> void:
	if DisplayServer.get_name() == "headless":
		quit(2)
		return
	if not ResourceLoader.exists(APP_SCENE):
		print("Release screenshots: ","FAIL: missing application scene")
		quit(1)
		return
	var directory := "user://release-visual-%s"%Time.get_ticks_usec()
	DirAccess.make_dir_recursive_absolute(directory)
	var security = ClassDB.instantiate("WindowsSecurity")
	var account = load("res://src/session/account_session.gd").new(load("res://src/network/account_api.gd").new(security), load("res://src/storage/godot_storage_service.gd").new(directory+"/account.cfg", load("res://src/storage/credential_store.gd").new(security,directory+"/tokens")))
	var app = load(APP_SCENE).instantiate()
	app.setup(account,directory+"/window.cfg")
	root.add_child(app)
	app.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	await create_timer(.4).timeout
	await capture(root,"agentluo-011-login")
	await account.perform("login",OS.get_environment("GODOT_TEST_SERVER"),{"username":"visual","password":"synthetic","request_token":false},false)
	await create_timer(.5).timeout
	var chat = app.find_child("ChatView",true,false)
	chat.get_node("%Input").text = "今天忙了一整天，终于可以休息一下了。"
	chat.get_node("%Send").pressed.emit()
	await create_timer(2.8).timeout
	await capture(root,"agentluo-redesign-chat")
	var was_on_top := root.always_on_top
	root.always_on_top = true
	root.grab_focus()
	await create_timer(0.1).timeout
	var screenshot_output: Array = []
	var screenshot_code := OS.execute(OS.get_environment("GODOT_TEST_PYTHON"),[ProjectSettings.globalize_path("res://tests/capture_native_window.py"),str(DisplayServer.window_get_native_handle(DisplayServer.WINDOW_HANDLE,root.get_window_id())),str(OS.get_process_id()),ProjectSettings.globalize_path("res://artifacts/agentluo-native-frame.png")],screenshot_output,true)
	root.always_on_top = was_on_top
	if screenshot_code != 0: failures.append("native frame screenshot: " + str(screenshot_output))
	await profile(root,"glass")
	var glass_nodes: Array[Node] = app.find_children("*","ColorRect",true,false).filter(func(n): return n.get_script() != null and n.get_script().resource_path == "res://src/ui/frost_surface.gd")
	var materials: Array = []
	for node in glass_nodes:
		materials.append(node.material)
		node.material = null
	await profile(root,"solid")
	for index in glass_nodes.size(): glass_nodes[index].material = materials[index]
	for factor in [1.25,1.5,2.0]:
		root.content_scale_mode = Window.CONTENT_SCALE_MODE_CANVAS_ITEMS
		root.content_scale_factor = factor
		root.size = Vector2i(Vector2(1200,800)*factor)
		await capture(root,"agentluo-redesign-chat-scale-%s" % int(factor*100))
	root.content_scale_factor = 1
	root.size = Vector2i(960,640)
	await capture(root,"agentluo-redesign-chat-minimum")
	root.size = Vector2i(1200,800)
	for item in [["logs","客户端日志","logs"],["preferences","设置","preferences"],["models","设置","models"]]:
		app.get_node("%NavLogs" if item[0] == "logs" else "%NavSettings").pressed.emit()
		await create_timer(.4).timeout
		var windows: Array = app.find_children("*","Window",true,false).filter(func(n): return n.title.begins_with(item[1]))
		if windows.is_empty():
			failures.append("window missing: "+item[1])
			continue
		if item[0] != "logs":
			windows[0].get_node("%ModelsTab" if item[0] == "models" else "%PreferencesTab").pressed.emit()
		await capture(windows[0],"agentluo-011-"+item[2])
		windows[0].hide()
	var dynamics: Array = app.find_children("*","Button",true,false).filter(func(n): return n.text.begins_with("动态 ·"))
	dynamics[0].pressed.emit()
	await create_timer(.4).timeout
	var window: Window = app.find_children("*","Window",true,false).filter(func(n): return n.title == "天依的动态")[0]
	window.select_post("visual-post")
	await create_timer(.3).timeout
	await capture(window,"agentluo-011-dynamics")
	for factor in [1.25,1.5]:
		window.content_scale_mode = Window.CONTENT_SCALE_MODE_CANVAS_ITEMS
		window.content_scale_factor = factor
		window.size = Vector2i(Vector2(1000,780)*factor)
		await capture(window,"agentluo-011-dynamics-scale-%s"%int(factor*100))
	window.content_scale_factor = 1
	window.size = Vector2i(1000,780)
	app.get_node("%NavLogs").pressed.emit()
	app.get_node("%NavSettings").pressed.emit()
	var logs: Window = app.find_child("LogWindow",true,false)
	var settings: Window = app.find_child("SettingsWindow",true,false)
	var settings_handle := DisplayServer.window_get_native_handle(DisplayServer.WINDOW_HANDLE,settings.get_window_id())
	root.mode = Window.MODE_MINIMIZED
	await create_timer(.3).timeout
	var native_output: Array = []
	var native_code := OS.execute(OS.get_environment("GODOT_TEST_PYTHON"),[ProjectSettings.globalize_path("res://tests/verify_native_relationships.py"),str(DisplayServer.window_get_native_handle(DisplayServer.WINDOW_HANDLE,root.get_window_id())),str(DisplayServer.window_get_native_handle(DisplayServer.WINDOW_HANDLE,window.get_window_id())),str(DisplayServer.window_get_native_handle(DisplayServer.WINDOW_HANDLE,logs.get_window_id())),str(settings_handle)],native_output,true)
	print(native_output)
	if native_code != 0: failures.append("native window relationships")
	app.get_node("%Chrome").open_window()
	await create_timer(.2).timeout
	if not settings.visible: failures.append("settings returns with main window")
	app.queue_free()
	await process_frame
	remove_folder(directory)
	print("Release screenshots: ","PASS" if failures.is_empty() else "FAIL: "+str(failures))
	quit(0 if failures.is_empty() else 1)

func profile(window: Window, suffix: String) -> void:
	window.grab_focus()
	for index in 12: await process_frame
	var frames: Array[float] = []
	var last := Time.get_ticks_usec()
	for index in 90:
		await process_frame
		var now := Time.get_ticks_usec()
		frames.append((now-last)/1000.0)
		last = now
	frames.sort()
	var report := {"mode":suffix,"samples":frames.size(),"median_frame_ms":frames[frames.size()/2],"p95_frame_ms":frames[int(frames.size()*.95)],"static_memory_bytes":Performance.get_monitor(Performance.MEMORY_STATIC),"draw_calls":Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME),"viewport":str(window.size),"note":"Current GPU and content scale only; not integrated-GPU or OS DPI certification"}
	var file := FileAccess.open("res://artifacts/redesign-profile-"+suffix+".json",FileAccess.WRITE)
	file.store_string(JSON.stringify(report,"  "))
	file.close()

func capture(window: Window,name: String) -> void:
	await create_timer(.2).timeout
	await RenderingServer.frame_post_draw
	if window.get_texture().get_image().save_png("res://artifacts/"+name+".png") != OK:
		failures.append("screenshot failed: "+name)

func remove_folder(path: String) -> void:
	for folder in DirAccess.get_directories_at(path): remove_folder(path.path_join(folder))
	for filename in DirAccess.get_files_at(path): DirAccess.remove_absolute(path.path_join(filename))
	DirAccess.remove_absolute(path)
