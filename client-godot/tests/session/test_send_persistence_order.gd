extends SceneTree
## 发送顺序：本地尾部必须先提交成功，网络帧才允许发出。

const Session = preload("res://src/session/chat_session.gd")

var failures: Array[String] = []
var order: Array = []


class QuietMedia extends Node:
	signal playback_finished(id: String, code: String)
	signal message_audio_changed(id: String, state: Dictionary)
	signal mouth_changed(value: float)
	signal state_changed(state: Dictionary)
	func reset() -> void: pass
	func set_scope(_server: String, _username: String) -> Error: return OK
	func append_reply_audio(_id: String, _audio: String, _final: bool, _error: bool, _ephemeral: bool,
			_detail: String = "") -> void: pass
	func get_message_audio(_id: String) -> Dictionary: return {}
	func play_reply(_id: String) -> void: pass


class FakePersistence extends RefCounted:
	var order: Array
	var fail := false
	var save_delay_ms := 0
	var generated_wire := "wire-1"

	func _init(shared: Array) -> void:
		order = shared

	func save_local(_message: Dictionary, _entry: Dictionary = {}) -> Dictionary:
		if save_delay_ms > 0:
			await Engine.get_main_loop().create_timer(save_delay_ms / 1000.0).timeout
		else:
			await Engine.get_main_loop().process_frame
		order.append("save_local")
		return {"ok": not fail, "code": "OK" if not fail else "CACHE_SQL_FAILED", "data": {}}

	func update_local(_id: String, _patch: Dictionary) -> Dictionary:
		order.append("update_local")
		return {"ok": true, "code": "OK", "data": {}}

	func delete_local(_id: String) -> Dictionary:
		order.append("delete_local")
		return {"ok": true, "code": "OK", "data": {}}

	func unsaved_count() -> int:
		return 0


class FakeTransport extends Node:
	signal state_changed(state: Dictionary)
	signal delivery_changed(wire_id: String, status: String, code: String)
	signal event_received(event: Dictionary)
	signal system_error(code: String)
	var order: Array
	var sent: Array = []

	func _init(shared: Array) -> void:
		order = shared

	func send_event(event_type: String, payload: Dictionary, _reliable: bool = true, _idempotent: bool = false) -> String:
		order.append("send")
		sent.append([event_type, payload])
		return "wire-1"

	func get_state() -> Dictionary: return {"phase": "ready", "code": ""}
	func start(_session: Dictionary) -> Error: return OK
	func stop() -> void: pass


func _initialize() -> void:
	run.call_deferred()


func run() -> void:
	await _case_save_before_send()
	await _case_failed_save_blocks_send()
	await _case_waiting_history_saves_then_sends()
	await _case_boundary_waits_for_commit()
	await _case_boundary_failure_blocks_send()
	print("Send persistence order: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func check(ok: bool, label: String) -> void:
	if ok:
		return
	failures.append(label)
	print("FAIL: ", label)


func _session() -> Dictionary:
	order.clear()
	var transport := FakeTransport.new(order)
	var persistence := FakePersistence.new(order)
	var session = Session.new(transport, null, QuietMedia.new(), null, null, null, null, persistence)
	root.add_child(session)
	session._connection_changed({"phase": "ready", "code": ""})
	return {"session": session, "transport": transport, "persistence": persistence}


func _until(predicate: Callable, timeout_ms: int = 2000) -> bool:
	var deadline := Time.get_ticks_msec() + timeout_ms
	while not predicate.call() and Time.get_ticks_msec() < deadline:
		await process_frame
	return predicate.call()


func _case_save_before_send() -> void:
	var context := _session()
	var id: String = context.session.send_text("hello")
	check(not id.is_empty(), "send is accepted")
	check(context.transport.sent.is_empty(), "network frame waits for the database commit")
	check(await _until(func(): return context.transport.sent.size() == 1), "frame is sent after the commit")
	check(order.slice(0, 2) == ["save_local", "send"], "save_local happens before send")
	check(str(context.session._by_id[id].status) == "sending", "wire accepted moves to sending")
	context.session._delivery_changed("wire-1", "sent", "")
	check(str(context.session._by_id[id].status) == "sent", "ACK moves to sent")
	check(await _until(func(): return order.has("update_local")), "state transitions are persisted")
	context.session.queue_free()
	await process_frame


func _case_failed_save_blocks_send() -> void:
	var context := _session()
	context.persistence.fail = true
	var id: String = context.session.send_text("must not leave")
	check(await _until(func(): return str(context.session._by_id[id].status) == "failed"), "failed commit marks the bubble failed")
	check(str(context.session._by_id[id].code) == "CACHE_WRITE_FAILED", "failed commit is explicit")
	check(context.transport.sent.is_empty(), "failed commit never sends a frame")
	context.session.queue_free()
	await process_frame


func _case_waiting_history_saves_then_sends() -> void:
	var context := _session()
	context.session._waiting_history = true
	var id: String = context.session.send_text("queued")
	check(await _until(func(): return order.has("save_local")), "queued message still persists first")
	check(context.transport.sent.is_empty(), "waiting history keeps the frame local")
	check(str(context.session._by_id[id].status) == "waiting_history", "queued message reports waiting_history")
	context.session._release_history_sends()
	check(await _until(func(): return context.transport.sent.size() == 1), "boundary release sends the queued frame")
	check(str(context.session._by_id[id].status) == "sending", "released message moves to sending")
	context.session.queue_free()
	await process_frame


## boundary 可能在 save_local 还在排队时到达；此时必须等提交完成再发。
func _case_boundary_waits_for_commit() -> void:
	var context := _session()
	context.persistence.save_delay_ms = 250
	context.session._waiting_history = true
	var id: String = context.session.send_text("slow commit")
	check(not id.is_empty(), "slow commit is accepted")
	await process_frame
	context.session._release_history_sends()
	check(context.transport.sent.is_empty(), "boundary cannot overtake an in-flight commit")
	check(await _until(func(): return context.transport.sent.size() == 1), "slow commit eventually sends")
	check(order.slice(0, 2) == ["save_local", "send"], "slow commit still preserves save-before-send")
	check(str(context.session._by_id[id].status) == "sending", "slow commit reaches sending")
	context.session.queue_free()
	await process_frame


## boundary 放行后保存失败：记录转为 failed，且网络帧永远不发出。
func _case_boundary_failure_blocks_send() -> void:
	var context := _session()
	context.persistence.save_delay_ms = 100
	context.persistence.fail = true
	context.session._waiting_history = true
	var id: String = context.session.send_text("never send")
	await process_frame
	context.session._release_history_sends()
	check(await _until(func(): return str(context.session._by_id[id].status) == "failed"),
		"boundary failure is reported")
	check(context.transport.sent.is_empty(), "failed boundary commit never sends")
	check(not context.session._pending_history.has(id), "failed boundary commit leaves the queue")
	context.session.queue_free()
	await process_frame
