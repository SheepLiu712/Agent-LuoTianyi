extends SceneTree

const ARTIFACTS := "res://artifacts/review-186"
var failures: Array[String] = []

class ControlledFeed extends Node:
	signal changed
	signal unread_changed(count: int)
	var posts: Array[Dictionary] = []
	var comments := {}
	var page_calls := 0

	func _init() -> void:
		for id in ["first", "second", "short"]:
			posts.append({"id":id, "author_name":"洛天依", "author_type":"agent", "created_at":"2026-10-01 12:00:00", "content":"阅读位置验收", "allow_comment":true, "comment_count":35})
			var state := {"items":[], "loaded":true, "busy":false, "has_more":false, "cursor":"", "code":"OK"}
			if id != "short":
				for index in 35:
					state.items.append({"id":"%s-%s" % [id,index], "author_name":"测试用户", "author_type":"user", "created_at":"2026-10-01 12:00:00", "content":"第 %s 条评论，独立保存每条动态的阅读位置。" % index, "parent_comment_id":null})
			comments[id] = state

	func get_posts() -> Array[Dictionary]:
		return posts.duplicate(true)

	func get_state() -> Dictionary:
		return {"busy":false, "has_more":false, "code":"OK", "unread":0, "unread_code":"OK"}

	func get_comments(id: String) -> Dictionary:
		return comments[id].duplicate(true)

	func refresh_comments(id: String) -> void:
		comments[id].busy = true
		changed.emit()

	func complete(id: String, failed: bool = false) -> void:
		comments[id].busy = false
		comments[id].code = "HTTP_ERROR" if failed else "OK"
		changed.emit()

	func refresh() -> void:
		changed.emit()

	func mark_read() -> void:
		unread_changed.emit(0)

	func load_comments(id: String, more: bool = false) -> void:
		if not more or comments[id].busy or not comments[id].has_more: return
		page_calls += 1
		comments[id].has_more = false
		changed.emit()

