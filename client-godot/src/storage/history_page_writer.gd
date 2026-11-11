extends RefCounted
## 历史页与实时消息的写入器：所有写路径都在一个事务里完成。
## 分工：本类只负责「怎么把一页写成一致的库状态」，
## 不负责网络、不负责重试、不负责 UI。调用方负责在失败时决定重试或放弃。
## 位置分配一律交给 domain/timeline_slots，排序冲突一律整页拒绝。

const Schema = preload("res://src/storage/history_schema.gd")
const TimelineSlots = preload("res://src/domain/timeline_slots.gd")
const HistoryRuns = preload("res://src/domain/history_runs.gd")

const ROLES := ["agent", "user", "system"]
const TYPES := ["text", "image", "sing", "cmd"]
const SOURCES := ["server", "local"]
## 本地接纳时刻与服务器处理时刻可能相差几十秒；十分钟内视为同一条消息。
const SUPERSEDE_WINDOW_SECONDS := 600.0

var _access: RefCounted


func _init(access: RefCounted) -> void:
	_access = access


func save_live(message: Dictionary) -> Dictionary:
	return _access.transaction(_save_live_in_transaction.bind(message), "save_live")


func _save_live_in_transaction(message: Dictionary) -> Dictionary:
	var valid := _valid_message(message)
	if not valid.ok:
		return valid
	var existing := _existing(message.id)
	if not existing.ok:
		return existing
	if existing.data.is_empty():
		return _insert_live(message)
	return _update_live(message, existing.data)


func _insert_live(message: Dictionary) -> Dictionary:
	var slot := _tail_slot()
	if not slot.ok:
		return slot
	var written := _write_message(message, int(slot.data.order))
	if not written.ok:
		return written
	return _success({"orders": [int(slot.data.order)], "ids": [str(message.id)], "created": true})


func _update_live(message: Dictionary, existing: Dictionary) -> Dictionary:
	var guard := _guard_identity(existing, message)
	if not guard.ok:
		return guard
	var updated: Dictionary = _access.execute(Schema.UPDATE_MESSAGE_CONTENT, [
		_content_of(message),
		JSON.stringify(message.get("timestamp")),
		1 if message.get("stream_complete", true) else 0,
		str(message.get("content_origin", "live")),
		_now_ms(),
		str(message.id),
	])
	if not updated.ok:
		return updated
	var delivery: Dictionary = _access.execute(Schema.UPDATE_DELIVERY, [
		_state_of(message), str(message.get("code", "")), _now_ms(), str(message.id),
	])
	if not delivery.ok:
		return delivery
	return _success({"orders": [int(existing.timeline_order)], "ids": [str(message.id)], "created": false})


func save_page(page: Dictionary, context: Dictionary) -> Dictionary:
	return _access.transaction(_save_page_in_transaction.bind(page, context), "save_page")


func _save_page_in_transaction(page: Dictionary, context: Dictionary) -> Dictionary:
	var rows: Array = page.get("history", [])
	var bounds := _valid_page(page, context, rows)
	if not bounds.ok:
		return bounds
	var known := _load_known(rows)
	if not known.ok:
		return known
	var plan := HistoryRuns.split(rows, known.data.known)
	if not plan.ok:
		return _failure("ORDER_CONFLICT")
	var applied := _apply_runs(plan.runs, context)
	if not applied.ok:
		return applied
	var updated := _update_known(rows, known.data.known)
	if not updated.ok:
		return updated
	var saved := _save_metadata(page, context)
	if not saved.ok:
		return saved
	return _success({
		"ids": applied.data.ids,
		"duplicates": int(bounds.data.get("duplicates", 0)),
	})


