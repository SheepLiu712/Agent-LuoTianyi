extends SceneTree

const Session = preload("res://src/session/chat_session.gd")
const Transport = preload("res://src/network/websocket_transport.gd")
var failures: Array[String] = []

class QuietMedia extends Node:
	signal playback_finished(id: String, code: String)
	signal message_audio_changed(id: String, state: Dictionary)
	signal mouth_changed(value: float)
	signal state_changed(state: Dictionary)
	func reset() -> void: pass
	func set_scope(_server: String, _username: String) -> Error: return OK
	func append_reply_audio(_id: String, _audio: String, _final: bool, _error: bool, _ephemeral: bool) -> void: pass
	func play_reply(_id: String) -> void: pass

func _initialize() -> void:
	run.call_deferred()

func check(ok: bool, description: String) -> void:
	if not ok:
		failures.append(description)
		print("FAIL: ", description)

func reply_event(id: String, timestamp: Variant, text: String, final: bool = false) -> Dictionary:
	return {"type":"agent_message", "ts":timestamp, "payload":{"uuid":id, "text":text, "audio":"", "is_final_package":final}}

func run() -> void:
	var session := Session.new(Transport.new(), null, QuietMedia.new())
	root.add_child(session)
	session._connection_changed({"phase":"connecting", "code":""})
	session._waiting_history = true
	test_outgoing_time(session)
	test_stream_time(session)
	test_fallback_time(session)
	test_history_time(session)
	session.queue_free()
	await process_frame
	print("Message timestamp sources: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func test_outgoing_time(session: Node) -> void:
	var before := Time.get_unix_time_from_system()
	var id: String = session.send_text("排队期间也记录发送时间")
	var current: Dictionary = session.get_messages()[0]
	check(not id.is_empty() and current.timestamp >= before and current.timestamp <= Time.get_unix_time_from_system(), "queued user message records its creation time")
	var original: float = current.timestamp
	session._delivery_changed(id, "sent", "")
	check(session.get_messages()[0].timestamp == original, "delivery changes never replace the user-message time")

func test_stream_time(session: Node) -> void:
	var first_ms := 1790816400000
	session._receive(reply_event("stream", first_ms, "第一段"))
	var first: Dictionary = session.get_messages()[1]
	check(first.timestamp == first_ms / 1000.0, "assistant message uses the server envelope's Unix-millisecond time")
	session._receive(reply_event("stream", first_ms + 300000, "完整回复", true))
	var streamed: Dictionary = session.get_messages()[1]
	check(streamed.timestamp == first.timestamp and streamed.text == "完整回复", "late final package updates text without moving the group time")
	session._receive(reply_event("stream", first_ms + 600000, "重复终包", true))
	check(session.get_messages()[1].timestamp == first.timestamp, "duplicate final package does not change first arrival time")
	session._audio_finished("stream", "")

func test_fallback_time(session: Node) -> void:
	var before := Time.get_unix_time_from_system()
	session._receive(reply_event("no-time", null, "没有时间字段的兼容回复"))
	var fallback: Dictionary = session.get_messages()[2]
	check(fallback.timestamp >= before and fallback.timestamp <= Time.get_unix_time_from_system(), "an absent envelope timestamp falls back to local first arrival")
	for raw in [-1, 0, INF, NAN, "invalid"]:
		check(session._reply_timestamp(raw) >= before, "invalid envelope time safely uses arrival time")

func test_history_time(session: Node) -> void:
	var history: Array[Dictionary] = [{"id":"stream", "role":"assistant", "text":"历史副本", "timestamp":"2026-10-01 09:01:00", "status":"received", "code":""}]
	session._history_page(history)
	var merged: Dictionary = session.get_messages()[0]
	check(merged.id == "stream" and merged.timestamp == history[0].timestamp, "UUID merge adopts the authoritative history timestamp")
	check(merged.text == "完整回复" and session.get_messages().size() == 3, "history-time reconciliation preserves live text and message identity")
