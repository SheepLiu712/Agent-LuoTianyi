extends RefCounted
## 聊天持久化门面：会话层唯一知道「要写库」的地方。
## 关键写操作（本地尾部、历史页、状态流转）都返回结果，调用方决定失败处理；
## 流式正文的节流写入可以不等结果，失败只计入 discarded。

const DEFAULT_LIMIT := 30
const MessageTime = preload("res://src/domain/message_time.gd")

var _scope_session: RefCounted
var _inflight: Array = []
var _discarded := 0


func _init(scope_session: RefCounted = null) -> void:
	_scope_session = scope_session


func is_open() -> bool:
	return _scope_session != null and _scope_session.is_open()


func scope() -> String:
	return "" if _scope_session == null else str(_scope_session.scope())


func metadata() -> Dictionary:
	return {} if _scope_session == null else _scope_session.metadata()


func discarded_count() -> int:
	_harvest()
	return _discarded


func open_scope(root: String, scope: String) -> Dictionary:
	if _scope_session == null:
		return _failure("STORAGE_UNAVAILABLE")
	return await _scope_session.ensure_open(root, scope)


func close_scope() -> Dictionary:
	if _scope_session == null:
		return _success()
	return await _scope_session.close_scope()


func read_latest(limit: int = DEFAULT_LIMIT) -> Dictionary:
	return await _read("read_latest", {"scope": scope(), "limit": limit})


func read_before(anchor_id: String, limit: int = DEFAULT_LIMIT) -> Dictionary:
	return await _read("read_before", {"scope": scope(), "anchor_id": anchor_id, "limit": limit})


func read_sync_state() -> Dictionary:
	return await _read("read_sync_state", {"scope": scope()})


func _read(operation: String, payload: Dictionary) -> Dictionary:
	if not is_open():
		return _failure("STORAGE_UNAVAILABLE")
	var result: Dictionary = await _worker().submit(operation, payload).wait()
	if not result.ok:
		return result
	var meta: Dictionary = result.data.duplicate(true)
	return _success({
		"messages": _convert(result.data.get("messages", [])),
		"revision": int(result.data.get("revision", meta.get("revision", 0))),
		"meta": meta,
	})


## 本地尾部：先落库，成功后才允许网络发送。
func save_local(message: Dictionary, entry: Dictionary = {}) -> Dictionary:
	if not is_open():
		return _failure("STORAGE_UNAVAILABLE")
	return await _worker().submit("save_local", {
		"scope": scope(), "message": message.duplicate(true), "entry": entry.duplicate(true),
	}).wait()


func update_local(message_id: String, patch: Dictionary) -> Dictionary:
	if not is_open():
		return _failure("STORAGE_UNAVAILABLE")
	return await _worker().submit("update_local", {
		"scope": scope(), "message_id": message_id, "patch": patch.duplicate(true),
	}).wait()


func delete_local(message_id: String) -> Dictionary:
	if not is_open():
		return _failure("STORAGE_UNAVAILABLE")
	return await _worker().submit("delete_local", {
		"scope": scope(), "message_id": message_id,
	}).wait()


## 历史页必须等结果：写失败时调用方不得推进游标。
func save_page(page: Dictionary, context: Dictionary) -> Dictionary:
	if not is_open():
		return _failure("STORAGE_UNAVAILABLE")
	return await _worker().submit("save_page", {
		"scope": scope(), "page": page.duplicate(true), "context": context.duplicate(true),
	}).wait()


## 流式正文用节流写：失败只计数，不打断对话。
func save_live(message: Dictionary) -> void:
	if not is_open():
		return
	var ticket = _worker().submit("save_local", {
		"scope": scope(), "message": message.duplicate(true), "entry": {},
	})
	_inflight.append(ticket)


func flush() -> Dictionary:
	if not is_open():
		return _failure("STORAGE_UNAVAILABLE")
	var before := _discarded
	var flushed: Dictionary = await _worker().submit("flush", {"scope": scope()}).wait()
	await _drain_inflight()
	if not flushed.ok:
		return flushed
	return _success({"dropped": _discarded - before})


func drain_pending_writes() -> Dictionary:
	await _drain_inflight()
	return _success()


func unsaved_count() -> int:
	_harvest()
	return _inflight.size()


func _drain_inflight() -> void:
	var queue := _inflight
	_inflight = []
	for ticket in queue:
		var result: Dictionary = await ticket.wait()
		if not result.get("ok", false):
			_discarded += 1


## 只统计已经结算的失败；在途命令保留到 flush 再决定。
func _harvest() -> void:
	var running: Array = []
	for ticket in _inflight:
		if ticket == null or not ticket.done:
			running.append(ticket)
			continue
		if not ticket.result.get("ok", false):
			_discarded += 1
	_inflight = running


func _convert(rows: Array) -> Array:
	var messages: Array = []
	for row in rows:
		messages.append(_row_to_message(row))
	return messages


func _row_to_message(row: Dictionary) -> Dictionary:
	var local := row.has("local_seq")
	var role := _role(str(row.get("role", "user")))
	var sent := int(row.get("sent_ts_ms", 0))
	var message := {
		"id": str(row.get("id", "")),
		"id_source": "local" if local else "server",
		"origin": "local" if local else "history",
		"role": role,
		"type": str(row.get("kind", "text")),
		"text": str(row.get("content", "")),
		"timestamp": MessageTime.display_text(sent),
		"status": str(row.get("state", "received")) if local else "received",
		"code": str(row.get("error_code", "")),
		"stream_complete": int(row.get("stream_complete", 1)) == 1,
		"restored": true,
	}
	if local:
		message.origin = "live" if role == "assistant" else "local"
		message.payload = _payload(row.get("payload_json"))
		message.local_seq = int(row.local_seq)
		message.attempts = int(row.get("attempts", 0))
	return message


func _payload(raw: Variant) -> Dictionary:
	if not raw is String or str(raw).is_empty():
		return {}
	var parsed: Variant = JSON.parse_string(raw)
	return parsed if parsed is Dictionary else {}


static func _role(raw: String) -> String:
	return "assistant" if raw == "agent" else raw


func _worker() -> Node:
	return _scope_session.worker()


static func _failure(code: String) -> Dictionary:
	return {"ok": false, "code": code, "data": {}}


static func _success(data: Dictionary = {}) -> Dictionary:
	return {"ok": true, "code": "OK", "data": data}
