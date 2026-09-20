extends SceneTree
const APP_SCENE := "res://scenes/main.tscn"
var failures: Array[String] = []
func check(value: bool,text: String) -> void:
	if not value:
		failures.append(text)
		print("FAIL: ",text)
func _initialize() -> void:
	_run.call_deferred()
func _run() -> void:
	check(ResourceLoader.exists(APP_SCENE),"application scene exists")
	if not ResourceLoader.exists(APP_SCENE):
		print("Application drafts: ","FAIL")
		quit(1)
		return
	var path := "user://draft-app-test-%s"%Time.get_ticks_usec()
	DirAccess.make_dir_recursive_absolute(path)
	var security = ClassDB.instantiate("WindowsSecurity")
	var session = load("res://src/session/account_session.gd").new(load("res://src/network/account_api.gd").new(security),load("res://src/storage/credential_store.gd").new(security,path+"/tokens"),path+"/account.cfg")
	var app = load(APP_SCENE).instantiate()
	app.setup(session,path+"/window.cfg")
	root.add_child(app)
	app.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	await process_frame
	await session.perform("login",OS.get_environment("GODOT_TEST_SERVER"),{"username":"ui","password":"synthetic-password","request_token":false},false)
	await process_frame
	var menu = app.find_child("ChatMore",true,false)
	check(menu.get_items().any(func(item): return item.get("id") == "preferences"),"chat menu exposes preferences")
	var dynamics: Array = []
	for tick in 200:
		dynamics = app.find_children("*","Button",true,false).filter(func(n): return n.text == "动态 · 99+")
		if not dynamics.is_empty():
			break
		await create_timer(.01).timeout
	check(dynamics.size()==1,"permanent dynamics button displays capped unread")
	if not dynamics.is_empty():
		dynamics[0].pressed.emit()
		await process_frame
		for button in app.find_children("*","Button",true,false):
			if button.text == "发布动态": button.pressed.emit()
		await process_frame
		var draft = app.find_child("PublishDraft",true,false)
		check(draft != null,"dynamics opens from chat")
		if draft != null:
			draft.text = "unsaved dynamic"
			draft.text_changed.emit()
	menu.activated.emit("models")
	await process_frame
	check(app.find_children("*","Window",true,false).filter(func(n): return n.title == "LLM / VLM 模型设置").size()==1,"model menu opens shared settings")
	if menu.get_items().any(func(item): return item.get("id") == "preferences"):
		menu.activated.emit("preferences")
		await create_timer(.15).timeout
		var windows: Array = app.find_children("*","Window",true,false).filter(func(n): return n.title == "相处模式")
		check(windows.size()==1,"preferences opens independent window")
		if windows.size()==1:
			menu.activated.emit("preferences")
			check(app.find_children("*","Window",true,false).filter(func(n): return n.title == "相处模式").size()==1,"repeated open focuses same window")
			var input: TextEdit = windows[0].find_children("*","TextEdit",true,false)[0]
			var deadline := Time.get_ticks_msec()+2500
			while not input.editable and Time.get_ticks_msec()<deadline:
				await process_frame
			input.text = "new draft"
			input.text_changed.emit()
			check(windows[0].is_dirty(),"loaded form accepts draft edit")
			root.close_requested.emit()
			var dialogs: Array = app.find_children("*","ConfirmationDialog",true,false).filter(func(n): return n.visible)
			check(not dialogs.is_empty(),"app exit asks before discarding settings")
			if not dialogs.is_empty():
				dialogs[0].get_cancel_button().pressed.emit()
			menu.activated.emit("logout")
			dialogs = app.find_children("*","ConfirmationDialog",true,false).filter(func(n): return n.visible)
			check(not session.get_session().is_empty() and not dialogs.is_empty(),"logout waits for draft decision")
			if not dialogs.is_empty():
				dialogs[0].get_cancel_button().pressed.emit()
				check(windows[0].is_dirty(),"default cancel retains sensitive drafts")
				menu.activated.emit("logout")
				dialogs[0].get_ok_button().pressed.emit()
				await process_frame
				check(session.get_session().is_empty(),"confirmed discard completes logout")
	app.queue_free()
	await process_frame
	for folder in ["logs","reading"]:
		if not DirAccess.dir_exists_absolute(path+"/"+folder):
			continue
		for file in DirAccess.get_files_at(path+"/"+folder):
			DirAccess.remove_absolute(path+"/"+folder+"/"+file)
		DirAccess.remove_absolute(path+"/"+folder)
	for file in DirAccess.get_files_at(path):
		DirAccess.remove_absolute(path+"/"+file)
	DirAccess.remove_absolute(path)
	print("Application drafts: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