## 页内字段与范围校验先行：HistoryRuns 不是协议校验器。
func _valid_page(page: Dictionary, context: Dictionary, rows: Array) -> Dictionary:
	var start: Variant = page.get("start_index")
	if not _valid_int(start):
		return _failure("HISTORY_INVALID")
	if int(context.get("epoch", 0)) <= 0:
		return _failure("CACHE_METADATA_INVALID")
	if int(context.get("end_index", -1)) >= 0 and int(context.get("end_index", -1)) - int(start) != rows.size():
		return _failure("HISTORY_INVALID")
	return _valid_rows(rows)


## 页内重复 UUID 不整页拒绝：按「范围无法确认」上报，由上层标记缺口。
## 整页拒绝只会让用户丢掉真实消息，掩盖分页漂移反而更危险。
func _valid_rows(rows: Array) -> Dictionary:
	var seen := {}
	var duplicates := 0
	for row in rows:
		var valid := _valid_row(row)
		if not valid.ok:
			return valid
		if seen.has(row.uuid):
			duplicates += 1
		seen[row.uuid] = true
	return _success({"duplicates": duplicates})


func _valid_row(row: Variant) -> Dictionary:
	if not row is Dictionary:
		return _failure("HISTORY_INVALID")
	if not row.get("uuid") is String or str(row.get("uuid", "")).is_empty():
		return _failure("HISTORY_INVALID")
	if not row.get("source") in ROLES or not row.get("type") in TYPES:
		return _failure("HISTORY_INVALID")
	if row.type != "image" and not row.get("content") is String:
		return _failure("HISTORY_INVALID")
	return _success()


func _load_known(rows: Array) -> Dictionary:
	var ids: Array = []
	for row in rows:
		ids.append(str(row.uuid))
	if ids.is_empty():
		return _success({"known": {}})
	var sql: String = Schema.READ_KNOWN % Schema.placeholders(ids.size())
	var result: Dictionary = _access.query(sql, ids)
	if not result.ok:
		return result
	var known := {}
	for row in _access.rows_of(result):
		known[str(row.message_id)] = {
			"message_id": str(row.message_id), "timeline_order": int(row.timeline_order),
			"id_source": str(row.id_source), "source": str(row.source), "message_type": str(row.message_type),
		}
	return _success({"known": known})


func _apply_runs(runs: Array, context: Dictionary) -> Dictionary:
	var ids: Array = []
	for run in runs:
		var placed := _apply_run(run, context)
		if not placed.ok:
			return placed
		ids.append_array(placed.data.ids)
	return _success({"ids": ids})


func _apply_run(run: Dictionary, context: Dictionary) -> Dictionary:
	var rows: Array = run.rows
	var bounds := _run_bounds(run, context)
	if not bounds.ok:
		return bounds
	var slots := TimelineSlots.allocate(bounds.data.left, bounds.data.right, rows.size())
	if str(slots.get("code", "")) == "RENUMBER_REQUIRED":
		var renumbered := _renumber()
		if not renumbered.ok:
			return renumbered
		# 重编号后邻居位置已经变化，必须重查再分配一次。
		bounds = _run_bounds(run, context)
		if not bounds.ok:
			return bounds
		slots = TimelineSlots.allocate(bounds.data.left, bounds.data.right, rows.size())
	if not slots.ok:
		return _failure(str(slots.get("code", "ORDER_CONFLICT")))
	return _insert_run(rows, slots.values, context)


## 锚点位置一律现查：重编号会让缓存里的旧位置失效。
## 缺一侧锚点时改用真实邻居；两侧锚点之间也可能夹着本页没带上的旧行
## （本地消息、服务端分页漂移），必须把区间收窄到最近邻居之前，
## 否则按整段均分会正好复制出旧行已占用的位置。
func _run_bounds(run: Dictionary, context: Dictionary) -> Dictionary:
	var left: Variant = _anchor_order(str(run.left))
	var right: Variant = _anchor_order(str(run.right))
	if left == null and right == null:
		return _unanchored_bounds(context)
	if left == null:
		left = _neighbor_order(int(right), true)
	elif right == null:
		right = _neighbor_order(int(left), false)
	else:
		var next_after_left: Variant = _neighbor_order(int(left), false)
		if next_after_left != null and int(next_after_left) < int(right):
			right = next_after_left
	return _success({"left": left, "right": right})


