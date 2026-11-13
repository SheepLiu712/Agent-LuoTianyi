extends SceneTree
var failures: Array[String] = []
func _initialize() -> void: run.call_deferred()
func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)
func run() -> void:
	for username in ["detail", "fail-write", "uncertain-write"]:
		var controller = load("res://src/session/dynamics_controller.gd").new()
		root.add_child(controller)
		await controller.start({"server":OS.get_environment("GODOT_TEST_SERVER"),"username":username,"message_token":"fixture-token"})
		await controller.refresh()
		var detail = load("res://scenes/ui/dynamics/dynamic_detail.tscn").instantiate()
		detail.setup(controller, controller.get_posts()[0])
		root.add_child(detail)
		check(detail.find_child("CommentTitle",true,false) == null, "redundant comment heading is removed")
		detail.get_node("%CommentDraft").text = "feedback fixture"
		detail.get_node("%Send").pressed.emit()
		var deadline := Time.get_ticks_msec()+3000
		while detail.get_node("%Send").disabled and Time.get_ticks_msec()<deadline: await process_frame
		var status: Label = detail.get_node("%Status")
		var error_dialog := _error_dialog()
		if username == "detail":
			check(detail.get_node("%CommentDraft").text.is_empty() and not status.visible, "success clears draft without status text or space")
			check(controller.get_comments("d0").items.any(func(item): return item.content == "feedback fixture"), "posted comment remains visible in the list")
		else:
			_check_failed_or_uncertain_writes_retain_visible_feedback_and_draft(error_dialog, detail)
			if username == "uncertain-write": check(error_dialog != null and error_dialog.get_current_text().contains("不确定"), "uncertain delivery is not shown as success")
			_dismiss_error(error_dialog)
		detail.queue_free()
		controller.queue_free()
		await process_frame
	print("Comment feedback: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func _dismiss_error(dialog: Node) -> void:
	if dialog != null and dialog.visible:
		dialog.get_node("%ErrorConfirm").pressed.emit()

func _error_dialog() -> Node:
	for child in root.find_children("*", "", true, false):
		if child.is_in_group("error_dialog"):
			return child
	return null

func _check_failed_or_uncertain_writes_retain_visible_feedback_and_draft(dialog: Variant, detail: Variant) -> void:
	check(dialog != null and dialog.visible and dialog.get_current_text().contains("草稿已保留") and not detail.get_node("%CommentDraft").text.is_empty(), "failed or uncertain writes retain visible feedback and draft")
