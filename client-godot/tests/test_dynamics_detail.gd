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
	await test_pruning_and_states()
	await test_open_post_from_card()
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
	window.setup(controller,preload("res://src/storage/godot_settings_store.gd").new(layout_path))
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
	await _wait_comments(controller, "d0")
	var draft = window.find_child("CommentDraft",true,false)
	draft.text = "ordinary draft"
	check(window.is_dirty(),"comment draft counted")
	window.select_post("d1")
	for input in window.find_children("CommentDraft","TextEdit",true,false):
		if input.is_visible_in_tree(): check(not input.editable,"read-only dynamic disables input")
	window.select_post("d0")
	_check_switch_preserves_correct_draft(draft)
	_check_unknown_selection_cannot_clear_current_detail(window)
	var active = window.find_children("*","ScrollContainer",true,false).filter(func(n): return n.has_method("update_comments") and n.is_visible_in_tree())[0]
	await _wait_comments(controller, "d0")
	await _wait_until(func(): return active._pending_scroll < 0, "reading-position restore completes before setting scroll")
	check(active.get_v_scroll_bar().max_value - active.get_v_scroll_bar().page >= 140, "loaded detail has real scroll range")
	active.scroll_vertical = 140
	await process_frame
	check(active.scroll_vertical == 140, "reading position was set before switching")
	window.select_post("d1")
	await process_frame
	window.select_post("d0")
	await _wait_comments(controller, "d0")
	await _wait_until(func(): return active._pending_scroll < 0, "per-post restore is actually applied")
	check(active.scroll_vertical==140,"per-post reading position restored")
	active.scroll_vertical = 100000
	await _wait_comments(controller, "d0")
	check(controller.get_comments("d0").items.size()==22,"scrolling detail to bottom loads next comment page")
	for scroll in window.find_children("*","ScrollContainer",true,false):
		if not scroll.has_method("update_comments"): scroll.scroll_vertical = 100000
	await _wait_until(func(): return controller.get_posts().size() == 12, "feed pagination completes")
	check(controller.get_posts().size()==12,"scrolling feed to bottom loads next post page")
	var replies = window.find_children("*","Button",true,false).filter(func(b): return b.text == "回复" and b.is_visible_in_tree())
	check(not replies.is_empty(),"explicit inline reply actions")
	if not replies.is_empty():
		replies[0].pressed.emit()
		var reply = window.find_child("ReplyDraft",true,false)
		reply.text = "reply draft"
		window.find_child("CancelReply",true,false).pressed.emit()
		_check_cancel_target_keeps_reply_text(reply, window)
	for button in window.find_children("*","Button",true,false):
		if button.text=="发布动态": button.pressed.emit()
	await process_frame
	var publish = window.find_child("PublishDraft",true,false)
	publish.text = "new post"
	window.find_child("PublishButton",true,false).pressed.emit()
	await _wait_until(func(): return window.get_selected_id() == "d99", "publication completes")
	_check_publication_selects_returned_post_and_closes_publisher(window)
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
	restored.setup(controller,preload("res://src/storage/godot_settings_store.gd").new(layout_path))
	root.add_child(restored)
	restored.open()
	await process_frame
	await process_frame
	split = restored.find_children("*","HSplitContainer",true,false)[0]
	check(absf(split.get_child(0).size.x/split.size.x-.55)<.02,"divider ratio survives new window")
	_check_new_window_restores_neither_selection_nor_discarded_drafts(restored)
	restored.queue_free()
	await process_frame
	controller.queue_free()
	await process_frame
	DirAccess.remove_absolute(layout_path)
## 服务端删除动态后刷新：行、详情与选中一起消失；四种状态互斥。
func test_pruning_and_states() -> void:
	var controller = load("res://src/session/dynamics_controller.gd").new()
	root.add_child(controller)
	await controller.start({"server":OS.get_environment("GODOT_TEST_SERVER"),"username":"shrinking","message_token":"fixture-token"})
	await controller.refresh()
	var window = _open_dynamics_window(controller)
	await process_frame
	check(window.select_post("d5"),"select the post that will be deleted")
	await process_frame
	var before := _detail_count(window)
	await controller.refresh()
	await process_frame
	check(_row_ids(window) == ["Post_d0"],"refresh removes rows the server no longer returns")
	check(_detail_count(window) < before,"refresh releases the removed detail")
	check(window.get_selected_id().is_empty(),"refresh clears a removed selection")
	check(window.get_node("%Empty").visible,"empty selection shows guidance instead of a stale detail")
	window.queue_free()
	await process_frame
	await _check_empty_and_failure_placeholders()
	controller.queue_free()
	await process_frame


