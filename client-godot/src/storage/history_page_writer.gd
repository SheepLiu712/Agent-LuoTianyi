extends RefCounted
## 聊天写路径：整页槽位覆盖、本地尾部维护与服务器确认后的清除。
## 所有写操作都在调用方开启的单事务里完成；这里不重试、不重排、不编号。

const Schema = preload("res://src/storage/history_schema.gd")
const MessageTime = preload("res://src/domain/message_time.gd")

const ROLES := ["agent", "user", "system"]
const KINDS := ["text", "image", "sing", "cmd", "audio", "call", "voice_call"]
const STATES := ["waiting_history", "pending", "sending", "sent", "failed", "received"]
## 本地接纳时刻与服务器处理时刻可能相差几十秒；十分钟内视为同一条消息。
const SUPERSEDE_WINDOW_MS := 600000

var _access: RefCounted


func _init(access: RefCounted) -> void:
	_access = access


## 本地尾部插入或更新。entry 是 {event, payload}，供重启后继续发送。
func save_local(message: Dictionary, entry: Dictionary = {}) -> Dictionary:
	var valid := _valid_local(message)
	if not valid.ok:
		return valid
	var existing_result: Dictionary = _access.query(Schema.READ_LOCAL_BY_ID, [str(message.id)])
	if not existing_result.ok:
		return existing_result
	var existing: Dictionary = _access.first_row(existing_result)
	var payload_json := JSON.stringify(entry) if not entry.is_empty() else str(existing.get("payload_json", ""))
	var row := _local_row(message, existing, payload_json)
	if existing.is_empty():
		return _insert_local(str(message.id), row)
	return _update_local_row(str(message.id), row, int(existing.local_seq))


func _insert_local(message_id: String, row: Dictionary) -> Dictionary:
	var seq_result: Dictionary = _access.query(Schema.READ_MAX_LOCAL_SEQ)
	if not seq_result.ok:
		return seq_result
	var tail: Variant = _access.first_row(seq_result).get("tail")
	var next_seq := (0 if tail == null else int(tail)) + 1
	var inserted: Dictionary = _access.execute(Schema.INSERT_LOCAL, [
		message_id, next_seq, str(row.role), str(row.kind), str(row.content),
		int(row.sent_ts_ms), str(row.state), str(row.error_code),
		1 if row.stream_complete else 0, str(row.payload_json), 0,
		MessageTime.now_ms(), MessageTime.now_ms(),
	])
	if not inserted.ok:
		return inserted
	return _success({"local_seq": next_seq, "created": true})


func _update_local_row(message_id: String, row: Dictionary, local_seq: int) -> Dictionary:
	var updated: Dictionary = _access.execute(Schema.UPDATE_LOCAL_FULL, [
		str(row.role), str(row.kind), str(row.content), int(row.sent_ts_ms),
		str(row.state), str(row.error_code), 1 if row.stream_complete else 0,
		str(row.payload_json), int(row.attempts), MessageTime.now_ms(), message_id,
	])
	if not updated.ok:
		return updated
	return _success({"local_seq": local_seq, "created": false})


## 局部更新：未出现的字段保持原值。attempts_delta 用于累计发送尝试。
func update_local(message_id: String, patch: Dictionary) -> Dictionary:
	if message_id.is_empty():
		return _failure("INVALID_INPUT")
	var existing_result: Dictionary = _access.query(Schema.READ_LOCAL_BY_ID, [message_id])
	if not existing_result.ok:
		return existing_result
	var existing: Dictionary = _access.first_row(existing_result)
	if existing.is_empty():
		return _failure("LOCAL_MESSAGE_MISSING")
	if patch.has("state") and not str(patch.state) in STATES:
		return _failure("INVALID_INPUT")
	var merged := {
		"role": str(existing.role),
		"kind": str(existing.kind),
		"content": str(patch.get("content", existing.content)),
		"sent_ts_ms": int(patch.get("sent_ts_ms", existing.sent_ts_ms)),
		"state": str(patch.get("state", existing.state)),
		"error_code": str(patch.get("error_code", existing.error_code)),
		"stream_complete": bool(patch.get("stream_complete", int(existing.stream_complete) == 1)),
		"payload_json": str(patch.get("payload_json", existing.payload_json)),
		"attempts": int(existing.attempts) + int(patch.get("attempts_delta", 0)),
	}
	var updated: Dictionary = _access.execute(Schema.UPDATE_LOCAL_FULL, [
		merged.role, merged.kind, merged.content, merged.sent_ts_ms,
		merged.state, merged.error_code, 1 if merged.stream_complete else 0,
		merged.payload_json, merged.attempts, MessageTime.now_ms(), message_id,
	])
	if not updated.ok:
		return updated
	return _success({"state": merged.state})