func _neighbor_order(order: int, before: bool) -> Variant:
	var sql: String = Schema.READ_NEIGHBOR_BEFORE if before else Schema.READ_NEIGHBOR_AFTER
	var result: Dictionary = _access.query(sql, [order])
	if not result.ok:
		return null
	var row: Dictionary = _access.first_row(result)
	return null if row.is_empty() else int(row.timeline_order)


## 无锚点页：首批与对账贴在本机尾部之后，更早页贴在头部之前，都不宣称已接合。
func _unanchored_bounds(context: Dictionary) -> Dictionary:
	var direction := str(context.get("direction", "initial"))
	if direction == "reconcile":
		# 对账的落位由调用方先判定：有服务器时间线贴尾，否则贴头。
		direction = "initial" if str(context.get("position", "tail")) == "tail" else "older"
	var sql: String = Schema.READ_MIN_ORDER if direction == "older" else Schema.READ_MAX_ORDER
	var result: Dictionary = _access.query(sql)
	if not result.ok:
		return result
	var row: Dictionary = _access.first_row(result)
	var column := "head" if direction == "older" else "tail"
	var value: Variant = row.get(column)
	if value == null:
		return _success({"left": null, "right": null})
	var order := int(value)
	return _success({"left": null, "right": order}) if direction == "older" else _success({"left": order, "right": null})


func _anchor_order(anchor: String) -> Variant:
	if anchor.is_empty():
		return null
	var result: Dictionary = _access.query(Schema.READ_ORDER_OF, [anchor])
	if not result.ok:
		return null
	var row: Dictionary = _access.first_row(result)
	return null if row.is_empty() else int(row.timeline_order)


func _insert_run(rows: Array, values: Array, context: Dictionary) -> Dictionary:
	var ids: Array = []
	for index in rows.size():
		var message := _history_message(rows[index], context)
		var written := _write_message(message, int(values[index]))
		if not written.ok:
			return written
		ids.append(str(message.id))
	return _success({"ids": ids})


func _update_known(rows: Array, known: Dictionary) -> Dictionary:
	for row in rows:
		if not known.has(str(row.uuid)):
			continue
		var guard := _guard_identity(known[str(row.uuid)], _history_message(row, {}))
		if not guard.ok:
			# 历史页只允许原位更新它自己的服务端记录；本地副本和身份冲突整行跳过。
			continue
		var updated: Dictionary = _access.execute(Schema.UPDATE_MESSAGE_CONTENT, [
			_content_of(row), JSON.stringify(row.timestamp), 1, "history", _now_ms(), str(row.uuid),
		])
		if not updated.ok:
			return updated
	return _success()


## 送达不确定后的主动回补：只补消息与顺序，不推进分页游标。
## 因此这里刻意不调用 _save_metadata：next_end/baseline/caught_up 与
## cached_ranges/history_positions 都必须保持对账前的状态。
func save_reconcile(rows: Array) -> Dictionary:
	return _access.transaction(_save_reconcile_in_transaction.bind(rows), "save_reconcile")


func _save_reconcile_in_transaction(rows: Array) -> Dictionary:
	var valid := _valid_rows(rows)
	if not valid.ok:
		return valid
	var unique := _unique_rows(rows)
	var known := _load_known(unique)
	if not known.ok:
		return known
	var plan := HistoryRuns.split(unique, known.data.known)
	if not plan.ok:
		return _failure("ORDER_CONFLICT")
	var position := _reconcile_position()
	if not position.ok:
		return position
	var applied := _apply_runs(plan.runs, {
		"direction": "reconcile", "position": str(position.data.position),
	})
	if not applied.ok:
		return applied
	return _success({
		"ids": applied.data.ids,
		"inserted": applied.data.ids.size(),
		"duplicates": rows.size() - unique.size(),
		"position": str(position.data.position),
	})