func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	for style in ["flat", "crystal"]:
		for dimensions in [Vector2i(1100,800), Vector2i(960,640)]:
			await _check_window(style, dimensions)
	print("Dynamics reading position: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func _settle() -> void:
	for frame in 6: await process_frame

func _wait_restored(detail: ScrollContainer) -> void:
	var deadline := Time.get_ticks_msec() + 3000
	while detail._pending_scroll >= 0 and Time.get_ticks_msec() < deadline:
		await process_frame
	check(detail._pending_scroll < 0, "restore completes after data and layout settle")

func _check_window(style_name: String, dimensions: Vector2i) -> void:
	var controller := ControlledFeed.new()
	root.add_child(controller)
	var path := "user://reading-review-%s.cfg" % Time.get_ticks_usec()
	var store := preload("res://src/storage/godot_settings_store.gd").new(path)
	var style := preload("res://src/application/ui_style.gd").new()
	style.configure(store)
	style.save_preferences(style_name, "svg")
	var window = load("res://scenes/ui/dynamics_window.tscn").instantiate()
	window.setup(controller, store)
	window.set_ui_style(style)
	root.add_child(window)
	window.open()
	window.size = dimensions
	await _settle()
	window.select_post("first")
	controller.complete("first")
	var first: ScrollContainer = window._details["first"]
	await _wait_restored(first)
	check(first.get_v_scroll_bar().max_value - first.get_v_scroll_bar().page >= 140, "fixture has real overflowing content")
	first.scroll_vertical = 140
	await process_frame
	window.select_post("second")
	controller.complete("second")
	var second: ScrollContainer = window._details["second"]
	await _wait_restored(second)
	second.scroll_vertical = 80
	await process_frame
	await _check_late_refresh(window, controller, first, second)
	await _capture(window, style_name, dimensions)
	await _check_hidden_window(window, controller, first)
	await _check_user_scroll(window, controller, first)
	await _check_scrollbar_and_keyboard(window, controller, first)
	await _check_bottom_pagination(window, controller, first)
	await _check_short_detail(window, controller)
	await _check_failed_refresh(window, controller, first)
	window.queue_free()
	controller.queue_free()
	await process_frame
	DirAccess.remove_absolute(path)

func _check_late_refresh(window: Window, controller: ControlledFeed, first: ScrollContainer, second: ScrollContainer) -> void:
	window.select_post("first")
	await _settle()
	check(first.get_reading_position() == 140, "busy refresh retains intended position")
	window.select_post("second")
	controller.complete("first")
	controller.complete("second")
	await _wait_restored(second)
	check(window.get_selected_id() == "second" and second.scroll_vertical == 80, "late response does not move current post")
	window.select_post("first")
	controller.complete("first")
	await _wait_restored(first)
	check(first.scroll_vertical == 140, "switching during refresh does not replace saved position with clamped value")

func _check_user_scroll(window: Window, controller: ControlledFeed, first: ScrollContainer) -> void:
	window.select_post("second")
	controller.complete("second")
	await _wait_restored(window._details["second"])
	window.select_post("first")
	await _settle()
	var wheel := InputEventMouseButton.new()
	wheel.button_index = MOUSE_BUTTON_WHEEL_DOWN
	wheel.pressed = true
	wheel.position = first.get_global_rect().get_center()
	wheel.global_position = wheel.position
	window.push_input(wheel, true)
	await process_frame
	check(first._pending_scroll < 0, "real wheel input cancels pending restoration")
	first.scroll_vertical = 60
	controller.complete("first")
	await _wait_restored(first)
	check(first.scroll_vertical == 60, "refresh completion does not steal user position")

func _check_short_detail(window: Window, controller: ControlledFeed) -> void:
	window.select_post("short")
	var detail: ScrollContainer = window._details["short"]
	detail.restore_reading_position(500)
	controller.complete("short")
	await _wait_restored(detail)
	check(detail.scroll_vertical == 0, "short content legally clamps saved position")

func _check_hidden_window(window: Window, controller: ControlledFeed, detail: ScrollContainer) -> void:
	controller.refresh_comments("first")
	detail.restore_reading_position(90)
	window.hide()
	controller.complete("first")
	await _settle()
	check(detail._pending_scroll == 90, "hidden window retains pending target")
	window.show()
	await _wait_restored(detail)
	check(detail.scroll_vertical == 90, "showing window restores position after hidden response")

func _check_scrollbar_and_keyboard(window: Window, controller: ControlledFeed, detail: ScrollContainer) -> void:
	var bar := detail.get_v_scroll_bar()
	bar.focus_mode = Control.FOCUS_ALL
	bar.grab_focus()
	controller.refresh_comments("first")
	detail.restore_reading_position(140)
	var key := InputEventKey.new()
	key.keycode = KEY_PAGEDOWN
	key.pressed = true
	window.push_input(key, true)
	await process_frame
	check(detail._pending_scroll < 0, "focused scrollbar key cancels pending target")
	var keyboard_position := detail.scroll_vertical
	controller.complete("first")
	await _wait_restored(detail)
	check(detail.scroll_vertical == keyboard_position, "refresh keeps keyboard scroll position")
	await _check_scrollbar_pointer(window, controller, detail)

func _pointer(window: Window, position: Vector2, pressed: bool) -> void:
	var event := InputEventMouseButton.new()
	event.button_index = MOUSE_BUTTON_LEFT
	event.position = position
	event.global_position = position
	event.pressed = pressed
	window.push_input(event, true)

func _check_scrollbar_pointer(window: Window, controller: ControlledFeed, detail: ScrollContainer) -> void:
	controller.refresh_comments("first")
	detail.restore_reading_position(140)
	var point := detail.get_v_scroll_bar().get_global_rect().get_center()
	_pointer(window, point, true)
	var motion := InputEventMouseMotion.new()
	motion.position = point + Vector2(0,20)
	motion.global_position = motion.position
	motion.relative = Vector2(0,20)
	motion.button_mask = MOUSE_BUTTON_MASK_LEFT
	window.push_input(motion, true)
	_pointer(window, motion.position, false)
	await process_frame
	check(detail._pending_scroll < 0, "scrollbar pointer input cancels pending target")
	var position := detail.scroll_vertical
	controller.complete("first")
	await _wait_restored(detail)
	check(detail.scroll_vertical == position, "refresh keeps scrollbar position")

func _check_bottom_pagination(window: Window, controller: ControlledFeed, detail: ScrollContainer) -> void:
	controller.comments["first"].has_more = true
	var calls := controller.page_calls
	detail.restore_reading_position(100000)
	await _wait_restored(detail)
	check(controller.page_calls == calls, "restoring alone does not fetch another page")
	var wheel := InputEventMouseButton.new()
	wheel.button_index = MOUSE_BUTTON_WHEEL_DOWN
	wheel.pressed = true
	wheel.position = detail.get_global_rect().get_center()
	wheel.global_position = wheel.position
	window.push_input(wheel, true)
	await _settle()
	check(controller.page_calls == calls + 1, "wheel at already-restored bottom still loads next page")

func _check_failed_refresh(window: Window, controller: ControlledFeed, first: ScrollContainer) -> void:
	window.select_post("first")
	first.get_node("%CommentDraft").text = "失败也保留评论草稿"
	first.restore_reading_position(70)
	var count: int = first._rows.size()
	controller.complete("first", true)
	await _wait_restored(first)
	check(first.scroll_vertical == 70, "failed refresh restores cached reading position")
	check(first._rows.size() == count and first.get_node("%CommentDraft").text == "失败也保留评论草稿", "failed refresh preserves content and draft")
	check(first.get_node("%Status").text.contains("HTTP_ERROR"), "failed refresh remains visible")

func _capture(window: Window, style_name: String, dimensions: Vector2i) -> void:
	if DisplayServer.get_name() == "headless": return
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(ARTIFACTS))
	await RenderingServer.frame_post_draw
	var filename := "reading-%s-%sx%s.png" % [style_name, dimensions.x, dimensions.y]
	check(window.get_texture().get_image().save_png(ARTIFACTS.path_join(filename)) == OK, "capture restored reading position")