func delete_local(message_id: String) -> Dictionary:
	if message_id.is_empty():
		return _failure("INVALID_INPUT")
	return _access.execute(Schema.DELETE_LOCAL, [message_id])


## 服务器历史页：整页 INSERT OR REPLACE，随后确认并移除本地尾部副本。
func save_page(page: Dictionary, context: Dictionary) -> Dictionary:
	var rows: Array = page.get("history", [])
	var start_result := _valid_start(page.get("start_index"))
	if not start_result.ok:
		return start_result
	var start := int(start_result.data.start)
	var valid := _valid_rows(rows)
	if not valid.ok:
		return valid
	var entries: Array = []
	for index in rows.size():
		var entry := _server_entry(rows[index], start + index)
		if entry.is_empty():
			return _failure("HISTORY_INVALID")
		var written: Dictionary = _access.execute(Schema.INSERT_SERVER, [
			entry.id, entry.server_index, entry.role, entry.kind,
			entry.content, entry.sent_ts_ms, MessageTime.now_ms(),
		])
		if not written.ok:
			return written
		entries.append(entry)
	var removed := _remove_confirmed(entries)
	if not removed.ok:
		return removed
	var progress := _update_progress(start, rows.size(), context)
	if not progress.ok:
		return progress
	return _success({
		"ids": entries.map(func(entry): return entry.id),
		"removed": removed.data.ids,
		"next_end": start,
		"baseline_index": progress.data.baseline_index,
		"revision": progress.data.revision,
	})


## 先用 id 精确匹配实时回复，再按「同类型 + 同正文 + 十分钟」贪心配对用户消息。
func _remove_confirmed(entries: Array) -> Dictionary:
	var removed: Array = []
	for entry in entries:
		var exact: Dictionary = _access.query(Schema.READ_LOCAL_BY_ID, [str(entry.id)])
		if not exact.ok:
			return exact
		if _access.first_row(exact).is_empty():
			continue
		var deleted: Dictionary = _access.execute(Schema.DELETE_LOCAL, [str(entry.id)])
		if not deleted.ok:
			return deleted
		removed.append(str(entry.id))
	var candidates_result: Dictionary = _access.query(Schema.READ_LOCAL_USER_CANDIDATES)
	if not candidates_result.ok:
		return candidates_result
	var candidates: Array = _access.rows_of(candidates_result)
	var used := {}
	var user_rows: Array = entries.filter(func(entry): return entry.role == "user")
	user_rows.sort_custom(func(a, b): return int(a.sent_ts_ms) < int(b.sent_ts_ms))
	for entry in user_rows:
		var match := _pick_candidate(candidates, used, entry)
		if match < 0:
			continue
		used[match] = true
		var local_id := str(candidates[match].id)
		if removed.has(local_id):
			continue
		var deleted: Dictionary = _access.execute(Schema.DELETE_LOCAL, [local_id])
		if not deleted.ok:
			return deleted
		removed.append(local_id)
	return _success({"ids": removed})


func _pick_candidate(candidates: Array, used: Dictionary, entry: Dictionary) -> int:
	for index in candidates.size():
		if used.has(index):
			continue
		var candidate: Dictionary = candidates[index]
		if str(candidate.kind) != str(entry.kind) or str(candidate.content) != str(entry.content):
			continue
		if absi(int(candidate.sent_ts_ms) - int(entry.sent_ts_ms)) > SUPERSEDE_WINDOW_MS:
			continue
		return index
	return -1


