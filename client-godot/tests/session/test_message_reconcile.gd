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


class FakeHistory extends Node:
	signal page_received(messages: Array[Dictionary])
	signal older_page(messages: Array[Dictionary])
	signal restore_page(messages: Array[Dictionary])
	signal boundary_ready
	signal state_changed(state: Dictionary)
	func get_state() -> Dictionary: return {"storage":"closed", "count":0, "incomplete":false}
	func start(_session: Dictionary) -> void: pass
	func stop() -> void: pass
	func load_older() -> void: pass
	func pause_catchup(_paused: bool) -> void: pass


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
	await _case_restore_keeps_pending_local(session)
	_case_idle_ignores(session)
	_case_latest_page_keeps_window_order()
	_case_latest_page_anchors_unknown_rows()
	_case_latest_page_appends_newer_window()
	_case_latest_page_prepends_before_local_only()
	_case_page_received_uses_in_place_merge()
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


## 重新登录时，首屏最新页只更新已有 UUID 的时间，不把缓存窗口重新排序。
## 回归：本地发送记录（图片 + 文字）曾被整页前插顶到最新位置。
func _case_latest_page_keeps_window_order() -> void:
	var session := _session()
	var window := [
		_message("s-old", "user", "更早的服务器消息"),
		_message("s-img", "user", ""),
		_message("s-text", "user", "给你看我的电脑壁纸哦"),
		_local("local-img", "image", ""),
		_local("local-text", "text", "给你看我的电脑壁纸哦"),
		_message("s-new", "assistant", "服务器最新回复"),
	]
	session._restore_page(_typed(window))
	session._latest_page(_typed([
		_message("s-old", "user", "更早的服务器消息"),
		_message("s-img", "user", ""),
		_message("s-text", "user", "给你看我的电脑壁纸哦"),
		_message("s-new", "assistant", "服务器最新回复"),
	]))
	check(_ids(session) == ["s-old", "s-img", "s-text", "local-img", "local-text", "s-new"], "latest page merges in place instead of prepending")
	check(_find(session, "local-text").status == "sent" and _find(session, "local-text").text == "给你看我的电脑壁纸哦", "latest page keeps the local send record untouched")
	session.queue_free()


## 缓存窗口缺了几条时，未知行插到下一个已知锚点之前，仍然贴着库里的顺序。
func _case_latest_page_anchors_unknown_rows() -> void:
	var session := _session()
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


## 缓存里只有更旧的服务器窗口时，最新页接在窗口之后，而不是压到最前面。
func _case_latest_page_appends_newer_window() -> void:
	var session := _session()
	session._restore_page(_typed([
		_message("old-1", "user", "旧一"),
		_message("old-2", "assistant", "旧二"),
	]))
	session._latest_page(_typed([
		_message("new-1", "user", "新一"),
		_message("new-2", "assistant", "新二"),
	]))
	check(_ids(session) == ["old-1", "old-2", "new-1", "new-2"], "a newer page follows the cached window")
	session.queue_free()


## 缓存里只有本机待发记录时，服务器历史仍排在本机记录之前。
func _case_latest_page_prepends_before_local_only() -> void:
	var session := _session()
	session._restore_page(_typed([_local("local-1", "text", "本机记录")]))
	session._latest_page(_typed([
		_message("h1", "assistant", "历史一"),
		_message("h2", "user", "历史二"),
	]))
	check(_ids(session) == ["h1", "h2", "local-1"], "history still precedes local-only records")
	session.queue_free()


## 接线回归：page_received 必须走原位合并，older_page 仍贴头。
func _case_page_received_uses_in_place_merge() -> void:
	var history := FakeHistory.new()
	var session = Session.new(Transport.new(), null, QuietMedia.new(), history)
	root.add_child(session)
	session._connection_changed({"phase": "ready", "code": ""})
	session._restore_page(_typed([
		_message("s1", "user", "一"),
		_local("local-1", "text", "本机"),
		_message("s2", "assistant", "二"),
	]))
	history.page_received.emit(_typed([
		_message("s1", "user", "一"),
		_message("s2", "assistant", "二"),
	]))
	check(_ids(session) == ["s1", "local-1", "s2"], "page_received merges in place")
	history.older_page.emit(_typed([_message("h0", "user", "更早")]))
	check(_ids(session) == ["h0", "s1", "local-1", "s2"], "older_page is still prepended")
	session.queue_free()


## 等待历史期间已产生的本地消息不能因为 restore_page 替换视图而消失。
func _case_restore_keeps_pending_local(session: Node) -> void:
	var local := _message("local-pending", "user", "发送中的消息")
	local.id_source = "local"
	local.status = "waiting_history"
	session._waiting_history = true
	session._pending_history[local.id] = {"type":"user_text", "payload":{"message":local.text}}
	session._accept_local(local)
	session._restore_page(_typed([
		_message("history-1", "assistant", "缓存一"),
		_message("history-2", "user", "缓存二"),
	]))
	check(_ids(session) == ["history-1", "history-2", "local-pending"], "restore keeps pending local message at the tail")
	check(_find(session, "local-pending").status == "waiting_history", "restore keeps pending delivery state")
	session._release_history_sends()
	check(_find(session, "local-pending").status == "failed", "offline release marks pending message failed instead of crashing")
	check(_ids(session).has("local-pending"), "failed release keeps the local message visible")


func _message(id: String, role: String, text: String) -> Dictionary:
	return {
		"id": id, "role": role, "type": "text", "text": text,
		"timestamp": 1700000000, "status": "received", "code": "",
	}


func _local(id: String, kind: String, text: String) -> Dictionary:
	return {
		"id": id, "id_source": "local", "role": "user", "type": kind, "text": text,
		"timestamp": 1700000000, "status": "sent", "code": "",
	}


func _session() -> Node:
	var session = Session.new(Transport.new(), null, QuietMedia.new())
	root.add_child(session)
	session._connection_changed({"phase": "ready", "code": ""})
	return session


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