## 页内重复 uuid 只保留第一次出现：同一页里它必然是同一个事实。
func _unique_rows(rows: Array) -> Array:
	var seen := {}
	var unique: Array = []
	for row in rows:
		var uuid := str(row.uuid)
		if seen.has(uuid):
			continue
		seen[uuid] = true
		unique.append(row)
	return unique


## 库内已有服务器时间线时贴尾；只有本机记录（首屏跳过/失败）时贴头，
## 否则服务器历史会被排到本机记录之后。
func _reconcile_position() -> Dictionary:
	var result: Dictionary = _access.query(Schema.READ_HAS_SERVER)
	if not result.ok:
		return result
	return _success({"position": "head" if _access.first_row(result).is_empty() else "tail"})


func _save_metadata(page: Dictionary, context: Dictionary) -> Dictionary:
	var epoch := int(context.get("epoch", 0))
	var start := int(page.get("start_index", 0))
	var rows: Array = page.get("history", [])
	var positions := _save_positions(rows, epoch, start)
	if not positions.ok:
		return positions
	var ranges := _save_range(epoch, start, rows)
	if not ranges.ok:
		return ranges
	return _save_progress(start, rows, context)


func _save_positions(rows: Array, epoch: int, start: int) -> Dictionary:
	for index in rows.size():
		var saved: Dictionary = _access.execute(Schema.UPSERT_POSITION, [
			epoch, start + index, str(rows[index].uuid),
		])
		if not saved.ok:
			return saved
	return _success()


func _save_range(epoch: int, start: int, rows: Array) -> Dictionary:
	if rows.is_empty():
		return _success()
	return _access.execute(Schema.UPSERT_RANGE, [
		epoch, start, start + rows.size(), str(rows[0].uuid), str(rows[rows.size() - 1].uuid),
	])


## 首屏页决定「下次登录的接合边界」：记下最新一条，供下次判断是否已经接上。
## 更早的页只推进游标，不改边界，否则边界会被旧消息拖回去。
func _save_progress(start: int, rows: Array, context: Dictionary) -> Dictionary:
	var caught := 1 if start == 0 and not rows.is_empty() else 0
	if not rows.is_empty() and str(context.get("direction", "")) == "initial":
		# 边界取本页最后一条服务器消息，而不是本页最后一条“新插入”的消息；
		# 与本地缓存重叠的页也必须把边界推进到页尾。
		var head := str(rows[rows.size() - 1].uuid)
		return _access.execute(Schema.UPDATE_SYNC_PROGRESS, [start, head, head, caught])
	return _access.execute(Schema.UPDATE_NEXT_END, [start, caught])


## 投递状态与发送尝试必须一起落库：只更新尝试表会让消息停在旧状态。
func update_attempt(payload: Dictionary) -> Dictionary:
	return _access.transaction(_update_attempt_in_transaction.bind(payload), "update_attempt")


func _update_attempt_in_transaction(payload: Dictionary) -> Dictionary:
	var attempt := _write_attempt(payload)
	if not attempt.ok:
		return attempt
	return _set_delivery(
		str(payload.get("message_id", "")),
		str(payload.get("state", "")),
		str(payload.get("error_code", ""))
	)


func _write_attempt(payload: Dictionary) -> Dictionary:
	var state := str(payload.get("state", ""))
	var code := str(payload.get("error_code", ""))
	var wire := str(payload.get("wire_id", ""))
	var ever := 1 if payload.get("ever_sent", false) else 0
	if not wire.is_empty():
		return _access.execute(Schema.UPDATE_ATTEMPT_BY_WIRE, [state, code, ever, wire])
	return _access.execute(Schema.UPDATE_ATTEMPT_BY_MESSAGE, [state, code, ever, str(payload.get("message_id", ""))])


