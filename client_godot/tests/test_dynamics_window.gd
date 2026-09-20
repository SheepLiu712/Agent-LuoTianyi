extends SceneTree
var failures: Array[String] = []
func check(value: bool,text: String) -> void:
	if not value:
		failures.append(text)
		print("FAIL: ",text)
func _initialize() -> void:
	_run.call_deferred()
func _run() -> void:
	if not ResourceLoader.exists("res://scenes/ui/dynamics_window.tscn"):
		check(false,"dynamics window scene exists")
		quit(1)
		return
	var controller = load("res://src/session/dynamics_controller.gd").new()
	root.add_child(controller)
	var scope := {"server":OS.get_environment("GODOT_TEST_SERVER"),"username":"write","message_token":"fixture-token"}
	await controller.start(scope)
	await controller.refresh()
	await controller.load_comments("d0")
	check((await controller.publish("published text")).ok,"text publishing succeeds")
	check(controller.get_posts()[0].content == "published text","published item displayed")
	check((await controller.comment("d0","reply text","c0")).ok,"reply succeeds")
	check(controller.get_comments("d0").items[-1].parent_comment_id == "c0","reply target preserved")
	await controller.load_comments("d0",true)
	check(controller.get_comments("d0").items[-1].id == "c99","older page remains before new comment")
	check(not (await controller.comment("d1","forbidden")).ok,"read-only post refuses comment")
	check(not (await controller.comment("d0","wrong parent","missing")).ok,"unknown reply target refused")
	scope.username = "fail-write"
	await controller.start(scope)
	await controller.refresh()
	var layout_path := "user://dynamics-window-test-%s.cfg"%Time.get_ticks_usec()
	var window = load("res://scenes/ui/dynamics_window.tscn").instantiate()
	window.setup(controller,layout_path)
	root.add_child(window)
	window.open()
	await process_frame
	for button in window.find_children("*","Button",true,false):
		if button.text == "发布动态": button.pressed.emit()
	await process_frame
	var draft = window.find_child("PublishDraft",true,false)
	var send = window.find_child("PublishButton",true,false)
	check(draft != null and send != null,"publish controls visible")
	if draft != null:
		draft.text = "keep my draft"
		draft.text_changed.emit()
		send.pressed.emit()
		await create_timer(0.2).timeout
		check(draft.text == "keep my draft" and window.is_dirty(),"failed publication preserves draft")
		window.close_requested.emit()
		await process_frame
		check(is_instance_valid(window),"draft closure requires explicit confirmation")
		var statuses = window.find_children("*","Label",true,false)
		var noted := false
		for label in statuses:
			noted = noted or label.text.contains("HTTP_ERROR")
		check(noted,"publication error shown")
	window.queue_free()
	await process_frame
	check(controller.get_posts().size()==10,"window does not own application controller")
	DirAccess.remove_absolute(layout_path)
	controller.queue_free()
	await process_frame
	print("Dynamics window: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
