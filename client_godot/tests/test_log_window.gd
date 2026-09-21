extends SceneTree
const APP_SCENE := "res://scenes/main.tscn"
const Log = preload("res://src/storage/client_log.gd")
var failures: Array[String] = []
func check(value: bool, text: String) -> void:
	if not value:
		failures.append(text)
		print("FAIL: ",text)
func _initialize() -> void:
	_run.call_deferred()
func _run() -> void:
	check(ResourceLoader.exists(APP_SCENE),"application scene exists")
	if not ResourceLoader.exists(APP_SCENE):
		print("Log window: ","FAIL")
		quit(1)
		return
	var directory := "user://log-window-test-%s" % Time.get_ticks_usec()
	DirAccess.make_dir_recursive_absolute(directory)
	var security = ClassDB.instantiate("WindowsSecurity")
	var account = load("res://src/session/account_session.gd").new(load("res://src/network/account_api.gd").new(security), load("res://src/storage/godot_storage_service.gd").new(directory+"/account.cfg", load("res://src/storage/credential_store.gd").new(security,directory+"/accounts")))
	var app = load(APP_SCENE).instantiate()
	app.setup(account,directory+"/layout.cfg")
	root.add_child(app)
	await process_frame
	app.get_node("%AccountForm").get_node("%MenuButton").pressed.emit()
	var open_button: Button = app.get_node("%AccountForm").get_node("%Logs")
	check(open_button != null,"login has open logs action")
	if open_button != null:
		open_button.pressed.emit()
		await process_frame
		var windows: Array = app.find_children("*","Window",true,false).filter(func(w): return w.title.contains("日志"))
		check(windows.size() == 1 and windows[0].visible,"one nonmodal log window opens")
		if windows.size() == 1:
			var window: Window = windows[0]
			var texts := window.find_children("*","RichTextLabel",true,false)
			check(texts.size() == 1 and texts[0].get_parsed_text().contains("客户端启动"),"late opening retains first startup entry")
			open_button.pressed.emit()
			window.close_requested.emit()
			check(not window.visible,"close hides log window")
			open_button.pressed.emit()
			check(window.visible,"reopen retains same window")
	push_warning("synthetic engine detail must not enter diagnostic archive")
	await process_frame
	await process_frame
	app.queue_free()
	await process_frame
	var observer = Log.new(directory+"/logs")
	var runs: Array = observer.list_runs() if observer.has_method("list_runs") else []
	check(runs.size() == 1 and runs[0].closed,"application exit closes startup archive")
	if runs.size() == 1:
		var data := JSON.stringify(observer.read_entries(runs[0].id))
		check(data.contains("ENGINE_WARNING") and not data.contains("synthetic engine detail"),"engine warning captured without raw details")
	var logger = Log.new(directory+"/logs")
	logger.record("client_started")
	if not ResourceLoader.exists("res://scenes/ui/log_window.tscn"):
		check(false,"log window scene available")
		logger.finish()
		quit(1)
		return
	var viewer = load("res://scenes/ui/log_window.tscn").instantiate()
	viewer.setup(logger)
	root.add_child(viewer)
	viewer.open()
	await process_frame
	await process_frame
	for control in viewer.find_children("*","Button",true,false):
		if control.has_method("get_selected_id") and control.is_visible_in_tree():
			var caption_width: float = control.get_theme_font("font").get_string_size(control.text,HORIZONTAL_ALIGNMENT_LEFT,-1,control.get_theme_font_size("font_size")).x
			check(control.size.x >= caption_width+12,"current log filter remains readable")
	logger.record("audio_received",{"frames":42})
	var output: RichTextLabel = viewer.find_children("*","RichTextLabel",true,false)[0]
	check(output.get_parsed_text().contains("42"),"visible window appends live metrics")
	var search: LineEdit = viewer.find_children("*","LineEdit",true,false).filter(func(n): return n.placeholder_text.begins_with("搜索"))[0]
	search.text = "audio_received"
	search.text_changed.emit(search.text)
	check(output.get_parsed_text().contains("audio_received") and not output.get_parsed_text().contains("client_started"),"search filters display")
	check(logger.read_entries().size() == 2,"filter does not discard archive entries")
	viewer.queue_free()
	await process_frame
	logger.finish()
	for file in DirAccess.get_files_at(directory+"/logs"):
		DirAccess.remove_absolute(directory+"/logs/"+file)
	DirAccess.remove_absolute(directory+"/logs")
	DirAccess.remove_absolute(directory)
	print("Log window: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
