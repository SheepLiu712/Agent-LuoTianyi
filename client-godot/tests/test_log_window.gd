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
	await _check_application(directory)
	await _check_viewer(directory)
	_cleanup(directory)
	print("Log window: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func _check_application(directory: String) -> void:
	var security = ClassDB.instantiate("WindowsSecurity")
	var account = load("res://src/session/account_session.gd").new(load("res://src/network/account_api.gd").new(security), load("res://src/storage/godot_storage_service.gd").new(directory+"/account.cfg", load("res://src/storage/credential_store.gd").new(security,directory+"/accounts")))
	var app = load(APP_SCENE).instantiate()
	app.setup(account,directory+"/layout.cfg")
	root.add_child(app)
	await process_frame
	app.get_login_page().get_node("%MenuButton").pressed.emit()
	var open_button: Button = app.get_login_page().get_node("%Logs")
	check(open_button != null,"login has open logs action")
	if open_button != null:
		open_button.pressed.emit()
		await process_frame
		var windows: Array = app.find_children("*","Window",true,false).filter(func(w): return w.title.contains("日志"))
		_check_one_nonmodal_log_window_opens(windows)
		if windows.size() == 1:
			var window: Window = windows[0]
			var texts := window.find_children("*","RichTextLabel",true,false)
			_check_late_opening_retains_first_startup_entry(texts)
			open_button.pressed.emit()
			window.close_requested.emit()
			check(not window.visible,"close hides log window")
			open_button.pressed.emit()
			check(window.visible,"reopen retains same window")
	push_warning("synthetic engine detail is expected in diagnostic archive")
	await process_frame
	await process_frame
	app.queue_free()
	await process_frame
	var observer = Log.new(directory+"/logs")
	var runs: Array = observer.list_runs() if observer.has_method("list_runs") else []
	_check_application_exit_closes_startup_archive(runs)
	if runs.size() == 1:
		var data := JSON.stringify(observer.read_entries(runs[0].id))
		_check_engine_warning_captured_with_detail(data)
		check(data.contains("access_ui") and data.contains("logs"), "application access is logged")

func _check_viewer(directory: String) -> void:
	var logger = Log.new(directory+"/logs")
	logger.set_debug_enabled(true)
	logger.record("runtime_app_started", {"phase":"starting", "reason":"normal", "uptime_ms":0, "pid":1})
	if not ResourceLoader.exists("res://scenes/ui/windows/log_window.tscn"):
		check(false,"log window scene available")
		logger.finish()
		quit(1)
		return
	var viewer = load("res://scenes/ui/windows/log_window.tscn").instantiate()
	viewer.setup(logger)
	root.add_child(viewer)
	viewer.open()
	await process_frame
	await process_frame
	_check_filter_widths(viewer)
	_check_origin_filter(viewer)
	logger.log_debug("debug_audio_received",{"frames":42})
	var output: RichTextLabel = viewer.find_children("*","RichTextLabel",true,false)[0]
	check(output.get_parsed_text().contains("42"),"visible window appends live metrics")
	var search: LineEdit = viewer.find_children("*","LineEdit",true,false).filter(func(n): return n.placeholder_text.begins_with("搜索"))[0]
	search.text = "debug_audio_received"
	search.text_changed.emit(search.text)
	await create_timer(0.3).timeout
	_check_search_filters_display(output)
	check(logger.read_entries().size() == 2,"filter does not discard archive entries")
	viewer.queue_free()
	await process_frame
	logger.finish()

func _cleanup(directory: String) -> void:
	for file in DirAccess.get_files_at(directory+"/logs"):
		DirAccess.remove_absolute(directory+"/logs/"+file)
	DirAccess.remove_absolute(directory+"/logs")
	DirAccess.remove_absolute(directory)
func _check_late_opening_retains_first_startup_entry(texts: Variant) -> void:
	check(texts.size() == 1 and texts[0].get_parsed_text().contains("客户端启动"),"late opening retains first startup entry")

func _check_one_nonmodal_log_window_opens(windows: Variant) -> void:
	check(windows.size() == 1 and windows[0].visible,"one nonmodal log window opens")

func _check_engine_warning_captured_with_detail(data: Variant) -> void:
	check(data.contains("ENGINE_WARNING") and data.contains("synthetic engine detail"),"engine warning captured with sanitized detail")

func _check_application_exit_closes_startup_archive(runs: Variant) -> void:
	check(runs.size() == 1 and runs[0].closed,"application exit closes startup archive")

func _check_search_filters_display(output: Variant) -> void:
	check(output.get_parsed_text().contains("debug_audio_received") and not output.get_parsed_text().contains("runtime_app_started"),"search filters display")

func _check_filter_widths(viewer: Variant) -> void:
	for control in viewer.find_children("*","Button",true,false):
		if control.has_method("get_selected_id") and control.is_visible_in_tree():
			var caption_width: float = control.get_theme_font("font").get_string_size(control.text,HORIZONTAL_ALIGNMENT_LEFT,-1,control.get_theme_font_size("font_size")).x
			check(control.size.x >= caption_width+12,"current log filter remains readable")

func _check_origin_filter(viewer: Variant) -> void:
	var origin = viewer.get_node_or_null("%OriginDropdown")
	check(origin != null, "log window exposes a fault origin filter")
	if origin != null:
		origin.set_selected_id("client")
		check(origin.get_selected_id() == "client", "origin filter accepts a concrete value")
		origin.set_selected_id("all")
