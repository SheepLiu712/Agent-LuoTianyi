extends SceneTree
## 聊天持久化门面：本地尾部、历史页、上翻与账号切换。

const Worker = preload("res://src/storage/sqlite_worker.gd")
const Database = preload("res://src/storage/sqlite_history_database.gd")
const ScopeSession = preload("res://src/storage/scope_session.gd")
const Persistence = preload("res://src/session/message_persistence.gd")

var failures: Array[String] = []
var _root := ""


func _initialize() -> void:
	run.call_deferred()


func run() -> void:
	_root = "user://test-persistence-%d" % Time.get_ticks_usec()
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(_root))
	await _case_roundtrip()
	await _case_page_and_before()
	await _case_scope_switch()
	print("Message persistence: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func check(ok: bool, label: String) -> void:
	if ok:
		return
	failures.append(label)
	print("FAIL: ", label)


func _scope(tag: String) -> String:
	return (tag + "0".repeat(64)).substr(0, 64)


func _boot() -> Dictionary:
	var worker := Worker.new(func() -> RefCounted: return Database.new())
	root.add_child(worker)
	worker.start()
	var session := ScopeSession.new(worker)
	var persistence := Persistence.new(session)
	return {"worker": worker, "session": session, "persistence": persistence}


func _stop(context: Dictionary) -> void:
	await context.persistence.close_scope()
	context.worker.begin_shutdown()
	context.worker.wait_to_finish()
	context.worker.queue_free()


func _local(id: String, role: String, text: String, status: String) -> Dictionary:
	return {
		"id": id, "id_source": "local", "origin": "local", "role": role,
		"type": "text", "text": text,
		"timestamp": Time.get_unix_time_from_system(),
		"status": status, "code": "", "stream_complete": true,
	}


func _role(messages: Array, id: String) -> String:
	for message in messages:
		if str(message.id) == id:
			return str(message.role)
	return ""


func _status(messages: Array, id: String) -> String:
	for message in messages:
		if str(message.id) == id:
			return str(message.status)
	return ""


func _case_roundtrip() -> void:
	var context := _boot()
	var scope := _scope("a")
	var opened: Dictionary = await context.persistence.open_scope(_root, scope)
	check(opened.ok, "open scope through the facade (%s)" % opened.code)
	var entry := {"event": "user_text", "payload": {"message": "hello"}}
	check((await context.persistence.save_local(_local("local-1", "user", "hello", "pending"), entry)).ok, "save user tail")
	check((await context.persistence.save_local(_local("reply-1", "assistant", "hi", "received"))).ok, "save assistant tail")
	var read: Dictionary = await context.persistence.read_latest(30)
	var messages: Array = read.data.messages
	check(messages.size() == 2, "both tail rows round trip")
	check(_role(messages, "reply-1") == "assistant", "agent role maps to assistant on the way out")
	check(_status(messages, "local-1") == "pending", "delivery state round trips")
	check(str(messages[0].payload.event) == "user_text", "send intent is exposed to the session")
	check((await context.persistence.update_local("local-1", {"state": "sent"})).ok, "state update")
	var again: Dictionary = await context.persistence.read_latest(30)
	check(_status(again.data.messages, "local-1") == "sent", "state update reaches the read path")
	check((await context.persistence.flush()).ok, "flush succeeds")
	check(context.persistence.unsaved_count() == 0, "flush leaves nothing unsaved")
	await _stop(context)


func _server_rows(seed: String, start: int, count: int) -> Array:
	var rows: Array = []
	for index in range(start, start + count):
		rows.append({
			"uuid": "%s-%d" % [seed, index],
			"source": "user" if index % 2 == 0 else "agent",
			"type": "text",
			"content": "record %d" % index,
			"timestamp": "2026-09-19 %02d:%02d:%02d" % [index / 3600 % 24, index / 60 % 60, index % 60],
		})
	return rows


func _ids(messages: Array) -> Array:
	return messages.map(func(message): return str(message.id))


func _case_page_and_before() -> void:
	var context := _boot()
	var scope := _scope("b")
	await context.persistence.open_scope(_root, scope)
	var saved: Dictionary = await context.persistence.save_page(
		{"start_index": 0, "history": _server_rows("s", 0, 60)},
		{"direction": "initial"})
	check(saved.ok, "save initial page (%s)" % saved.code)
	check(int(saved.data.baseline_index) == 59, "baseline index comes from the first page")
	await context.persistence.save_local(_local("tail-1", "user", "tail", "failed"))
	var latest: Dictionary = await context.persistence.read_latest(30)
	check(latest.data.messages.size() == 31, "latest window appends the local tail")
	check(str(latest.data.messages[-1].id) == "tail-1", "local tail stays at the end")
	var before: Dictionary = await context.persistence.read_before("s-30", 30)
	check(_ids(before.data.messages) == _range_ids("s", 0, 30), "older server page")
	var from_tail: Dictionary = await context.persistence.read_before("tail-1", 30)
	check(from_tail.data.messages.size() == 30, "paging up from the tail fills from server history")
	check(str(from_tail.data.messages[0].id) == "s-30" and str(from_tail.data.messages[-1].id) == "s-59",
		"tail paging returns the newest server rows in ascending order")
	await _stop(context)


func _range_ids(seed: String, start: int, count: int) -> Array:
	var ids: Array = []
	for index in range(start, start + count):
		ids.append("%s-%d" % [seed, index])
	return ids


func _case_scope_switch() -> void:
	var context := _boot()
	var first := _scope("c")
	var second := _scope("d")
	await context.persistence.open_scope(_root, first)
	await context.persistence.save_local(_local("private-1", "user", "first account", "pending"))
	var switched: Dictionary = await context.persistence.open_scope(_root, second)
	check(switched.ok, "switch to a second scope")
	var read: Dictionary = await context.persistence.read_latest(30)
	check(read.ok and read.data.messages.is_empty(), "second scope starts empty")
	var stale: Dictionary = await context.session.worker().submit("read_latest", {
		"scope": first, "limit": 30,
	}).wait()
	check(not stale.ok and stale.code == "STALE_SCOPE", "old scope is rejected after the switch")
	await _stop(context)
