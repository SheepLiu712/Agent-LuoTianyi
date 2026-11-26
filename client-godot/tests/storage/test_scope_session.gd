extends SceneTree
## ScopeSession：同一作用域幂等打开，聊天与动态共享同一条连接。

const ScopeSession = preload("res://src/storage/scope_session.gd")

var failures: Array[String] = []


class Ticket:
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


class CountingWorker extends Node:
	var opens := 0
	var closes := 0
	var running := true

	func is_running() -> bool:
		return running

	func submit(operation: String, payload: Dictionary) -> RefCounted:
		var ticket := Ticket.new()
		if operation == "open_scope":
			opens += 1
			ticket.settle({
				"ok": true, "code": "OK",
				"data": {"scope": payload.scope, "next_end": -1, "baseline_index": -1, "revision": 1},
			})
		elif operation == "close_scope":
			closes += 1
			ticket.settle({"ok": true, "code": "OK", "data": {}})
		else:
			ticket.settle({"ok": false, "code": "UNKNOWN_STORAGE_OPERATION", "data": {}})
		return ticket


func _initialize() -> void:
	run.call_deferred()


func run() -> void:
	await _case_idempotent()
	await _case_unavailable()
	print("Scope session: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func check(ok: bool, label: String) -> void:
	if ok:
		return
	failures.append(label)
	print("FAIL: ", label)


func _scope(tag: String) -> String:
	return (tag + "0".repeat(64)).substr(0, 64)


func _case_idempotent() -> void:
	var worker := CountingWorker.new()
	root.add_child(worker)
	var session := ScopeSession.new(worker)
	var first := _scope("a")
	var second := _scope("b")
	var opened: Dictionary = await session.ensure_open("user://scope-test", first)
	check(opened.ok, "first open succeeds")
	check(worker.opens == 1, "first open reaches the worker once")
	check(session.is_open() and session.scope() == first, "session reports the active scope")
	var again: Dictionary = await session.ensure_open("user://scope-test", first)
	check(again.ok and worker.opens == 1, "same scope does not reopen the connection")
	check(str(session.metadata().scope) == first, "metadata is cached for the same scope")
	var switched: Dictionary = await session.ensure_open("user://scope-test", second)
	check(switched.ok and worker.opens == 2, "a different scope opens exactly once")
	check(session.scope() == second, "scope switches to the new account")
	await session.close_scope()
	check(worker.closes == 1 and not session.is_open(), "close releases the scope")
	var reopened: Dictionary = await session.ensure_open("user://scope-test", second)
	check(reopened.ok and worker.opens == 3, "reopen after close is allowed")
	worker.queue_free()


func _case_unavailable() -> void:
	var worker := CountingWorker.new()
	worker.running = false
	root.add_child(worker)
	var session := ScopeSession.new(worker)
	var result: Dictionary = await session.ensure_open("user://scope-test", _scope("c"))
	check(not result.ok and result.code == "STORAGE_UNAVAILABLE", "stopped worker is unavailable")
	var missing := ScopeSession.new(null)
	var none: Dictionary = await missing.ensure_open("user://scope-test", _scope("d"))
	check(not none.ok and none.code == "STORAGE_UNAVAILABLE", "missing worker is unavailable")
	worker.queue_free()
