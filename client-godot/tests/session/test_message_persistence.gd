extends SceneTree
## 持久化门面：往来真实库一趟、失败写入只放弃一次、切换账号不重放旧命令。

const Worker = preload("res://src/storage/sqlite_worker.gd")
const Database = preload("res://src/storage/sqlite_history_database.gd")
const Persistence = preload("res://src/session/message_persistence.gd")

var failures: Array[String] = []
var _root := ""


func _initialize() -> void:
	run.call_deferred()


func run() -> void:
	_root = "user://test-persistence-%d" % Time.get_ticks_usec()
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(_root))
	await _case_roundtrip()
	await _case_pending()
	await _case_switch()
	await _case_reconcile()
	await _case_reconcile_unopened()
	print("Message persistence: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func check(ok: bool, label: String) -> void:
	if ok:
		return
	failures.append(label)
	print("FAIL: ", label)


func _case_roundtrip() -> void:
	var scope := ("a" + "0".repeat(64)).substr(0, 64)
	var worker := Worker.new(func() -> RefCounted: return Database.new())
	root.add_child(worker)
	worker.start()
	var persistence := Persistence.new(worker)
	var opened: Dictionary = await persistence.open_scope(_root, scope)
	check(opened.ok, "open scope through the facade (%s)" % opened.code)
	persistence.save_live(_message("local-1", "user", "hello"))
	persistence.save_live(_message("reply-1", "assistant", "hi"))
	var flushed: Dictionary = await persistence.flush()
	check(flushed.ok, "flush reports saved state (%s)" % flushed.code)
	check(persistence.unsaved_count() == 0, "no unsaved commands after flush")
	var read: Dictionary = await persistence.read_latest(30)
	var messages: Array = read.get("data", {}).get("messages", [])
	check(messages.size() == 2, "both messages round trip")
	check(_role(messages, "reply-1") == "assistant", "server role agent maps to assistant")
	check(_role(messages, "local-1") == "user", "user role is preserved")
	check(_status(messages, "local-1") == "queued", "delivery state round trips")
	persistence.record_attempt("local-1", "wire-1")
	persistence.update_attempt("local-1", "wire-1", "sent", "")
	var settled: Dictionary = await persistence.flush()
	check(settled.ok, "attempt updates flush")
	var again: Dictionary = await persistence.read_latest(30)
	check(_status(again.get("data", {}).get("messages", []), "local-1") == "sent", "attempt update reaches the message")
	await persistence.close_scope()
	worker.begin_shutdown()
	worker.wait_to_finish()
	worker.queue_free()


## 写入只尝试一次：失败当场放弃，不进待写队列，也不在 flush 时重放。
func _case_pending() -> void:
	var worker := FakeWorker.new()
	root.add_child(worker)
	worker.fail.append("save_live")
	var persistence := Persistence.new(worker)
	persistence.save_live(_message("local-2", "user", "text"))
	var flushed: Dictionary = await persistence.flush()
	check(flushed.ok, "a failed write never blocks the flush (%s)" % flushed.code)
	check(int(flushed.data.get("dropped", 0)) == 1, "flush reports the abandoned write")
	check(persistence.unsaved_count() == 0, "a failed write is not kept for another try")
	check(persistence.discarded_count() == 1, "the abandoned write is counted once")
	check(worker.order == ["save_live", "flush"], "the failed write is never replayed")
	worker.queue_free()


func _case_switch() -> void:
	var worker := FakeWorker.new()
	root.add_child(worker)
	worker.fail.append("save_live")
	var persistence := Persistence.new(worker)
	persistence.save_live(_message("local-3", "user", "text"))
	await persistence.open_scope(_root, ("b" + "0".repeat(64)).substr(0, 64))
	check(persistence.discarded_count() == 1, "a failed write is abandoned instead of being replayed on switch")
	check(persistence.unsaved_count() == 0, "nothing is left pending after the switch")
	check(worker.order == ["save_live", "open_scope"], "the failed write is not retried before the new scope opens")
	worker.queue_free()


## 对账写入必须等结果：新增行落库、页内重复只留一条、已知行不重复插入。
func _case_reconcile() -> void:
	var scope := ("c" + "0".repeat(64)).substr(0, 64)
	var worker := Worker.new(func() -> RefCounted: return Database.new())
	root.add_child(worker)
	worker.start()
	var persistence := Persistence.new(worker)
	check((await persistence.open_scope(_root, scope)).ok, "open scope for reconcile")
	persistence.save_live(_message("local-1", "user", "hello"))
	persistence.save_live(_message("reply-1", "assistant", "hi"))
	check((await persistence.flush()).ok, "live rows are saved before reconcile")
	var rows: Array = [
		{"uuid": "reply-1", "source": "agent", "type": "text", "content": "hi", "timestamp": 1700000001},
		{"uuid": "srv-1", "source": "user", "type": "text", "content": "one", "timestamp": 1700000002},
		{"uuid": "srv-2", "source": "agent", "type": "text", "content": "two", "timestamp": 1700000003},
		{"uuid": "srv-2", "source": "agent", "type": "text", "content": "two", "timestamp": 1700000003},
	]
	var saved: Dictionary = await persistence.save_reconcile(rows)
	check(saved.ok, "reconcile write succeeds (%s)" % saved.code)
	check(int(saved.data.inserted) == 2, "only unknown rows are inserted")
	check(int(saved.data.duplicates) == 1, "duplicate uuid inside one page is reported")
	check(str(saved.data.position) == "tail", "server rows extend the existing timeline")
	var read: Dictionary = await persistence.read_latest(30)
	var messages: Array = read.get("data", {}).get("messages", [])
	check(messages.size() == 4, "reconcile leaves no duplicate row")
	check(str(messages[-1].id) == "srv-2", "reconciled rows keep the server order")
	check(_status(messages, "local-1") == "queued", "reconcile does not rewrite local delivery state")
	check(persistence.unsaved_count() == 0, "reconcile does not leave pending commands")
	await persistence.close_scope()
	worker.begin_shutdown()
	worker.wait_to_finish()
	worker.queue_free()


## 库没打开时对账直接失败，且不能把失败命令塞进待写队列。
func _case_reconcile_unopened() -> void:
	var persistence := Persistence.new(null)
	var saved: Dictionary = await persistence.save_reconcile([
		{"uuid": "srv-1", "source": "user", "type": "text", "content": "one", "timestamp": 1},
	])
	check(not saved.ok and saved.code == "STORAGE_UNAVAILABLE", "unopened storage refuses reconcile (%s)" % saved.code)
	check(persistence.unsaved_count() == 0, "refused reconcile is not queued as pending")


# ---------------------------------------------------------------- 辅助

func _message(id: String, role: String, text: String) -> Dictionary:
	return {
		"id": id, "id_source": "local" if role == "user" else "server",
		"origin": "local" if role == "user" else "live", "role": role, "type": "text",
		"text": text, "timestamp": 1700000000, "status": "queued", "code": "",
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


## 只实现门面需要的两个方法：可运行状态与提交。
class FakeWorker:
	extends Node
	var fail: Array = []
	var order: Array = []
	var running := true

	func is_running() -> bool:
		return running

	func submit(operation: String, _payload: Dictionary) -> RefCounted:
		order.append(operation)
		var ticket := FakeTicket.new()
		var rejected: bool = operation in fail
		ticket.settle({
			"ok": not rejected,
			"code": "CACHE_SQL_FAILED" if rejected else "OK",
			"data": {"messages": []},
		})
		return ticket


class FakeTicket:
	extends RefCounted
	signal resolved(result: Dictionary)
	var result: Dictionary = {}
	var done := false

	func settle(value: Dictionary) -> void:
		result = value
		done = true
		resolved.emit(value)

	func wait() -> Dictionary:
		if not done:
			await resolved
		return result
