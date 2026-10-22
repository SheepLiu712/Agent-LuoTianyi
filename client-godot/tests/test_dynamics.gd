extends SceneTree
var failures: Array[String] = []
func check(value: bool,text: String) -> void:
	if not value:
		failures.append(text)
		print("FAIL: ",text)
func _initialize() -> void:
	_run.call_deferred()
func _run() -> void:
	await test_reads()
	await test_writes()
	print("Dynamics: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func test_reads() -> void:
	if not ResourceLoader.exists("res://src/session/dynamics_controller.gd"):
		check(false,"dynamics controller available")
		quit(1)
		return
	var controller = load("res://src/session/dynamics_controller.gd").new()
	root.add_child(controller)
	var scope := {"server":OS.get_environment("GODOT_TEST_SERVER"),"username":"read","message_token":"fixture-token"}
	await controller.start(scope)
	check(controller.get_state().unread==123,"initial unread query")
	check(controller.get_latest_unread().get("id") == "d0", "latest unread dynamic is fetched without opening the window")
	check(controller.get_posts().is_empty(), "preview does not preselect or mutate the window list")
	var preview: Dictionary = controller.get_latest_unread()
	preview.content = "mutated"
	check(controller.get_latest_unread().content != "mutated", "unread preview snapshots are independent")
	await controller.refresh()
	_check_reading_ten_posts_does_not_clear_unread(controller)
	await controller.load_more()
	_check_opaque_cursor_paging_deduplicates_posts(controller)
	await controller.load_comments("d0")
	check(controller.get_comments("d0").items.size()==20,"comments first twenty")
	if not controller.has_method("refresh_comments"):
		check(false,"complete comment refresh available")
		controller.queue_free()
		await process_frame
		quit(1)
		return
	await controller.refresh_comments("d0")
	_check_refresh_reaches_replies_beyond_first_page(controller)
	await controller.load_comments("d0",true)
	check(controller.get_comments("d0").items.size()==22,"comments page merge")
	await controller.mark_read()
	check(controller.get_state().unread==0,"explicit mark read clears unread")
	check(controller.get_latest_unread().is_empty(), "explicit mark read clears the preview")
	scope.username = "comments-only"
	await controller.start(scope)
	check(controller.get_state().unread == 123 and controller.get_latest_unread().is_empty(), "unread comments alone never show a dynamic card")
	scope.username = "preview-fail"
	await controller.start(scope)
	await controller.refresh_unread()
	check(controller.get_latest_unread().get("id") == "d0" and controller.get_state().unread_code == "HTTP_ERROR", "failed preview fetch retains known unread content and reports error")
	scope.username = "preview-pagination"
	await controller.start(scope)
	check(controller.get_latest_unread().get("id") == "d9", "latest unread skips user-authored posts across pages")
	scope.username = "preview-late"
	controller.start(scope)
	await create_timer(.1).timeout
	controller.stop()
	scope.username = "read"
	await controller.start(scope)
	await create_timer(.4).timeout
	check(controller.get_latest_unread().is_empty(), "late preview from previous account cannot repopulate the card")
	scope.username = "fail-refresh"
	await controller.start(scope)
	await controller.refresh()
	await controller.load_comments("d0")
	var before: Array = controller.get_comments("d0").items
	await controller.refresh_comments("d0")
	check(controller.get_comments("d0").items==before and controller.get_comments("d0").code=="HTTP_ERROR","failed later refresh page preserves all displayed comments")
	for user in ["private-a","private-b"]:
		scope.username = user
		await controller.start(scope)
		await controller.refresh()
		await controller.load_comments("d0")
		var expected := 2 if user == "private-a" else 1
		_check_same_public_post_has_account_scoped_count(controller, expected)
		check(controller.get_comments("d0").items.all(func(item): return item.owner_user_id==user),"relogin retains no prior private comments")
	scope.username = "slow-comments"
	await controller.start(scope)
	await controller.refresh()
	controller.refresh_comments("d0")
	controller.stop()
	await create_timer(.4).timeout
	check(controller.get_comments("d0").items.is_empty(),"logout isolates late complete refresh")
	scope.username = "fail-unread"
	await controller.start(scope)
	await controller.refresh_unread()
	check(controller.get_state().unread==123 and controller.get_state().unread_code=="HTTP_ERROR","failed unread poll preserves count")
	check(controller.get_latest_unread().get("id") == "d0", "failed unread poll preserves known preview")
	scope.username = "fail-write"
	await controller.start(scope)
	await controller.mark_read()
	check(controller.get_state().unread==123,"failed mark read preserves count")
	check(controller.get_latest_unread().get("id") == "d0", "failed mark read preserves preview")
	scope.username = "slow"
	controller.start(scope)
	controller.stop()
	await create_timer(0.6).timeout
	check(controller.get_posts().is_empty() and controller.get_state().unread==0,"logout isolates pending reads")
	controller.queue_free()
	await process_frame
func test_writes() -> void:
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
	controller.queue_free()
	await process_frame

func _check_same_public_post_has_account_scoped_count(controller: Variant, expected: Variant) -> void:
	check(controller.get_posts()[0].comment_count==expected and controller.get_comments("d0").items.size()==expected,"same public post has account-scoped count")

func _check_reading_ten_posts_does_not_clear_unread(controller: Variant) -> void:
	check(controller.get_posts().size()==10 and controller.get_state().unread==123,"reading ten posts does not clear unread")

func _check_opaque_cursor_paging_deduplicates_posts(controller: Variant) -> void:
	check(controller.get_posts().size()==12 and not controller.get_state().has_more,"opaque cursor paging deduplicates posts")

func _check_refresh_reaches_replies_beyond_first_page(controller: Variant) -> void:
	check(controller.get_comments("d0").items.size()==22 and not controller.get_comments("d0").has_more,"refresh reaches replies beyond first page")
