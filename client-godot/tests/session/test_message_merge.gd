extends SceneTree
## 会话内存窗口：本地尾部优先、原位合并、服务器确认后只移除 local 行。

const Session = preload("res://src/session/chat_session.gd")

var failures: Array[String] = []


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


class FakeTransport extends Node:
	signal state_changed(state: Dictionary)
	signal delivery_changed(wire_id: String, status: String, code: String)
	signal event_received(event: Dictionary)
	signal system_error(code: String)
	var sent: Array = []

	func send_event(event_type: String, payload: Dictionary, _reliable: bool = true, _idempotent: bool = false) -> String:
		sent.append([event_type, payload])
		return "wire-%d" % sent.size()

	func get_state() -> Dictionary: return {"phase": "ready", "code": ""}
	func start(_session: Dictionary) -> Error: return OK
	func stop() -> void: pass


class FakePersistence extends RefCounted:
	var order: Array = []
	var fail_save := false
	var fail_delete := false
	func save_local(_message: Dictionary, _entry: Dictionary = {}) -> Dictionary:
		order.append("save_local")
		return {"ok": not fail_save, "code": "OK" if not fail_save else "CACHE_SQL_FAILED", "data": {}}
	func update_local(_id: String, _patch: Dictionary) -> Dictionary:
		order.append("update_local")
		return {"ok": true, "code": "OK", "data": {}}
	func delete_local(_id: String) -> Dictionary:
		order.append("delete_local")
		return {"ok": not fail_delete, "code": "OK" if not fail_delete else "CACHE_SQL_FAILED", "data": {}}
	func unsaved_count() -> int:
		return 0


func _initialize() -> void:
	run.call_deferred()


