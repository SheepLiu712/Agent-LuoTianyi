extends SceneTree
## 工作线程契约：命令按提交顺序执行、结果回到主线程、关闭后不再接受命令。
##
## 同时用真实仓储跑一遍，确认「连接只属于工作线程」在真实 SQLite 上成立。

const Worker = preload("res://src/storage/sqlite_worker.gd")
const Database = preload("res://src/storage/sqlite_history_database.gd")

var failures: Array[String] = []
var _root := ""


func _initialize() -> void:
	run.call_deferred()


func run() -> void:
	_root = "user://test-sqlite-worker-%d" % Time.get_ticks_usec()
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(_root))
	await _case_fifo()
	await _case_real_database()
	await _case_closed()
	print("SQLite worker: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func check(ok: bool, label: String) -> void:
	if ok:
		return
	failures.append(label)
	print("FAIL: ", label)


## 只用假仓储验证运输语义，不碰 SQLite。
func _case_fifo() -> void:
	var recorder := Recorder.new()
	var worker := Worker.new(func() -> RefCounted: return recorder)
	root.add_child(worker)
	check(worker.start().ok, "worker starts")
	var first: RefCounted = worker.submit("first", {})
	var second: RefCounted = worker.submit("second", {})
	var third: RefCounted = worker.submit("third", {})
	var results: Array = []
	for ticket in [first, second, third]:
		results.append(await ticket.wait())
	check(results.all(func(res): return res.ok), "every command reports ok")
	check(recorder.seen == ["first", "second", "third"], "commands run in submit order")
	worker.begin_shutdown()
	worker.wait_to_finish()
	check(recorder.seen.back() == "closed", "repository is closed on shutdown")
	check(not worker.is_running(), "worker stops")
	worker.queue_free()


## 真实仓储：open / 写入 / 读取都要跨线程完成。
func _case_real_database() -> void:
	var scope := ("c" + "0".repeat(64)).substr(0, 64)
	var worker := Worker.new(func() -> RefCounted: return Database.new())
	root.add_child(worker)
	worker.start()
	var opened: Dictionary = await worker.submit("open_scope", {"root": _root, "scope": scope}).wait()
	check(opened.ok, "worker opens a real database (%s)" % opened.code)
	var saved: Dictionary = await worker.submit("save_live", {
		"scope": scope,
		"message": {
			"id": "worker-1", "id_source": "local", "origin": "local", "role": "user",
			"type": "text", "text": "from thread", "timestamp": 1700000000,
			"status": "queued", "code": "",
		},
	}).wait()
	check(saved.ok, "worker writes through the thread (%s)" % saved.code)
	var read: Dictionary = await worker.submit("read_latest", {"scope": scope, "limit": 30}).wait()
	var rows: Array = read.get("data", {}).get("messages", [])
	check(rows.size() == 1 and str(rows[0].content) == "from thread", "worker reads back the write")
	var stale: Dictionary = await worker.submit("read_latest", {"scope": "d" + "0".repeat(63), "limit": 30}).wait()
	check(stale.code == "STALE_SCOPE", "foreign scope is rejected")
	worker.begin_shutdown()
	worker.wait_to_finish()
	worker.queue_free()


func _case_closed() -> void:
	var worker := Worker.new(func() -> RefCounted: return Recorder.new())
	var unstarted: Dictionary = await worker.submit("any", {}).wait()
	check(unstarted.code == "STORAGE_UNAVAILABLE", "submit before start fails fast")
	root.add_child(worker)
	worker.start()
	worker.begin_shutdown()
	worker.wait_to_finish()
	var late: Dictionary = await worker.submit("any", {}).wait()
	check(late.code == "STORAGE_UNAVAILABLE", "submit after shutdown fails fast")
	worker.queue_free()


## 记录命令顺序的假仓储；只在工作线程内被调用。
class Recorder:
	extends RefCounted
	var seen: Array = []

	func execute(operation: String, _payload: Dictionary) -> Dictionary:
		seen.append(operation)
		return {"ok": true, "code": "OK", "data": {"operation": operation}}

	func close() -> void:
		seen.append("closed")
