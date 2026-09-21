extends SceneTree
var failures: Array[String] = []
func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ",label)
func _initialize() -> void:
	run.call_deferred()
func run() -> void:
	const SCENE := "res://scenes/ui/settings_window.tscn"
	check(ResourceLoader.exists(SCENE),"one settings window exposes both pages")
	if not failures.is_empty():
		quit(1)
		return
	var path := "user://unified-settings-%s" % Time.get_ticks_usec()
	var scope := {"server":OS.get_environment("GODOT_TEST_SERVER"),"username":"fail_once","message_token":"message-test"}
	var models = load("res://src/session/model_settings.gd").new(load("res://src/network/json_request.gd").new(),load("res://src/storage/model_store.gd").new(ClassDB.instantiate("WindowsSecurity"),path))
	root.add_child(models)
	await models.start(scope)
	var prefs = load("res://src/session/preferences_controller.gd").new(load("res://src/network/json_request.gd").new())
	var window = load(SCENE).instantiate()
	window.setup(prefs,models)
	root.add_child(window)
	await prefs.start(scope)
	window.open()
	check(not window.get_node("%Result").visible and window.get_node("%Result").text.is_empty(),"no fixed footer explanation before saving")
	var context: TextEdit = window.find_child("CustomContextField",true,false)
	context.text = "保留跨页的草稿"
	context.text_changed.emit()
	window.select_page("models")
	var name: LineEdit = window.find_child("ModelName",true,false)
	name.text = "saved-local-model"
	name.text_changed.emit(name.text)
	var params: TextEdit = window.find_child("Params",true,false)
	params.text = "["
	params.text_changed.emit()
	var result: Dictionary = await window.save_changes()
	check(window.get_node("%Result").visible,"validation failures remain visible")
	check(not result.ok and models.get_config("text-purpose").model != name.text and prefs.get_state().dirty,"invalid model prevents every write")
	window.select_page("preferences")
	check(context.text == "保留跨页的草稿","switching pages preserves drafts")
	params.text = "{}"
	params.text_changed.emit()
	result = await window.save_changes()
	check(not result.ok and models.get_config("text-purpose").model == "saved-local-model" and prefs.get_state().dirty,"partial failure retains failed page and successful model")
	check(window.is_dirty(),"partial success cannot close as fully saved")
	result = await window.save_changes()
	check(result.ok and not window.is_dirty(),"retry saves only remaining changes")
	check(window.get_node("%Result").visible,"successful save remains visible")
	context.text = "close guard"
	context.text_changed.emit()
	await process_frame
	await process_frame
	check(not window.get_node("%Result").visible,"editing clears stale save-success feedback")
	window.close_requested.emit()
	var dialog: Window = window.get_node("%UnsavedDialog")
	check(dialog.visible,"dirty close opens a decision")
	check(dialog.get_node("%SaveAndClose") is Button,"save-and-close control is authored in scene")
	dialog.get_node("%CloseDecision").pressed.emit()
	check(not dialog.visible and window.is_dirty(),"dialog close cancels without losing draft")
	window.close_requested.emit()
	dialog.get_cancel_button().pressed.emit()
	check(window.is_dirty(),"cancel retains edits")
	window.get_node("%SaveAll").pressed.emit()
	check(window.is_saving(),"save is tracked while awaiting server")
	window.close_requested.emit()
	await window.saving_finished
	await process_frame
	check(not is_instance_valid(window),"close while saving waits and closes only on success")
	models.queue_free()
	await process_frame
	remove_folder(path)
	print("Unified settings: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
func remove_folder(path: String) -> void:
	for folder in DirAccess.get_directories_at(path): remove_folder(path.path_join(folder))
	for file in DirAccess.get_files_at(path): DirAccess.remove_absolute(path.path_join(file))
	DirAccess.remove_absolute(path)