func _set_delivery(message_id: String, state: String, code: String) -> Dictionary:
	if message_id.is_empty():
		return _success()
	return _access.execute(Schema.UPDATE_DELIVERY, [state, code, _now_ms(), message_id])


func record_attempt(payload: Dictionary) -> Dictionary:
	return _access.execute(Schema.INSERT_ATTEMPT, [
		str(payload.get("attempt_id", "")),
		str(payload.get("message_id", "")),
		str(payload.get("wire_id", "")),
		str(payload.get("state", "sending")),
		1,
		str(payload.get("error_code", "")),
	])


## 启动/历史页落库后的本地副本对账：服务器已有同正文副本时，
## 只把本地 uncertain 软标记为 superseded，不删除、不改顺序、不推进游标。
func reconcile_delivery() -> Dictionary:
	return _access.transaction(_reconcile_delivery_in_transaction, "reconcile_delivery")


func _reconcile_delivery_in_transaction() -> Dictionary:
	var locals: Dictionary = _access.query(Schema.RECONCILE_LOCAL_UNCERTAIN)
	if not locals.ok:
		return locals
	var claims := {}
	var matches: Array = []
	for row in _access.rows_of(locals):
		var candidates := _server_copies(row)
		if not candidates.ok:
			return candidates
		var ids: Array = candidates.data.ids
		if ids.size() != 1:
			continue
		var server_id := str(ids[0])
		if claims.has(server_id):
			# 两条本地消息抢同一个服务器副本：两边都不能断言送达。
			claims[server_id] = ""
			continue
		claims[server_id] = str(row.message_id)
		matches.append({"local": str(row.message_id), "server": server_id})
	var applied: Array = []
	var now := _now_ms()
	for match in matches:
		if str(claims.get(str(match.server), "")) != str(match.local):
			continue
		var marked: Dictionary = _access.execute(Schema.MARK_SUPERSEDED, [now, str(match.local)])
		if not marked.ok:
			return marked
		var attempt: Dictionary = _access.execute(Schema.MARK_ATTEMPT_SUPERSEDED, [str(match.local)])
		if not attempt.ok:
			return attempt
		applied.append(str(match.local))
	return _success({"ids": applied})


## 候选必须唯一：同正文被用户说过多次时保持 uncertain，交给用户判断。
func _server_copies(row: Dictionary) -> Dictionary:
	var result: Dictionary = _access.query(Schema.RECONCILE_SERVER_CANDIDATES, [
		str(row.message_type), str(row.content), str(row.message_id),
	])
	if not result.ok:
		return result
	var local_seconds := _timestamp_seconds(row.get("timestamp_json"))
	if not is_finite(local_seconds):
		return _success({"ids": []})
	var ids: Array = []
	for candidate in _access.rows_of(result):
		var server_seconds := _timestamp_seconds(candidate.get("timestamp_json"))
		if is_finite(server_seconds) and absf(server_seconds - local_seconds) <= SUPERSEDE_WINDOW_SECONDS:
			ids.append(str(candidate.message_id))
	return _success({"ids": ids})


## 本地数值时间戳按本地墙钟比较；服务器无时区日历串按同口径解析。
static func _timestamp_seconds(raw: Variant) -> float:
	var parsed: Variant = raw
	if raw is String:
		parsed = JSON.parse_string(raw)
	if parsed is int or parsed is float:
		return float(parsed) + Time.get_time_zone_from_system().bias * 60.0
	if parsed is String:
		var text := str(parsed).strip_edges()
		if text.length() >= 19:
			return float(Time.get_unix_time_from_datetime_string(text.left(19).replace(" ", "T")))
	return NAN


func _renumber() -> Dictionary:
	var renumbered: Dictionary = _access.execute_block(Schema.RENUMBER)
	if not renumbered.ok:
		return renumbered
	return _access.execute(Schema.BUMP_ORDER_REVISION)


