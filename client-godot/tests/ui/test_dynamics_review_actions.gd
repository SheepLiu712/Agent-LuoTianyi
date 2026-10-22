extends SceneTree

const ARTIFACTS := "res://artifacts/ui-redraw-client"
var failures: Array[String] = []

class FeedController extends Node:
	signal changed
	signal unread_changed(count: int)
	var page_calls := 0
	var refresh_calls := 0
	var comment_calls := {}
	var fail_next_page := false
	var fail_next_comments := false
	var posts: Array[Dictionary] = []
	var comments := {}
	var state := {"busy":false, "has_more":true, "code":"OK", "unread":1, "unread_code":"OK"}

	func _init() -> void:
		for index in 12: posts.append(make_post(index))
		var cached := empty_comments()
		cached.loaded = true
		for index in 18: cached.items.append(make_comment("review-0", index))
		comments["review-0"] = cached

	func make_post(index: int) -> Dictionary:
		return {"id":"review-%s" % index, "author_name":"洛天依", "author_type":"agent", "source_type":"diary", "created_at":"2026-09-30 20:00:00", "content":"今天想和你分享第 %s 件小事。\n\n点击这张卡片，会自动查看最新的评论。" % (index + 1), "allow_comment":true, "comment_count":18}

	func make_comment(id: String, index: int) -> Dictionary:
		return {"id":"%s-comment-%s" % [id, index], "author_name":"洛天依", "author_type":"agent", "created_at":"2026-09-30 20:00:00", "content":"第 %s 条留言：今天也一起慢慢聊。" % (index + 1), "parent_comment_id":null}

	func empty_comments() -> Dictionary:
		return {"items":[], "loaded":false, "busy":false, "has_more":false, "code":"OK", "cursor":""}

	func get_posts() -> Array[Dictionary]:
		return posts.duplicate(true)

	func get_state() -> Dictionary:
		return state.duplicate(true)

	func get_comments(id: String) -> Dictionary:
		return comments.get(id, empty_comments()).duplicate(true)

	func refresh_comments(id: String) -> void:
		comment_calls[id] = int(comment_calls.get(id, 0)) + 1
		if not comments.has(id): comments[id] = empty_comments()
		var current: Dictionary = comments[id]
		if current.busy: return
		current.busy = true
		changed.emit()
		await get_tree().create_timer(.06).timeout
		current.busy = false
		if fail_next_comments:
			fail_next_comments = false
			current.code = "HTTP_ERROR"
		else:
			current.items.append(make_comment(id, current.items.size()))
			current.loaded = true
			current.code = "OK"
		changed.emit()

	func load_more() -> void:
		if state.busy or not state.has_more: return
		page_calls += 1
		state.busy = true
		changed.emit()
		await get_tree().create_timer(.06).timeout
		state.busy = false
		if fail_next_page:
			fail_next_page = false
			state.code = "HTTP_ERROR"
		else:
			for index in range(12, 24): posts.append(make_post(index))
			state.has_more = false
			state.code = "OK"
		changed.emit()

	func refresh() -> void:
		refresh_calls += 1
		changed.emit()

	func mark_read() -> void:
		state.unread = 0
		unread_changed.emit(0)

func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)

func _initialize() -> void:
	run.call_deferred()

func settle() -> void:
	for frame in 3: await process_frame
	await create_timer(.12).timeout

func click(window: Window, button: Button) -> void:
	var point := button.get_global_rect().get_center()
	var motion := InputEventMouseMotion.new()
	motion.position = point
	motion.global_position = point
	window.push_input(motion, true)
	for pressed in [true, false]:
		var event := InputEventMouseButton.new()
		event.button_index = MOUSE_BUTTON_LEFT
		event.position = point
		event.global_position = point
		event.pressed = pressed
		window.push_input(event, true)
		await process_frame

func wheel_down(window: Window, scroll: ScrollContainer) -> void:
	var event := InputEventMouseButton.new()
	event.button_index = MOUSE_BUTTON_WHEEL_DOWN
	event.position = scroll.get_global_rect().get_center()
	event.global_position = event.position
	event.pressed = true
	window.push_input(event, true)
	event.pressed = false
	window.push_input(event, true)
	await process_frame

func capture(window: Window, name: String) -> void:
	if DisplayServer.get_name() == "headless": return
	await RenderingServer.frame_post_draw
	check(window.get_texture().get_image().save_png(ARTIFACTS.path_join(name + ".png")) == OK, "capture " + name)

