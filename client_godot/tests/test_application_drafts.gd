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
	var session = load("res://src/session/account_session.gd").new(load("res://src/network/account_api.gd").new(security), load("res://src/storage/godot_storage_service.gd").new(path+"/account.cfg", load("res://src/storage/credential_store.gd").new(security,path+"/tokens")))
	var app = load(APP_SCENE).instantiate()
	app.setup(session,path+"/window.cfg")
	root.add_child(app)
	app.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	await process_frame
	await session.perform("login",OS.get_environment("GODOT_TEST_SERVER"),{"username":"ui","password":"synthetic-password","request_token":false},false)
	await process_frame
	check(app.get_node_or_null("%AccountMenu") == null,"main navigation no longer owns account actions")
	var dynamics = app.get_node("%NavDynamics")
	for tick in 200:
		if dynamics.text == "动态 · 99+": break
		await create_timer(.01).timeout
	check(dynamics.text == "动态 · 99+","navigation shows capped unread")
	dynamics.pressed.emit()
	await process_frame
	app.find_child("DynamicsWindow",true,false).get_node("%Publish").pressed.emit()
	await process_frame
	var draft = app.find_child("PublishDraft",true,false)
	check(draft != null,"publishing opens from dynamic navigation")
	draft.text = "unsaved dynamic"
	draft.text_changed.emit()
	app.get_node("%NavLogs").pressed.emit()
	var logs = app.find_child("LogWindow",true,false)
	app.get_node("%NavSettings").pressed.emit()
	await process_frame
	var window = app.find_child("SettingsWindow",true,false)
	check(window != null,"settings navigation opens unified window")
	check(window.get_node_or_null("%LogoutButton") is Button,"settings provides logout action")
	if window.get_node_or_null("%LogoutButton") == null:
		app.queue_free()
		await process_frame
		print("Application drafts: FAIL")
		quit(1)
		return
	window.get_node("%ModelsTab").pressed.emit()
	app.get_node("%NavSettings").pressed.emit()
	check(app.find_children("SettingsWindow","Window",true,false).size() == 1 and window.get_node("%ModelPage").visible,"reopen preserves selected settings page and singleton")
	window.get_node("%PreferencesTab").pressed.emit()
	var input: TextEdit = window.find_child("CustomContextField",true,false)
	var deadline := Time.get_ticks_msec()+2500
	while not input.editable and Time.get_ticks_msec()<deadline: await process_frame
	input.text = "new draft"
	input.text_changed.emit()
	check(window.is_dirty(),"loaded form accepts draft edit")
	var chat = app.find_child("ChatView",true,false)
	chat.get_node("%Input").text = "unsent chat draft"
	var image := Image.create(4,4,false,Image.FORMAT_RGB8)
	chat.get_node("%Input").image_pasted.emit(image)
	root.close_requested.emit()
	var dialog = app.get_node("%ExitDialog")
	check(dialog.visible and dialog.dialog_text.contains("聊天") and dialog.dialog_text.contains("设置") and dialog.dialog_text.contains("动态"),"one exit prompt summarizes every draft")
	dialog.get_cancel_button().pressed.emit()
	check(chat.is_dirty() and window.is_dirty() and draft.text == "unsaved dynamic" and chat.get_node("%AttachmentBar").visible,"cancel preserves every draft")
	window.get_node("%LogoutButton").pressed.emit()
	check(not session.get_session().is_empty() and dialog.visible,"logout waits for decision")
	dialog.get_cancel_button().pressed.emit()
	window.get_node("%LogoutButton").pressed.emit()
	dialog.get_ok_button().pressed.emit()
	await process_frame
	check(session.get_session().is_empty(),"confirmed discard completes logout")
	check(not is_instance_valid(window) and logs.visible,"logout closes business windows but preserves logs")
	await session.perform("login",OS.get_environment("GODOT_TEST_SERVER"),{"username":"slow_save","password":"synthetic-password","request_token":false},false)
	app.get_node("%NavSettings").pressed.emit()
	window = app.find_child("SettingsWindow",true,false)
	input = window.find_child("CustomContextField",true,false)
	deadline = Time.get_ticks_msec()+2500
	while not input.editable and Time.get_ticks_msec()<deadline: await process_frame
	check(not app.find_child("ChatView",true,false).is_dirty(),"relogin does not restore prior text or image drafts")
	input.text = "save before logout"
	input.text_changed.emit()
	window.get_node("%SaveAll").pressed.emit()
	check(window.is_saving() and window.get_node("%Result").visible,"save exposes processing feedback")
	window.get_node("%LogoutButton").pressed.emit()
	check(not session.get_session().is_empty(),"logout waits for an in-flight save")
	deadline = Time.get_ticks_msec()+3000
	while not session.get_session().is_empty() and Time.get_ticks_msec()<deadline: await process_frame
	await process_frame
	check(session.get_session().is_empty() and not is_instance_valid(window) and logs.visible,"completed save permits logout and keeps logs")
	app.queue_free()
	await process_frame
	remove_folder(path)
	print("Application drafts: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
func remove_folder(path: String) -> void:
	for folder in DirAccess.get_directories_at(path): remove_folder(path.path_join(folder))
	for file in DirAccess.get_files_at(path): DirAccess.remove_absolute(path.path_join(file))
	DirAccess.remove_absolute(path)