func _tail_slot() -> Dictionary:
	var result: Dictionary = _access.query(Schema.READ_MAX_ORDER)
	if not result.ok:
		return result
	var tail: Variant = _access.first_row(result).get("tail")
	var slots := TimelineSlots.allocate(null if tail == null else int(tail), null, 1)
	if not slots.ok:
		return _failure(str(slots.get("code", "ORDER_CONFLICT")))
	return _success({"order": int(slots.values[0])})


func _existing(message_id: String) -> Dictionary:
	var result: Dictionary = _access.query(Schema.READ_MESSAGE, [message_id])
	if not result.ok:
		return result
	return _success(_access.first_row(result))


func _write_message(message: Dictionary, order: int) -> Dictionary:
	var now := _now_ms()
	return _access.execute(Schema.UPSERT_MESSAGE, [
		str(message.id), _source_of(message), order, _origin_of(message),
		_role_of(message), _type_of(message), _content_of(message),
		JSON.stringify(message.get("timestamp")), _state_of(message),
		str(message.get("code", "")), 1 if message.get("stream_complete", true) else 0,
		str(message.get("content_origin", "live")), now, now,
	])


func _guard_identity(existing: Dictionary, message: Dictionary) -> Dictionary:
	if str(existing.id_source) != _source_of(message):
		return _failure("MESSAGE_ID_CONFLICT")
	if str(existing.source) != _role_of(message):
		return _failure("MESSAGE_ID_CONFLICT")
	if str(existing.message_type) != _type_of(message):
		return _failure("MESSAGE_ID_CONFLICT")
	return _success()


func _history_message(row: Dictionary, _context: Dictionary) -> Dictionary:
	return {
		"id": str(row.uuid),
		"id_source": "server",
		"origin": "history",
		"role": str(row.source),
		"type": str(row.type),
		"text": "" if str(row.type) == "image" else str(row.get("content", "")),
		"timestamp": row.timestamp,
		"status": "received",
		"code": "",
		"content_origin": "history",
		"stream_complete": true,
	}


func _valid_message(message: Dictionary) -> Dictionary:
	if not message.get("id") is String or str(message.get("id", "")).is_empty():
		return _failure("INVALID_INPUT")
	if not _source_of(message) in SOURCES or not _type_of(message) in TYPES:
		return _failure("INVALID_INPUT")
	return _success() if _role_of(message) in ROLES else _failure("INVALID_INPUT")


## 服务器侧角色名是 agent；会话层用的是 assistant。
func _role_of(message: Dictionary) -> String:
	var role := str(message.get("role", "user"))
	return "agent" if role == "assistant" else role


func _type_of(message: Dictionary) -> String:
	return str(message.get("type", "text"))


func _source_of(message: Dictionary) -> String:
	return str(message.get("id_source", "local"))


func _origin_of(message: Dictionary) -> String:
	return str(message.get("origin", "live"))


## 正文来源有两种：实时 DTO 用 text，历史页用 content；图片正文恒为空。
func _content_of(message: Dictionary) -> String:
	if _type_of(message) == "image":
		return ""
	if message.get("text") is String:
		return str(message.text)
	return str(message.get("content", ""))


func _state_of(message: Dictionary) -> String:
	return str(message.get("status", "queued"))


static func _now_ms() -> int:
	@warning_ignore("narrowing_conversion")
	return int(Time.get_unix_time_from_system() * 1000.0)


static func _valid_int(value: Variant) -> bool:
	return (value is int or value is float) and is_finite(float(value)) and value >= 0 and value == floor(float(value))


static func _failure(code: String) -> Dictionary:
	return {"ok": false, "code": code, "data": {}}


static func _success(data: Dictionary = {}) -> Dictionary:
	return {"ok": true, "code": "OK", "data": data}
