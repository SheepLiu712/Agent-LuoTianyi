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
	var account = load("res://src/session/account_session.gd").new(load("res://src/network/account_api.gd").new(security),load("res://src/storage/credential_store.gd").new(security,directory+"/tokens"),directory+"/account.cfg")
	var app = load(APP_SCENE).instantiate()
	app.setup(account,directory+"/window.cfg")
	root.add_child(app)
	app.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	await create_timer(.4).timeout
	await capture(root,"agentluo-011-login")
	await account.perform("login",OS.get_environment("GODOT_TEST_SERVER"),{"username":"visual","password":"synthetic","request_token":false},false)
	await create_timer(.5).timeout
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
	app.queue_free()
	await process_frame
	for folder in ["logs","reading"]:
		if DirAccess.dir_exists_absolute(directory+"/"+folder):
			for file in DirAccess.get_files_at(directory+"/"+folder):
				DirAccess.remove_absolute(directory+"/"+folder+"/"+file)
			DirAccess.remove_absolute(directory+"/"+folder)
	for file in DirAccess.get_files_at(directory):
		DirAccess.remove_absolute(directory+"/"+file)
	DirAccess.remove_absolute(directory)
	print("Release screenshots: ","PASS" if failures.is_empty() else "FAIL: "+str(failures))
	quit(0 if failures.is_empty() else 1)

func capture(window: Window,name: String) -> void:
	await create_timer(.2).timeout
	await RenderingServer.frame_post_draw
	if window.get_texture().get_image().save_png("res://artifacts/"+name+".png") != OK:
		failures.append("screenshot failed: "+name)
