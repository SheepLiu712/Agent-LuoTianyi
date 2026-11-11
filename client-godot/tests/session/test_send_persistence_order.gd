extends SceneTree
## 发送落库顺序：messages 行必须先于 send_attempts 存在，否则外键失败。

const Session = preload("res://src/session/chat_session.gd")

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


class FakeTransport extends Node:
	signal state_changed(state: Dictionary)
	signal delivery_changed(wire_id: String, status: String, code: String)
	signal event_received(event: Dictionary)
	signal system_error(code: String)
	var sent: Array = []
	func send_event(event_type: String, payload: Dictionary, _reliable: bool = true, _idempotent: bool = false) -> String:
		sent.append([event_type, payload])
		return "wire-1"
	func start(_session: Dictionary) -> Error: return OK
	func stop() -> void: pass


class FakePersistence extends RefCounted:
	var order: Array = []
	func save_live(_message: Dictionary) -> void: order.append("save_live")
	func record_attempt(_message_id: String, _wire_id: String) -> void: order.append("record_attempt")
	func update_attempt(_message_id: String, _wire_id: String, _state: String, _code: String) -> void: pass


func _initialize() -> void:
	run.call_deferred()


func run() -> void:
	var transport := FakeTransport.new()
	var persistence := FakePersistence.new()
	var session := Session.new(transport, null, QuietMedia.new(), null, null, null, null, persistence)
	root.add_child(session)
	session._connection_changed({"phase": "ready", "code": ""})
	check(not session.send_text("hello").is_empty(), "send is accepted")
	check(transport.sent.size() == 1, "event is sent exactly once")
	check(persistence.order == ["save_live", "record_attempt"], "message row is saved before the send attempt")
	session.queue_free()
	await process_frame
	print("Send persistence order: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func check(ok: bool, label: String) -> void:
	if ok:
		return
	failures.append(label)
	print("FAIL: ", label)