func run() -> void:
	_case_restore_and_reconcile()
	_case_latest_page_anchors()
	await _case_retry_and_delete()
	await _case_release_restored_pending()
	await _case_retry_requires_commit()
	await _case_delete_failure_keeps_row()
	print("Message merge: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func check(ok: bool, label: String) -> void:
	if ok:
		return
	failures.append(label)
	print("FAIL: ", label)


func _session() -> Dictionary:
	var transport := FakeTransport.new()
	var persistence := FakePersistence.new()
	var session = Session.new(transport, null, QuietMedia.new(), null, null, null, null, persistence)
	root.add_child(session)
	session._connection_changed({"phase": "ready", "code": ""})
	return {"session": session, "transport": transport, "persistence": persistence}


func _case_restore_and_reconcile() -> void:
	var context := _session()
	var session: Node = context.session
	session._restore_page(_typed([
		_message("s1", "user", "一"),
		_local("local-1", "text", "本机", "failed"),
		_message("s2", "assistant", "二"),
	]))
	check(_ids(session) == ["s1", "local-1", "s2"], "restore keeps the stored order")
	session._latest_page(_typed([
		_message("s1", "user", "一"),
		_message("s2", "assistant", "二"),
	]))
	check(_ids(session) == ["s1", "local-1", "s2"], "latest page merges in place")
	check(str(_find(session, "s1").id_source) == "server", "confirmed rows become server identity")
	session._delivery_reconciled(["s1"])
	check(_ids(session).has("s1"), "server rows are never removed by confirmation")
	session._delivery_reconciled(["local-1"])
	check(_ids(session) == ["s1", "s2"], "confirmed local row is removed")
	session.queue_free()


func _case_latest_page_anchors() -> void:
	var context := _session()
	var session: Node = context.session
	session._restore_page(_typed([
		_message("s1", "user", "一"),
		_message("s3", "assistant", "三"),
	]))
	session._latest_page(_typed([
		_message("s1", "user", "一"),
		_message("s2", "user", "二"),
		_message("s3", "assistant", "三"),
	]))
	check(_ids(session) == ["s1", "s2", "s3"], "unknown rows land before the next cached anchor")
	session.queue_free()
	var other := _session()
	other.session._restore_page(_typed([_message("old-1", "user", "旧一"), _message("old-2", "assistant", "旧二")]))
	other.session._latest_page(_typed([_message("new-1", "user", "新一"), _message("new-2", "assistant", "新二")]))
	check(_ids(other.session) == ["old-1", "old-2", "new-1", "new-2"], "a newer page follows the cached window")
	other.session.queue_free()


func _case_retry_and_delete() -> void:
	var context := _session()
	var session: Node = context.session
	session._restore_page(_typed([_local("failed-1", "text", "重试我", "failed")]))
	var retried: bool = await session.retry_message("failed-1")
	check(retried, "retry accepts a failed local row")
	check(context.transport.sent.size() == 1, "retry sends the original event")
	check(str(_find(session, "failed-1").status) == "sending", "retry moves to sending")
	var deleted: bool = await session.delete_message("failed-1")
	check(deleted, "delete accepts a local row")
	check(_ids(session).is_empty(), "delete removes the bubble")
	var missing: bool = await session.delete_message("missing")
	check(not missing, "delete rejects unknown ids")
	session.queue_free()


func _case_release_restored_pending() -> void:
	var context := _session()
	var session: Node = context.session
	session._waiting_history = true
	session._restore_page(_typed([
		_message("h1", "assistant", "缓存"),
		_local("pending-1", "text", "排队", "pending", {"event": "user_text", "payload": {"message": "排队"}}),
	]))
	check(_ids(session) == ["h1", "pending-1"], "restored pending row stays visible")
	check(session._pending_history.has("pending-1"), "restored pending row is adopted")
	session._release_history_sends()
	check(await _until(func(): return context.transport.sent.size() == 1), "boundary release sends the restored row")
	check(str(_find(session, "pending-1").status) == "sending", "restored row moves to sending")
	session.queue_free()
	await process_frame


## 手动重试也要先提交本地意图；提交失败不得发网络帧。
func _case_retry_requires_commit() -> void:
	var context := _session()
	var session: Node = context.session
	session._restore_page(_typed([_local("retry-1", "text", "再试一次", "failed")]))
	context.persistence.fail_save = true
	var rejected: bool = await session.retry_message("retry-1")
	check(not rejected, "retry reports a failed commit")
	check(context.transport.sent.is_empty(), "failed retry commit never sends")
	check(str(_find(session, "retry-1").status) == "failed", "failed retry stays failed")
	check(str(_find(session, "retry-1").code) == "CACHE_SQL_FAILED", "retry exposes the commit error")
	context.persistence.fail_save = false
	check(await session.retry_message("retry-1"), "retry succeeds after the cache recovers")
	check(context.transport.sent.size() == 1, "recovered retry sends exactly once")
	session.queue_free()
	await process_frame


## 删除失败时不能先移除气泡；否则重启后本地行会“复活”。
func _case_delete_failure_keeps_row() -> void:
	var context := _session()
	var session: Node = context.session
	session._restore_page(_typed([_local("keep-1", "text", "保留", "failed")]))
	context.persistence.fail_delete = true
	var rejected: bool = await session.delete_message("keep-1")
	check(not rejected, "failed delete is reported")
	check(_ids(session).has("keep-1"), "failed delete keeps the bubble")
	context.persistence.fail_delete = false
	check(await session.delete_message("keep-1"), "delete succeeds after the cache recovers")
	check(not _ids(session).has("keep-1"), "recovered delete removes the bubble")
	session.queue_free()
	await process_frame


func _until(predicate: Callable, timeout_ms: int = 2000) -> bool:
	var deadline := Time.get_ticks_msec() + timeout_ms
	while not predicate.call() and Time.get_ticks_msec() < deadline:
		await process_frame
	return predicate.call()


func _message(id: String, role: String, text: String) -> Dictionary:
	return {
		"id": id, "id_source": "server", "role": role, "type": "text", "text": text,
		"timestamp": "2026-09-19 10:00:00", "status": "received", "code": "",
	}


func _local(id: String, kind: String, text: String, status: String, payload: Dictionary = {}) -> Dictionary:
	var message := {
		"id": id, "id_source": "local", "role": "user", "type": kind, "text": text,
		"timestamp": Time.get_unix_time_from_system(), "status": status, "code": "",
	}
	if not payload.is_empty():
		message.payload = payload
	return message


func _typed(rows: Array) -> Array[Dictionary]:
	var typed: Array[Dictionary] = []
	for row in rows:
		typed.append(row)
	return typed


func _ids(session: Node) -> Array:
	var ids: Array = []
	for message in session.get_messages():
		ids.append(str(message.id))
	return ids


func _find(session: Node, id: String) -> Dictionary:
	for message in session.get_messages():
		if str(message.id) == id:
			return message
	return {}