func _check_empty_and_failure_placeholders() -> void:
	var empty_feed = load("res://src/session/dynamics_controller.gd").new()
	root.add_child(empty_feed)
	await empty_feed.start({"server":OS.get_environment("GODOT_TEST_SERVER"),"username":"empty-feed","message_token":"fixture-token"})
	await empty_feed.refresh()
	var empty_window = _open_dynamics_window(empty_feed)
	await process_frame
	check(empty_window.get_node("%Empty").text.contains("还没有动态"),"empty feed states are not disguised as an error")
	check(not empty_window.get_node("%Refresh").disabled,"empty feed keeps retry available")
	empty_window.queue_free()
	empty_feed.queue_free()
	await process_frame
	var failing = load("res://src/session/dynamics_controller.gd").new()
	root.add_child(failing)
	await failing.start({"server":OS.get_environment("GODOT_TEST_SERVER"),"username":"fail-first-page","message_token":"fixture-token"})
	await failing.refresh()
	check(failing.get_state().phase == "failed","first page failure is reported as failed")
	var failing_window = _open_dynamics_window(failing)
	await process_frame
	check(failing_window.get_node("%Empty").text.contains("失败"),"failure placeholder explains the state")
	check(not failing_window.get_node("%Refresh").disabled,"failure keeps an explicit retry action")
	failing_window.queue_free()
	failing.queue_free()
	await process_frame

## 角色卡片只带预览快照：确认它能选中详情、清空预览且不会把删除条目当成成功。
func test_open_post_from_card() -> void:
	var controller = load("res://src/session/dynamics_controller.gd").new()
	root.add_child(controller)
	var scope := {"server":OS.get_environment("GODOT_TEST_SERVER"),"username":"detail","message_token":"fixture-token"}
	await controller.start(scope)
	var preview: Dictionary = controller.get_latest_unread()
	check(not preview.is_empty(),"card preview fetched")
	controller.dismiss_preview("other")
	check(not controller.get_latest_unread().is_empty(),"dismiss ignores another dynamic")
	controller.dismiss_preview(str(preview.id))
	check(controller.get_latest_unread().is_empty() and controller.get_state().unread == 123,"dismiss hides card without marking read")
	await controller.start(scope)
	preview = controller.get_latest_unread()
	await controller.refresh()
	var window = _open_dynamics_window(controller)
	await process_frame
	var opened: bool = await window.open_post(preview)
	check(opened,"card opens its dynamic")
	check(window.get_selected_id() == str(preview.id),"card selection matches preview")
	check(controller.get_latest_unread().is_empty(),"opening card clears preview")
	var deleted := preview.duplicate(true)
	deleted.id = "deleted-post"
	var deleted_opened: bool = await window.open_post(deleted)
	check(not deleted_opened,"missing dynamic reports failure")
	window.queue_free()
	await process_frame
	controller.queue_free()
	await process_frame


func _open_dynamics_window(controller: Node) -> Node:
	var layout_path := "user://dynamics-states-%s.cfg" % Time.get_ticks_usec()
	var window = load("res://scenes/ui/dynamics_window.tscn").instantiate()
	window.setup(controller,preload("res://src/storage/godot_settings_store.gd").new(layout_path))
	root.add_child(window)
	window.open()
	return window


func _row_ids(window: Node) -> Array:
	return window.get_node("%List").get_children().map(func(row): return str(row.name))


func _detail_count(window: Node) -> int:
	return window.get_node("%Right").get_children().size()


func _wait_until(condition: Callable, label: String) -> void:
	var deadline := Time.get_ticks_msec() + 5000
	while not condition.call() and Time.get_ticks_msec() < deadline:
		await process_frame
	check(condition.call(), label)
	for frame in 4: await process_frame

func _wait_comments(controller: Node, id: String) -> void:
	await _wait_until(func():
		var state: Dictionary = controller.get_comments(id)
		return state.loaded and not state.busy, "comments loaded before reading-position checks")

func test_publish_failure() -> void:
	var controller = load("res://src/session/dynamics_controller.gd").new()
	root.add_child(controller)
	await controller.start({"server":OS.get_environment("GODOT_TEST_SERVER"),"username":"fail-write","message_token":"fixture-token"})
	await controller.refresh()
	var layout_path := "user://dynamics-window-test-%s.cfg"%Time.get_ticks_usec()
	var window = load("res://scenes/ui/dynamics_window.tscn").instantiate()
	window.setup(controller,preload("res://src/storage/godot_settings_store.gd").new(layout_path))
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

func _check_cancel_target_keeps_reply_text(reply: Variant, window: Variant) -> void:
	check(reply.text == "reply draft" and window.is_dirty(),"cancel target keeps reply text")

func _check_switch_preserves_correct_draft(draft: Variant) -> void:
	check(draft.text == "ordinary draft" and draft.is_visible_in_tree(),"switch preserves correct draft")

func _check_unknown_selection_cannot_clear_current_detail(window: Variant) -> void:
	check(not window.select_post("missing") and window.get_selected_id()=="d0","unknown selection cannot clear current detail")

func _check_publication_selects_returned_post_and_closes_publisher(window: Variant) -> void:
	check(window.get_selected_id()=="d99" and window.find_child("PublishDraft",true,false)==null,"publication selects returned post and closes publisher")

func _check_new_window_restores_neither_selection_nor_discarded_drafts(restored: Variant) -> void:
	check(restored.get_selected_id().is_empty() and not restored.is_dirty(),"new window restores neither selection nor discarded drafts")
