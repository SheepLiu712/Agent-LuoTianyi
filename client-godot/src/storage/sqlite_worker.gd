extends Node
## 数据库工作线程：连接只属于工作线程，主线程只搬运纯数据。
## 线程只做「运输」：取命令、调用仓储、投递结果。
## 重试、幂等、待写队列等业务语义都在 MessagePersistence，
## 所以这里没有失败重放逻辑，也没有 Node 树或纹理的访问。

signal stopped

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
var _running := false
var _stopped := false


func _init(factory: Callable) -> void:
	_factory = factory


func start() -> Dictionary:
	if _running:
		return _failure("STORAGE_RUNNING")
	_running = true
	_thread = Thread.new()
	if _thread.start(_run) != OK:
		_running = false
		return _failure("STORAGE_UNAVAILABLE")
	return _success()


## 未启动或正在关闭时立即失败，让调用方拿到确定的错误而不是无限等待。
func submit(operation: String, payload: Dictionary) -> Ticket:
	var ticket := Ticket.new()
	if not _running:
		ticket.settle(_failure("STORAGE_UNAVAILABLE"))
		return ticket
	_enqueue({"operation": operation, "payload": payload.duplicate(true), "ticket": ticket})
	return ticket


func is_running() -> bool:
	return _running


func pending_jobs() -> int:
	_mutex.lock()
	var size := _jobs.size()
	_mutex.unlock()
	return size


func begin_shutdown() -> void:
	if not _running:
		return
	_enqueue({"operation": "", "payload": {}, "ticket": Ticket.new()})


func wait_to_finish() -> void:
	if _thread != null:
		_thread.wait_to_finish()
		_thread = null
	_running = false
	_drain()
	if _stopped:
		return
	_stopped = true
	stopped.emit()


func _process(_delta: float) -> void:
	_drain()


func _exit_tree() -> void:
	begin_shutdown()
	wait_to_finish()


func _run() -> void:
	var repository: RefCounted = _factory.call()
	while true:
		_semaphore.wait()
		var job: Variant = _take_job()
		if job == null or str(job.operation).is_empty():
			break
		_results_push({"ticket": job.ticket, "result": repository.execute(str(job.operation), job.payload)})
	repository.close()


func _enqueue(job: Dictionary) -> void:
	_mutex.lock()
	_jobs.append(job)
	_mutex.unlock()
	_semaphore.post()


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
		entry.ticket.settle(entry.result)


static func _failure(code: String) -> Dictionary:
	return {"ok": false, "code": code, "data": {}}


static func _success(data: Dictionary = {}) -> Dictionary:
	return {"ok": true, "code": "OK", "data": data}
