extends SceneTree
## 对账页并入内存：锚点定位、贴尾/贴头、同 id 不重复、本地状态不被覆盖。

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


func run() -> void:
	var session := Session.new(Transport.new(), null, QuietMedia.new())
	root.add_child(session)
	session._connection_changed({"phase": "ready", "code": ""})
	_case_tail_anchor(session)
	_case_head(session)
	_case_duplicates(session)
	_case_local_state_kept(session)
	_case_idle_ignores(session)
	session.queue_free()
	await process_frame
	print("Message reconcile: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func check(ok: bool, label: String) -> void:
	if ok:
		return
	failures.append(label)
	print("FAIL: ", label)


## 页内已有 id 当锚点：未知块落在锚点之后，顺序与 timeline_order 一致。
func _case_tail_anchor(session: Node) -> void:
	session._history_page(_typed([_message("a", "assistant", "one"), _message("b", "assistant", "two")]))
	session._reconcile_page(_typed([
		_message("b", "assistant", "two"),
		_message("new-1", "user", "three"),
		_message("new-2", "assistant", "four"),
	]), "tail")
	check(_ids(session) == ["a", "b", "new-1", "new-2"], "tail reconcile inserts after the page anchor")


## 没有任何锚点时贴尾：服务器页整体追加到当前窗口之后。
func _case_head(session: Node) -> void:
	session._reconcile_page(_typed([_message("tail-1", "user", "five")]), "tail")
	check(_ids(session) == ["a", "b", "new-1", "new-2", "tail-1"], "unmatched tail page is appended")
	session._reconcile_page(_typed([_message("head-1", "user", "zero")]), "head")
	check(_ids(session)[0] == "head-1", "head reconcile is placed before the window")


## 重复下发同一页不会产生第二条气泡。
func _case_duplicates(session: Node) -> void:
	var before := _ids(session)
	session._reconcile_page(_typed([
		_message("head-1", "user", "zero"),
		_message("new-1", "user", "three"),
		_message("new-2", "assistant", "four"),
	]), "tail")
	check(_ids(session) == before, "repeating the same page changes nothing")
	check(_unique_count(session) == session.get_messages().size(), "no duplicate id in the window")


## 本地未确认消息的正文与状态不被历史副本覆盖。
func _case_local_state_kept(session: Node) -> void:
	var local := _message("local-1", "user", "重庆")
	local.status = "uncertain"
	local.code = "DELIVERY_UNCERTAIN"
	session._accept_local(local)
	session._reconcile_page(_typed([
		_message("local-1", "user", "服务器副本"),
		_message("srv-copy", "user", "重庆"),
	]), "tail")
	var kept := _find(session, "local-1")
	check(str(kept.text) == "重庆" and str(kept.status) == "uncertain", "local copy keeps its text and delivery state")
	check(_ids(session)[-1] == "srv-copy", "server copy is appended as a distinct record")
	check(_ids(session).find("local-1") < _ids(session).find("srv-copy"), "local record stays before its server copy")


## 未登录/认证被拒时不得把对账结果塞进空窗口。
func _case_idle_ignores(session: Node) -> void:
	var before: int = session.get_messages().size()
	session._connection_changed({"phase": "auth_rejected", "code": "AUTH_REJECTED"})
	session._reconcile_page(_typed([_message("late", "user", "late")]), "tail")
	check(session.get_messages().size() == before, "reconcile is ignored outside a live session")


func _message(id: String, role: String, text: String) -> Dictionary:
	return {
		"id": id, "role": role, "type": "text", "text": text,
		"timestamp": 1700000000, "status": "received", "code": "",
	}


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


func _unique_count(session: Node) -> int:
	var seen := {}
	for message in session.get_messages():
		seen[str(message.id)] = true
	return seen.size()


func _find(session: Node, id: String) -> Dictionary:
	for message in session.get_messages():
		if str(message.id) == id:
			return message
	return {}
