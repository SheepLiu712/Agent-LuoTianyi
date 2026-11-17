extends RefCounted
## 账号作用域的唯一打开者：聊天与动态共用同一条工作线程连接。
## ensure_open 幂等：同一 root + scope 已打开时直接返回元数据，不重复 open/close。

var _worker: Node
var _root := ""
var _scope := ""
var _metadata: Dictionary = {}


func _init(worker: Node = null) -> void:
	_worker = worker


func attach(worker: Node) -> void:
	_worker = worker
	_clear_state()


func worker() -> Node:
	return _worker


func is_open() -> bool:
	return _worker != null and _worker.is_running() and not _scope.is_empty()


func scope() -> String:
	return _scope


func metadata() -> Dictionary:
	return _metadata.duplicate(true)


func ensure_open(root: String, scope: String) -> Dictionary:
	if _worker == null or not _worker.is_running():
		return _failure("STORAGE_UNAVAILABLE")
	if scope.is_empty() or root.is_empty():
		return _failure("INVALID_INPUT")
	if _scope == scope and _root == root and not _metadata.is_empty():
		return _success(_metadata)
	var result: Dictionary = await _worker.submit("open_scope", {"root": root, "scope": scope}).wait()
	if not result.ok:
		_clear_state()
		return result
	_root = root
	_scope = scope
	_metadata = result.data.duplicate(true)
	return result


func close_scope() -> Dictionary:
	if _worker == null or not _worker.is_running():
		_clear_state()
		return _success()
	if _scope.is_empty():
		_clear_state()
		return _success()
	var result: Dictionary = await _worker.submit("close_scope", {"scope": _scope}).wait()
	_clear_state()
	return result


func reset_scope() -> Dictionary:
	if _worker == null or not _worker.is_running():
		return _failure("STORAGE_UNAVAILABLE")
	if _scope.is_empty():
		return _failure("INVALID_INPUT")
	var result: Dictionary = await _worker.submit("reset_scope", {"scope": _scope}).wait()
	if result.ok:
		_metadata = result.data.duplicate(true)
	return result


func _clear_state() -> void:
	_root = ""
	_scope = ""
	_metadata = {}


static func _failure(code: String) -> Dictionary:
	return {"ok": false, "code": code, "data": {}}


static func _success(data: Dictionary = {}) -> Dictionary:
	return {"ok": true, "code": "OK", "data": data}
