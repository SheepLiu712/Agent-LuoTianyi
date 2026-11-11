extends SceneTree
## “回到最新”优先于“定位未读”：显式动作必须消费目标，且不能被延迟自动定位拉回。

var failures: Array[String] = []


class FakeSession:
	extends Node
	signal changed
	signal state_changed(state: Dictionary)
	signal message_audio_changed(id: String, state: Dictionary)

	var reading := {"pending":false, "manual":false, "located":false, "target_id":"", "reason":""}
	var messages: Array[Dictionary] = []
	var noted := 0
	var located := 0
	var dismissed := 0
	var reported := 0
	var older_requests := 0

	func get_reading_state() -> Dictionary:
		return reading.duplicate(true)

	func note_read_interaction() -> void:
		noted += 1
		reading.manual = true

	func reading_located() -> void:
		located += 1
		reading.located = true

	func dismiss_unread() -> void:
		dismissed += 1
		reading.manual = true
		reading.located = true
		reading.target_id = ""

	func get_messages() -> Array[Dictionary]:
		return messages

	func get_message_audio(_id: String) -> Dictionary:
		return {"available":false, "code":""}

	func request_message_image(_id: String) -> void:
		pass

	func get_message_image(_id: String) -> Dictionary:
		return {"status":"idle", "texture":null, "original_size":Vector2i.ZERO, "code":""}

	func report_visible_messages(_ids: Array[String], _foreground: bool) -> void:
		reported += 1

	func load_older_history() -> void:
		older_requests += 1


func _initialize() -> void:
	run.call_deferred()


func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)


func settle(frames: int = 10) -> void:
	for _frame in frames:
		await process_frame


func run() -> void:
	var chat = load("res://scenes/ui/chat_view.tscn").instantiate()
	root.add_child(chat)
	chat.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	await settle()
	var session := FakeSession.new()
	root.add_child(session)
	for index in 40:
		session.messages.append({"id":str(index), "role":"assistant", "text":"消息 %s" % index, "type":"text", "status":"received", "code":""})
	chat._session = session
	chat._scroll.set_messages(session.messages)
	await settle()
	await _check_both_buttons_and_latest_wins(chat, session)
	await _check_unread_then_latest(chat, session)
	await _check_missing_target_retries_next_page(chat, session)
	await _check_auto_jump_is_suppressed(chat, session)
	chat.queue_free()
	session.queue_free()
	await process_frame
	print("Chat reading buttons: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func _check_both_buttons_and_latest_wins(chat: Node, session: FakeSession) -> void:
	session.reading = {"pending":false, "manual":true, "located":false, "target_id":"20", "reason":""}
	chat._apply_reading()
	chat._scroll.scroll_to_message("10")
	chat._update_latest_visibility()
	await settle(4)
	check(chat.get_node("%Unread").visible and chat.get_node("%Latest").visible, "both actions can be visible before a choice")
	chat._to_latest()
	await settle(4)
	check(session.dismissed == 1 and session.get_reading_state().target_id.is_empty(), "latest consumes the unread target")
	check(not chat.get_node("%Unread").visible and not chat.get_node("%Latest").visible, "latest hides both actions once at the bottom")
	check(chat._scroll.is_at_latest(), "latest really returns to the bottom")
	var located_before := session.located
	chat._apply_reading()
	check(chat._scroll.is_at_latest() and session.located == located_before, "no delayed auto-jump after latest wins")


func _check_unread_then_latest(chat: Node, session: FakeSession) -> void:
	session.reading = {"pending":false, "manual":false, "located":false, "target_id":"5", "reason":""}
	var located_before := session.located
	chat._request_unread()
	await settle(4)
	check(session.located == located_before + 1 and not chat.get_node("%Unread").visible, "unread hides after a successful location")
	check(not chat._scroll.is_at_latest() and chat.get_node("%Latest").visible, "latest becomes available after leaving the bottom")
	chat._to_latest()
	await settle(4)
	check(chat._scroll.is_at_latest() and session.dismissed == 2, "latest still wins after unread was located")


func _check_missing_target_retries_next_page(chat: Node, session: FakeSession) -> void:
	session.reading = {"pending":false, "manual":true, "located":false, "target_id":"older-missing", "reason":""}
	chat.get_node("%Unread").show()
	chat._jump_reading()
	await process_frame
	check(session.older_requests == 1 and not session.reading.located, "missing target requests the next page and keeps the action")
	check(chat.get_node("%Unread").visible, "unread stays visible while the target page is loading")
	session.messages.push_front({"id":"older-missing", "role":"assistant", "text":"更早消息", "type":"text", "status":"received", "code":""})
	chat._refresh()
	await settle(4)
	check(chat.get_node("%Unread").visible == false, "unread resolves after the page arrives")
	check(chat._scroll.get_reading_anchor().id == "older-missing", "the retried jump lands on the target")


func _check_auto_jump_is_suppressed(chat: Node, session: FakeSession) -> void:
	chat._to_latest()
	await settle(4)
	session.reading = {"pending":false, "manual":true, "located":false, "target_id":"5", "reason":""}
	chat._apply_reading()
	check(chat._scroll.is_at_latest(), "manual interaction suppresses auto location")
	check(chat.get_node("%Unread").visible, "manual interaction leaves the unread action available")
