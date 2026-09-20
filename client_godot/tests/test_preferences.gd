extends SceneTree
var failures: Array[String] = []
func check(value: bool,text: String) -> void:
	if not value:
		failures.append(text)
		print("FAIL: ",text)
func _initialize() -> void:
	_run.call_deferred()
func scope(user: String) -> Dictionary:
	return {"server":OS.get_environment("GODOT_TEST_SERVER"),"username":user,"message_token":"message-test"}
func _run() -> void:
	check(ResourceLoader.exists("res://src/session/preferences_controller.gd"),"preferences load and merge boundary exists")
	if not failures.is_empty():
		quit(1)
		return
	var controller = load("res://src/session/preferences_controller.gd").new(load("res://src/network/json_request.gd").new())
	root.add_child(controller)
	await controller.start(scope("merge"))
	var state: Dictionary = controller.get_state()
	check(state.phase == "ready" and state.fields.personality_text == "真诚，安静","canonical personality wins over legacy field")
	var fields: Dictionary = state.fields.duplicate()
	fields.relationship = "朋友"
	fields.personality_text = "温柔,认真、活泼\n诚实， "
	controller.edit(fields)
	check(controller.get_state().dirty and controller.get_state().can_save,"editing loaded form enables save")
	await controller.save()
	state = controller.get_state()
	check(state.code == "OK" and not state.dirty and state.fields.speaking_style == "文静恬淡","merge preserves latest unedited fields")
	await controller.start(scope("legacy"))
	check(controller.get_state().fields.personality_text == "开朗，认真","legacy trait field remains readable")
	await controller.start(scope("fail_load"))
	controller.edit({"relationship":"家人"})
	await controller.save()
	check(not controller.get_state().can_save,"failed read cannot overwrite preferences")
	await controller.start(scope("fail_save"))
	fields = controller.get_state().fields.duplicate()
	fields.custom_context = "retain draft"
	controller.edit(fields)
	await controller.save()
	check(controller.get_state().dirty and controller.get_state().fields.custom_context == "retain draft","write error preserves draft")
	check(ResourceLoader.exists("res://scenes/ui/preferences_window.tscn"),"preference window exposes draft protection")
	if ResourceLoader.exists("res://scenes/ui/preferences_window.tscn"):
		var window_controller = load("res://src/session/preferences_controller.gd").new(load("res://src/network/json_request.gd").new())
		var window = load("res://scenes/ui/preferences_window.tscn").instantiate()
		window.setup(window_controller)
		root.add_child(window)
		await window_controller.start(scope("ui"))
		window_controller.edit({"custom_context":"window draft"})
		window.open()
		window.close_requested.emit()
		var dialogs: Array = window.find_children("*","ConfirmationDialog",true,false)
		check(not dialogs.is_empty() and dialogs[0].visible,"dirty window asks before closing")
		if not dialogs.is_empty():
			dialogs[0].canceled.emit()
			check(is_instance_valid(window) and window_controller.get_state().dirty,"cancel keeps window draft")
		window.queue_free()
		await process_frame
	controller.stop()
	check(not controller.get_state().dirty and controller.get_state().phase == "idle","logout clears draft and state")
	controller.queue_free()
	await process_frame
	print("Preferences: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