func run() -> void:
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(ARTIFACTS))
	var controller := FeedController.new()
	root.add_child(controller)
	var path := "user://review-actions-%s.cfg" % Time.get_ticks_usec()
	var store := preload("res://src/storage/godot_settings_store.gd").new(path)
	var style := preload("res://src/application/ui_style.gd").new()
	style.configure(store)
	var window = load("res://scenes/ui/dynamics_window.tscn").instantiate()
	window.setup(controller, store)
	window.set_ui_style(style)
	root.add_child(window)
	window.open()
	window.size = Vector2i(1100, 800)
	await settle()
	check(window.get_node_or_null("%More") == null, "feed has no manual load-more button")
	check(window.get_selected_id().is_empty(), "opening still has no selected post")
	await click(window, window._rows["review-0"])
	var detail = window._details["review-0"]
	check(detail.get_node_or_null("%LoadMore") == null, "detail has no loading box or manual comment-load button")
	check(controller.get_comments("review-0").busy, "comment request is really running")
	check(detail.find_children("LoadMore", "Button", true, false).is_empty(), "busy comments do not insert a loading box")
	await capture(window, "dynamics-comments-no-loading-box")
	await settle()
	_check_clicking_cached_post_refreshes_comments(window, controller)
	check(controller.get_comments("review-0").items.size() == 19, "new comment appears without toolbar refresh")
	var draft: TextEdit = detail.get_node("%CommentDraft")
	draft.text = "保留我的评论草稿"
	detail.scroll_vertical = 80
	await settle()
	var reading_position: int = detail.scroll_vertical
	await click(window, window._rows["review-0"])
	await settle()
	check(controller.comment_calls["review-0"] == 2, "clicking selected post refreshes again")
	_check_refresh_preserves_draft_and_reading_position(draft, detail, reading_position)
	window._rows["review-0"].pressed.emit()
	window._rows["review-0"].pressed.emit()
	await settle()
	check(controller.comment_calls["review-0"] == 3, "in-flight clicks do not duplicate comment requests")
	await click(window, window._rows["review-1"])
	await settle()
	await click(window, window._rows["review-0"])
	await settle()
	_check_switching_posts_refreshes_without_discarding_drafts(controller, draft)
	controller.fail_next_comments = true
	var prior_count: int = controller.get_comments("review-0").items.size()
	await click(window, window._rows["review-0"])
	await settle()
	_check_failed_auto_refresh_preserves_comments_and_reports_failure(controller, prior_count, detail)
	await click(window, window._rows["review-0"])
	await settle()
	_check_another_click_retries_failed_comments(detail, draft)
	check(controller.refresh_calls == 0 and controller.state.unread == 1, "card refresh needs no manual feed refresh and does not mark read")
	var list_scroll: ScrollContainer = window.get_node("%ListScroll")
	controller.fail_next_page = true
	for attempt in 60:
		await wheel_down(window, list_scroll)
		if controller.page_calls > 0: break
	await settle()
	check(controller.page_calls == 1 and window.get_node("%Notice").text.contains("HTTP_ERROR"), "wheel reaching bottom loads next page and exposes failure")
	await wheel_down(window, list_scroll)
	await settle()
	check(controller.page_calls == 2 and controller.get_posts().size() == 24, "wheel retries pagination without a load-more button")
	list_scroll.scroll_vertical = 0
	detail.scroll_vertical = 0
	await settle()
	for variant in ["flat", "crystal"]:
		check(style.save_preferences(variant, "svg") == OK, "switch style " + variant)
		await settle()
		await capture(window, "dynamics-actions-" + variant + "-1100x800")
		var body: RichTextLabel = detail.get_node("%Body")
		body.select_all()
		_check_run_result(body, variant)
		await capture(window, "dynamics-selection-" + variant + "-1100x800")
		body.deselect()
		await click(window, window.get_node("%Publish"))
		await settle()
		var publisher: Control = window._publisher
		check(publisher.get_node_or_null("%ClosePublish") == null, "publisher has no header close button")
		check(publisher.get_node("Center/Panel/Column/Header").find_children("*", "Button", true, false).is_empty(), "publisher title has no cross glyph actions")
		await capture(window, "dynamics-publish-clean-" + variant + "-1100x800")
		await click(window, publisher.get_node("%CancelPublish"))
		await settle()
		check(not is_instance_valid(publisher), "empty publisher closes using bottom cancel")
	await click(window, window.get_node("%Publish"))
	await settle()
	var publisher: Control = window._publisher
	publisher.get_node("%PublishDraft").text = "尚未发布的草稿"
	await click(window, publisher.get_node("%CancelPublish"))
	await settle()
	var discard: Window = publisher.get_node("%DiscardDialog")
	check(discard.visible and publisher.is_dirty(), "bottom cancel protects unsent draft")
	discard.get_cancel_button().pressed.emit()
	await settle()
	check(publisher.get_node("%PublishDraft").text == "尚未发布的草稿", "cancel discard keeps publish draft")
	await click(window, publisher.get_node("%CancelPublish"))
	await settle()
	discard.get_ok_button().pressed.emit()
	await settle()
	check(not is_instance_valid(publisher), "confirmed discard closes publish overlay")
	window.size = Vector2i(960, 640)
	await settle()
	await capture(window, "dynamics-actions-compact-960x640")
	window.queue_free()
	controller.queue_free()
	await process_frame
	DirAccess.remove_absolute(path)
	print("Dynamics review actions: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
func _check_run_result(body: Variant, variant: Variant) -> void:
	check(body.get_theme_color("selection_color").is_equal_approx(Color("0078d7")) and body.get_theme_color("font_selected_color").is_equal_approx(Color.WHITE), "selected body uses blue and white: " + variant)

func _check_clicking_cached_post_refreshes_comments(window: Variant, controller: Variant) -> void:
	check(window.get_selected_id() == "review-0" and controller.comment_calls.get("review-0", 0) == 1, "clicking cached post refreshes comments")

func _check_refresh_preserves_draft_and_reading_position(draft: Variant, detail: Variant, reading_position: Variant) -> void:
	check(draft.text == "保留我的评论草稿" and detail.scroll_vertical == reading_position, "refresh preserves draft and reading position")

func _check_switching_posts_refreshes_without_discarding_drafts(controller: Variant, draft: Variant) -> void:
	check(controller.comment_calls["review-1"] == 1 and draft.text == "保留我的评论草稿", "switching posts refreshes without discarding drafts")

func _check_failed_auto_refresh_preserves_comments_and_reports_failure(controller: Variant, prior_count: Variant, detail: Variant) -> void:
	check(controller.get_comments("review-0").items.size() == prior_count and detail.get_node("%Status").text.contains("HTTP_ERROR"), "failed auto-refresh preserves comments and reports failure")

func _check_another_click_retries_failed_comments(detail: Variant, draft: Variant) -> void:
	check(detail.get_node("%Status").text.is_empty() and draft.text == "保留我的评论草稿", "another click retries failed comments")