func _update_progress(start: int, count: int, context: Dictionary) -> Dictionary:
	var current: Dictionary = _access.query(Schema.READ_SYNC_STATE)
	if not current.ok:
		return current
	var row: Dictionary = _access.first_row(current)
	var baseline := int(row.get("baseline_index", -1))
	var initial := str(context.get("direction", "")) == "initial"
	if initial:
		baseline = (start + count - 1) if count > 0 else -1
	var updated: Dictionary = _access.execute(Schema.UPDATE_PROGRESS, [start, baseline])
	if not updated.ok:
		return updated
	# 初始页代表服务端当前最新窗口；更高的旧槽位已经失效，必须一起清理。
	if initial:
		var purged: Dictionary = _access.execute(Schema.DELETE_SERVER_AFTER, [baseline])
		if not purged.ok:
			return purged
	var revision: Dictionary = _access.query(Schema.READ_REVISION)
	if not revision.ok:
		return revision
	return _success({
		"baseline_index": baseline,
		"revision": int(_access.first_row(revision).get("revision", 0)),
	})


func _local_row(message: Dictionary, existing: Dictionary, payload_json: String) -> Dictionary:
	return {
		"role": _role_of(message),
		"kind": _kind_of(message),
		"content": "" if _kind_of(message) == "image" else str(message.get("text", message.get("content", ""))),
		"sent_ts_ms": MessageTime.to_display_ms(message.get("timestamp")),
		"state": str(message.get("status", existing.get("state", "pending"))),
		"error_code": str(message.get("code", existing.get("error_code", ""))),
		"stream_complete": bool(message.get("stream_complete", int(existing.get("stream_complete", 1)) == 1)),
		"payload_json": payload_json,
		"attempts": int(existing.get("attempts", 0)),
	}


func _server_entry(row: Dictionary, server_index: int) -> Dictionary:
	if not row.get("uuid") is String or str(row.get("uuid", "")).is_empty():
		return {}
	var role := str(row.get("source", ""))
	var kind := str(row.get("type", ""))
	if not role in ROLES or not kind in KINDS:
		return {}
	return {
		"id": str(row.uuid),
		"server_index": server_index,
		"role": role,
		"kind": kind,
		"content": "" if kind == "image" else str(row.get("content", "")),
		"sent_ts_ms": MessageTime.to_display_ms(row.get("timestamp")),
	}


func _valid_local(message: Dictionary) -> Dictionary:
	if not message.get("id") is String or str(message.get("id", "")).is_empty():
		return _failure("INVALID_INPUT")
	if not _role_of(message) in ROLES or not _kind_of(message) in KINDS:
		return _failure("INVALID_INPUT")
	return _success() if str(message.get("status", "pending")) in STATES else _failure("INVALID_INPUT")


func _valid_rows(rows: Array) -> Dictionary:
	for row in rows:
		if not row is Dictionary:
			return _failure("HISTORY_INVALID")
		if not row.get("uuid") is String or str(row.get("uuid", "")).is_empty():
			return _failure("HISTORY_INVALID")
		if not str(row.get("source", "")) in ROLES or not str(row.get("type", "")) in KINDS:
			return _failure("HISTORY_INVALID")
		if not str(row.get("type")) in ["image", "audio", "call", "voice_call"] and not row.get("content") is String:
			return _failure("HISTORY_INVALID")
	return _success()


static func _valid_start(raw: Variant) -> Dictionary:
	if not (raw is int or raw is float):
		return _failure("HISTORY_INVALID")
	var value := float(raw)
	if not is_finite(value) or value < 0 or value != floor(value):
		return _failure("HISTORY_INVALID")
	return _success({"start": int(value)})


## 服务器侧角色名是 agent；会话层用的是 assistant。
static func _role_of(message: Dictionary) -> String:
	var role := str(message.get("role", "user"))
	return "agent" if role == "assistant" else role


static func _kind_of(message: Dictionary) -> String:
	return str(message.get("type", "text"))


static func _failure(code: String) -> Dictionary:
	return {"ok": false, "code": code, "data": {}}


static func _success(data: Dictionary = {}) -> Dictionary:
	return {"ok": true, "code": "OK", "data": data}
