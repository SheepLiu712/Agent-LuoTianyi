extends SceneTree
var failures: Array[String] = []
func check(value: bool,label: String) -> void:
	if not value:
		failures.append(label)
		print("FAIL: ",label)
func _initialize() -> void:
	_run.call_deferred()
func _run() -> void:
	await test_details()
	await test_publish_failure()
	print("Dynamics detail: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func test_details() -> void:
	var controller = load("res://src/session/dynamics_controller.gd").new()
	root.add_child(controller)
	await controller.start({"server":OS.get_environment("GODOT_TEST_SERVER"),"username":"detail","message_token":"fixture-token"})
	await controller.refresh()
	if not ResourceLoader.exists("res://scenes/ui/dynamics_window.tscn"):
		check(false,"dynamics window scene exists")
		controller.queue_free()
		await process_frame
		quit(1)
		return
	var layout_path := "user://detail-test-%s.cfg" % Time.get_ticks_usec()
	var scene: PackedScene = load("res://scenes/ui/dynamics_window.tscn")
	var window = scene.instantiate()
	window.setup(controller,layout_path)
	root.add_child(window)
	window.open()
	await process_frame
	if not window.has_method("select_post"):
		check(false,"two-pane selection available")
		controller.queue_free()
		await process_frame
		quit(1)
		return
	check(window.get_selected_id().is_empty(),"opening has no selection")
	check(window.select_post("d0"),"select known post")
	await create_timer(.15).timeout
	var draft = window.find_child("CommentDraft",true,false)
	draft.text = "ordinary draft"
	check(window.is_dirty(),"comment draft counted")
	window.select_post("d1")
	for input in window.find_children("CommentDraft","TextEdit",true,false):
		if input.is_visible_in_tree(): check(not input.editable,"read-only dynamic disables input")
	window.select_post("d0")
	check(draft.text == "ordinary draft" and draft.is_visible_in_tree(),"switch preserves correct draft")
	check(not window.select_post("missing") and window.get_selected_id()=="d0","unknown selection cannot clear current detail")
	var active = window.find_children("*","ScrollContainer",true,false).filter(func(n): return n.has_method("update_comments") and n.is_visible_in_tree())[0]
	await process_frame
	active.scroll_vertical = 140
	await process_frame
	window.select_post("d1")
	await process_frame
	window.select_post("d0")
	await process_frame
	check(active.scroll_vertical==140,"per-post reading position restored")
	active.scroll_vertical = 100000
	await create_timer(.15).timeout
	check(controller.get_comments("d0").items.size()==22,"scrolling detail to bottom loads next comment page")
	for scroll in window.find_children("*","ScrollContainer",true,false):
		if not scroll.has_method("update_comments"): scroll.scroll_vertical = 100000
	await create_timer(.15).timeout
	check(controller.get_posts().size()==12,"scrolling feed to bottom loads next post page")
	var replies = window.find_children("*","Button",true,false).filter(func(b): return b.text == "回复" and b.is_visible_in_tree())
	check(not replies.is_empty(),"explicit inline reply actions")
	if not replies.is_empty():
		replies[0].pressed.emit()
		var reply = window.find_child("ReplyDraft",true,false)
		reply.text = "reply draft"
		window.find_child("CancelReply",true,false).pressed.emit()
		check(reply.text == "reply draft" and window.is_dirty(),"cancel target keeps reply text")
	for button in window.find_children("*","Button",true,false):
		if button.text=="发布动态": button.pressed.emit()
	await process_frame
	var publish = window.find_child("PublishDraft",true,false)
	publish.text = "new post"
	window.find_child("PublishButton",true,false).pressed.emit()
	await create_timer(.2).timeout
	check(window.get_selected_id()=="d99" and window.find_child("PublishDraft",true,false)==null,"publication selects returned post and closes publisher")
	check(window.is_dirty(),"publication success preserves another post draft")
	window.select_post("d0")
	check(draft.text=="ordinary draft","prior comment survives publication")
	var split: HSplitContainer = window.find_children("*","HSplitContainer",true,false)[0]
	split.split_offset = int(split.size.x*.55)
	split.dragged.emit(split.split_offset)
	await process_frame
	window.queue_free()
	await process_frame
	var restored = scene.instantiate()
	restored.setup(controller,layout_path)
	root.add_child(restored)
	restored.open()
	await process_frame
	await process_frame
	split = restored.find_children("*","HSplitContainer",true,false)[0]
	check(absf(split.get_child(0).size.x/split.size.x-.55)<.02,"divider ratio survives new window")
	check(restored.get_selected_id().is_empty() and not restored.is_dirty(),"new window restores neither selection nor discarded drafts")
	restored.queue_free()
	await process_frame
	controller.queue_free()
	await process_frame
	DirAccess.remove_absolute(layout_path)

func test_publish_failure() -> void:
	var controller = load("res://src/session/dynamics_controller.gd").new()
	root.add_child(controller)
	await controller.start({"server":OS.get_environment("GODOT_TEST_SERVER"),"username":"fail-write","message_token":"fixture-token"})
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
		check(draft.get_window() == window,"publishing stays inside its dynamics window")
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
