extends RefCounted
## 消息持久化门面：会话层唯一知道「要写库」的地方。
## 只依赖注入进来的 worker（Node）与纯数据命令，不 import 任何具体存储实现；
## 数据库行到 UI DTO 的映射也只在这里做一次，避免两处口径漂移。
## 写入是「提交即返回」；任何一条命令失败一次就当场放弃，不重试、不重放，
## 只把丢弃条数记下来，由调用方决定要不要提示。

const DEFAULT_LIMIT := 30

var _worker: Node
var _scope := ""
var _inflight: Array = []
var _pending: Array = []
var _discarded := 0


func _init(worker: Node = null) -> void:
	_worker = worker


func attach(worker: Node) -> void:
	_worker = worker


func is_open() -> bool:
	return not _scope.is_empty() and _worker != null and _worker.is_running()


func scope() -> String:
	return _scope


func discarded_count() -> int:
	return _discarded


func open_scope(root: String, scope: String) -> Dictionary:
	if _worker == null:
		return _failure("STORAGE_UNAVAILABLE")
	if scope != _scope:
		# 换账号前把旧作用域还没提交的命令各试一次；失败的当场丢弃，不跨账号重放。
		await drain_pending_writes()
		_discard_pending()
	var result: Dictionary = await _worker.submit("open_scope", {"root": root, "scope": scope}).wait()
	if result.ok:
		_scope = scope
	return result


func close_scope() -> Dictionary:
	if not is_open():
		_scope = ""
		return _success()
	var result: Dictionary = await _worker.submit("close_scope", {}).wait()
	_scope = ""
	return result


func read_latest(limit: int = DEFAULT_LIMIT) -> Dictionary:
	return await _read("read_latest", {"scope": _scope, "limit": limit})


func read_before(anchor_id: String, limit: int = DEFAULT_LIMIT) -> Dictionary:
	return await _read("read_before", {"scope": _scope, "anchor_id": anchor_id, "limit": limit})


func read_sync_state() -> Dictionary:
	return await _read("read_sync_state", {"scope": _scope})


func _read(operation: String, payload: Dictionary) -> Dictionary:
	if not is_open():
		return _failure("STORAGE_UNAVAILABLE")
	var result: Dictionary = await _worker.submit(operation, payload).wait()
	if not result.ok:
		return result
	return _success({
		"messages": _convert(result.data.get("messages", [])),
		"order_revision": int(result.data.get("order_revision", 0)),
		"meta": result.data,
	})


func save_live(message: Dictionary) -> void:
	_submit("save_live", {"scope": _scope, "message": message.duplicate(true)})


func save_history(page: Dictionary, context: Dictionary) -> void:
	_submit("save_history", {"scope": _scope, "page": page, "context": context})


## 对账写入需要结果决定「要不要重渲染」，所以这里等待而不是进待写队列。
## 库没打开就直接失败：不写库就不合并内存，避免界面与库分叉。
func save_reconcile(rows: Array) -> Dictionary:
	if not is_open():
		return _failure("STORAGE_UNAVAILABLE")
	return await _worker.submit("save_reconcile", {
		"scope": _scope, "rows": rows.duplicate(true),
	}).wait()


## 启动/历史页落库后对账本地 uncertain 副本：只返回被软标记的本地 id。
func reconcile_delivery() -> Dictionary:
	if not is_open():
		return _failure("STORAGE_UNAVAILABLE")
	return await _worker.submit("reconcile_delivery", {"scope": _scope}).wait()


func record_attempt(message_id: String, wire_id: String) -> void:
	_submit("record_attempt", {
		"scope": _scope,
		"attempt_id": "attempt:%s" % message_id,
		"message_id": message_id,
		"wire_id": wire_id,
		"state": "sending",
		"ever_sent": true,
	})


func update_attempt(message_id: String, wire_id: String, state: String, code: String) -> void:
	_submit("update_attempt", {
		"scope": _scope,
		"message_id": message_id,
		"wire_id": wire_id,
		"state": state,
		"error_code": code,
		"ever_sent": true,
	})


func _submit(operation: String, payload: Dictionary) -> void:
	if _worker == null or not _worker.is_running():
		_pending.append({"operation": operation, "payload": payload, "ticket": null})
		return
	_inflight.append({"operation": operation, "payload": payload, "ticket": _worker.submit(operation, payload)})


## 收口：worker 里还没落地的命令先结算，待写队列各试一次。
## 返回 dropped 表示本次放弃了几条；放弃过的写入不会留下重试队列。
func flush() -> Dictionary:
	if _worker == null or not _worker.is_running():
		return _failure("STORAGE_UNAVAILABLE")
	var before := _discarded
	await _worker.submit("flush", {"scope": _scope}).wait()
	_harvest()
	await drain_pending_writes()
	return _success({"dropped": _discarded - before})


## 待写队列里的命令只试一次：失败立刻丢弃，绝不回到队列里等下一次。
func drain_pending_writes() -> Dictionary:
	var queue := _pending
	_pending = []
	for command in queue:
		var result: Dictionary = await _worker.submit(str(command.operation), command.payload).wait()
		if not result.ok:
			_discarded += 1
	return _success()


func unsaved_count() -> int:
	_harvest()
	return _pending.size()


## 结算在途命令：失败的直接计入丢弃，不进待写队列，所以不会再有第二次尝试。
func _harvest() -> void:
	var still_running: Array = []
	for entry in _inflight:
		if not _settled(entry):
			still_running.append(entry)
			continue
		if not entry.ticket.result.get("ok", false):
			_discarded += 1
	_inflight = still_running


func _settled(entry: Dictionary) -> bool:
	return entry.ticket != null and entry.ticket.done


func _discard_pending() -> void:
	_discarded += _pending.size() + _inflight.size()
	_pending = []
	_inflight = []


func _convert(rows: Array) -> Array:
	var messages: Array = []
	for row in rows:
		messages.append(_row_to_message(row))
	return messages


## 服务器侧角色名是 agent，UI 侧统一用 assistant。
func _row_to_message(row: Dictionary) -> Dictionary:
	return {
		"id": str(row.get("message_id", "")),
		"id_source": str(row.get("id_source", "server")),
		"role": "assistant" if str(row.get("source", "user")) == "agent" else str(row.get("source", "user")),
		"type": str(row.get("message_type", "text")),
		"text": str(row.get("content", "")),
		"timestamp": _timestamp_of(row.get("timestamp_json")),
		"status": str(row.get("delivery_state", "received")),
		"code": str(row.get("error_code", "")),
		"stream_complete": int(row.get("stream_complete", 1)) == 1,
		"restored": true,
	}


static func _timestamp_of(raw: Variant) -> Variant:
	if not raw is String:
		return raw
	var parsed: Variant = JSON.parse_string(raw)
	return parsed if parsed != null else 0


static func _failure(code: String) -> Dictionary:
	return {"ok": false, "code": code, "data": {}}


static func _success(data: Dictionary = {}) -> Dictionary:
	return {"ok": true, "code": "OK", "data": data}
