extends Node
## 数据库工作线程：连接只属于工作线程，主线程只搬运纯数据。
## 线程只做「运输」：取命令、调用仓储、投递结果。
## 重试、幂等、待写队列等业务语义都在 MessagePersistence，
## 所以这里没有失败重放逻辑，也没有 Node 树或纹理的访问。

signal stopped

const Schema = preload("res://src/storage/log_schema.gd")

## 一次命令的凭据：主线程 await 它，工作线程只会投递结果。
class Ticket:
	extends RefCounted
	signal resolved(result: Dictionary)

	var result: Dictionary = {}
	var done := false

	func settle(value: Dictionary) -> void:
		if done:
			return
		result = value
		done = true
		resolved.emit(value)

	func wait() -> Dictionary:
		if not done:
			await resolved
		return result


var _thread: Thread
var _mutex := Mutex.new()
var _semaphore := Semaphore.new()
var _jobs: Array = []
var _results: Array = []
var _factory: Callable
var _logger: RefCounted
var _running := false
var _accepting := false
var _stopped := false


func _init(factory: Callable, logger: RefCounted = null) -> void:
	_factory = factory
	_logger = logger


func start() -> Dictionary:
	if _running:
		return _failure("STORAGE_RUNNING")
	_running = true
	_accepting = true
	_thread = Thread.new()
	if _thread.start(_run) != OK:
		_running = false
		_accepting = false
		return _failure("STORAGE_UNAVAILABLE")
	return _success()


## 未启动或正在关闭时立即失败，让调用方拿到确定的错误而不是无限等待。
func submit(operation: String, payload: Dictionary) -> Ticket:
	var ticket := Ticket.new()
	_mutex.lock()
	var available := _running and _accepting
	if available:
		_jobs.append({"operation": operation, "payload": payload.duplicate(true), "ticket": ticket})
	_mutex.unlock()
	if not available:
		ticket.settle(_failure("STORAGE_UNAVAILABLE"))
		return ticket
	_semaphore.post()
	return ticket


func is_running() -> bool:
	return _running


func pending_jobs() -> int:
	_mutex.lock()
	var size := _jobs.size()
	_mutex.unlock()
	return size


func begin_shutdown() -> void:
	_mutex.lock()
	if not _running or not _accepting:
		_mutex.unlock()
		return
	# 关闭标志与哨兵入队必须在同一临界区：之后到达的提交立即失败，
	# 不能排在哨兵后面永远不被工作线程取走。
	_accepting = false
	_jobs.append({"operation": "", "payload": {}, "ticket": Ticket.new()})
	_mutex.unlock()
	_semaphore.post()


func wait_to_finish() -> void:
	if _thread != null:
		_thread.wait_to_finish()
		_thread = null
	_mutex.lock()
	_running = false
	_accepting = false
	_mutex.unlock()
	_drain()
	if _stopped:
		return
	_stopped = true
	stopped.emit()


func _process(_delta: float) -> void:
	if _results.is_empty():
		return
	_drain()


func _exit_tree() -> void:
	begin_shutdown()
	wait_to_finish()


func _run() -> void:
	var repository: RefCounted = _factory.call()
	if repository == null:
		_fail_remaining("STORAGE_UNAVAILABLE")
		return
	while true:
		_semaphore.wait()
		var job: Variant = _take_job()
		if job == null or str(job.operation).is_empty():
			break
		var started := Time.get_ticks_usec()
		var result: Dictionary = repository.execute(str(job.operation), job.payload)
		result.duration_ms = int((Time.get_ticks_usec() - started) / 1000)
		result.operation = str(job.operation)
		_results_push({"ticket": job.ticket, "result": result})
	repository.close()


## 线程退出时仍有排队任务（异常/强制关闭）：主动结算，主线程不能无限 await。
func _fail_remaining(code: String) -> void:
	_mutex.lock()
	var remaining := _jobs.duplicate()
	_jobs.clear()
	_running = false
	_accepting = false
	_mutex.unlock()
	for job in remaining:
		if job.has("ticket"):
			_results_push({"ticket": job.ticket, "result": _failure(code)})


func _take_job() -> Variant:
	_mutex.lock()
	var job: Variant = null if _jobs.is_empty() else _jobs.pop_front()
	_mutex.unlock()
	return job


func _results_push(entry: Dictionary) -> void:
	_mutex.lock()
	_results.append(entry)
	_mutex.unlock()


## 只在主线程调用：把工作线程的结果交回等待者。
func _drain() -> void:
	_mutex.lock()
	var entries := _results.duplicate()
	_results.clear()
	_mutex.unlock()
	for entry in entries:
		_log_result(entry.result)
		entry.ticket.settle(entry.result)

func _log_result(result: Dictionary) -> void:
	if _logger == null:
		return
	var operation := str(result.get("operation", "unknown"))
	var outcome := "success" if result.get("ok", false) else "failure"
	var code := str(result.get("code", "UNKNOWN"))
	var duration := int(result.get("duration_ms", 0))
	var transaction: Variant = result.get("transaction")
	var trace_id := ""
	if transaction is Dictionary:
		trace_id = str(transaction.get("trace_id", ""))
	if trace_id.is_empty():
		trace_id = Schema.new_trace_id("db")
	_logger.log_performance("performance_sqlite", {"operation":operation, "outcome":outcome,
		"duration_ms":duration, "queue_depth":pending_jobs(), "code":code, "trace_id":trace_id})
	if transaction is Dictionary:
		_logger.log_transaction("transaction_sqlite", {"transaction_id":str(transaction.get("transaction_id", trace_id)),
			"scope":"sqlite", "operation":str(transaction.get("operation", operation)),
			"phase":str(transaction.get("phase", "rolled_back")), "outcome":str(transaction.get("outcome", outcome)),
			"duration_ms":int(transaction.get("duration_ms", duration)), "trace_id":trace_id, "code":code})
	if code == "STALE_SCOPE":
		_logger.log_security("security_scope", {"action":"db_scope_guard", "outcome":"denied", "reason_code":"STALE_SCOPE",
			"subject":Schema.hash_subject("", "db"), "trace_id":trace_id})


static func _failure(code: String) -> Dictionary:
	return {"ok": false, "code": code, "data": {}}


static func _success(data: Dictionary = {}) -> Dictionary:
	return {"ok": true, "code": "OK", "data": data}
