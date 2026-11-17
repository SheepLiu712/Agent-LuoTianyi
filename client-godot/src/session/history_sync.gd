extends Node
## 历史同步控制器：本地优先、单请求分页、写失败停游标。
## 只做编排：谁先显示、补到哪停、失败怎么报。落地与网络分别由
## MessagePersistence 与 HistoryFetcher 负责，因此这里既没有 SQL 也没有 HTTP。

signal page_received(messages: Array[Dictionary])
signal older_page(messages: Array[Dictionary])
signal restore_page(messages: Array[Dictionary])
signal delivery_reconciled(ids: Array)
signal boundary_ready
signal state_changed(state: Dictionary)

const Policy = preload("res://src/session/history_sync_policy.gd")
const Fetcher = preload("res://src/session/history_fetcher.gd")

const LEGACY_PHASES := {
	"failed": "first_failed",
	"skipped": "skipped",
	"loading": "first_loading",
	"ready": "complete",
}

var _fetcher: Node
var _persistence: RefCounted
var _logger: RefCounted
var _session: Dictionary = {}
var _generation := 0
var _state: Dictionary = {}
var _boundary_released := false
var _next_end := -1
var _oldest_id := ""
var _seen: Dictionary = {}
var _baseline_index := -1
var _join_target := -1
var _open := false
var _older_wanted := false


func _init(source: Node, persistence: RefCounted = null, logger: RefCounted = null, _legacy_reconcile_source: Node = null) -> void:
	_persistence = persistence
	_logger = logger
	_fetcher = _build_fetcher(source)
	_state = _empty()


func _build_fetcher(source: Node) -> Node:
	var fetcher: Node = source if source.has_method("fetch") else Fetcher.new(source)
	if fetcher.get_parent() == null:
		add_child(fetcher)
	return fetcher


func start(session: Dictionary) -> void:
	stop()
	_session = session.duplicate(true)
	_state.initial = "loading"
	_state.storage = "opening" if _persistence != null else "closed"
	_notify()
	_bootstrap.call_deferred(_generation)


func stop() -> void:
	_generation += 1
	if _fetcher != null:
		_fetcher.cancel()
	_session.clear()
	_seen.clear()
	_next_end = -1
	_oldest_id = ""
	_baseline_index = -1
	_join_target = -1
	_open = false
	_boundary_released = false
	_older_wanted = false
	_state = _empty()
	_notify()


func get_state() -> Dictionary:
	var state := _state.duplicate(true)
	state.phase = _legacy_phase()
	state.incomplete = bool(state.has_gap)
	state.start_index = _next_end
	return state


func retry() -> void:
	if _state.initial == "failed":
		_restart_initial.call_deferred(_generation)
		return
	if _state.older == "failed":
		load_older()
		return
	if _state.catchup == "failed":
		_catchup.call_deferred(_generation)


func skip() -> void:
	if _state.initial != "failed":
		return
	_state.initial = "skipped"
	_state.code = ""
	_notify()
	_release_boundary_once()


func load_older() -> void:
	if _state.initial != "ready" or _state.older == "loading":
		return
	# catchup 与上翻共用 fetcher：先记下意图，等补齐结束后再读本地或发网络页。
	if _state.catchup == "running":
		_older_wanted = true
		return
	_load_older.call_deferred(_generation)


func pause_catchup(paused: bool) -> void:
	_state.paused = paused
	_notify()


func _bootstrap(generation: int) -> void:
	var opened := await _open_storage(generation)
	if generation != _generation:
		return
	if opened:
		await _restore_local(generation)
	if generation != _generation:
		return
	await _fetch_initial(generation)
	if generation != _generation:
		return
	await _catchup(generation)


func _restart_initial(generation: int) -> void:
	await _fetch_initial(generation)
	if generation != _generation:
		return
	await _catchup(generation)


## 存储打不开是降级而不是登录失败：继续走网络首屏。
func _open_storage(generation: int) -> bool:
	if _persistence == null:
		return false
	var root := str(_session.get("history_root", ""))
	var scope := str(_session.get("scope", ""))
	if root.is_empty() or scope.is_empty():
		_state.storage = "unavailable"
		_log_open_failure("INVALID_CONFIG", "history_root or scope missing")
		return false
	var result: Dictionary = await _persistence.open_scope(root, scope)
	if generation != _generation:
		return false
	if not result.ok:
		_state.storage = "unavailable"
		_state.code = str(result.code)
		_log_open_failure(str(result.code), str(result.get("detail", "Local SQLite database failed to open")))
		return false
	# ScopeSession 会复用已打开的连接；游标必须以库里的最新值为准，
	# 不能沿用上一次登录缓存的 open 元数据。
	var state: Dictionary = await _persistence.read_sync_state()
	if generation != _generation:
		return false
	if not state.ok:
		_state.storage = "unavailable"
		_state.code = str(state.code)
		_log_open_failure(str(state.code), "sync state could not be read")
		return false
	_open = true
	_state.storage = "ready"
	_next_end = int(state.data.meta.get("next_end", -1))
	_baseline_index = int(state.data.meta.get("baseline_index", -1))
	_join_target = _baseline_index
	_state.has_baseline = _baseline_index >= 0
	return true


func _log_open_failure(code: String, detail: String) -> void:
	if _logger == null:
		return
	_logger.record_as("storage", "history_storage_unavailable", {
		"scope":"sqlite", "operation":"open_scope", "outcome":"failure", "duration_ms":0,
		"code":code, "phase":"failed", "level":"ERROR", "detail":detail})


func _restore_local(generation: int) -> void:
	var result: Dictionary = await _persistence.read_latest(Policy.PAGE_SIZE)
	if generation != _generation or not result.ok:
		return
	var messages: Array = result.data.get("messages", [])
	if messages.is_empty():
		return
	_oldest_id = str(messages[0].id)
	restore_page.emit(_typed(messages))
	_release_boundary_once()


func _fetch_initial(generation: int) -> void:
	_state.initial = "loading"
	_notify()
	var response: Dictionary = await _fetcher.fetch(_session, -1, Policy.PAGE_SIZE)
	if generation != _generation:
		return
	var page := _validated(response, -1)
	if not page.ok:
		_fail_initial(str(page.code))
		return
	var saved := await _persist(page.data.rows, int(page.data.start), "initial")
	if generation != _generation:
		return
	if not saved.ok:
		_fail_initial(str(saved.code))
		return
	var previous_baseline := _join_target
	_apply_saved(saved)
	_join_target = previous_baseline
	_next_end = int(page.data.start)
	_state.has_baseline = _baseline_index >= 0
	_state.joined = previous_baseline < 0 or _next_end <= previous_baseline
	_state.has_older = _next_end > 0
	_state.initial = "ready"
	_notify()
	var messages := _messages_of(page.data.rows)
	_remember(messages, true)
	_emit_removed(saved)
	page_received.emit(_typed(messages))
	_release_boundary_once()


func _fail_initial(code: String) -> void:
	_state.initial = "failed"
	_state.code = code
	_notify()
	# 首屏失败时保持发送等待：只有重试成功或用户显式跳过才释放 boundary，
	# 避免在历史基线未知时先把消息发出去、随后分页无法正确对账。


func _catchup(generation: int) -> void:
	while generation == _generation and Policy.continue_catchup(_catchup_facts()):
		_state.catchup = "running"
		_notify()
		var response: Dictionary = await _fetcher.fetch(_session, _next_end, Policy.PAGE_SIZE)
		if generation != _generation:
			return
		var page := _validated(response, _next_end)
		if not page.ok:
			_state.catchup = "failed"
			_state.code = str(page.code)
			_notify()
			return
		var saved := await _persist(page.data.rows, int(page.data.start), "catchup")
		if generation != _generation:
			return
		if not saved.ok:
			_state.catchup = "failed"
			_state.code = str(saved.code)
			_notify()
			return
		_apply_saved(saved)
		_emit_removed(saved)
		_next_end = int(page.data.start)
		_state.has_older = _next_end > 0
		if _joined(_next_end):
			_state.joined = true
	_settle_catchup()


func _catchup_facts() -> Dictionary:
	return {
		"paused": bool(_state.paused),
		"joined": bool(_state.joined),
		"has_baseline": bool(_state.has_baseline),
		"next_end": _next_end,
	}


## 追平页压住上次基线索引即与既有历史接合。
func _joined(start: int) -> bool:
	return _join_target < 0 or start <= _join_target


func _settle_catchup() -> void:
	if _state.catchup != "failed" and _state.has_baseline and not _state.joined:
		_state.has_gap = true
	_state.catchup = "failed" if _state.catchup == "failed" else "done"
	_notify()
	if _older_wanted and _state.older == "idle":
		_older_wanted = false
		_load_older.call_deferred(_generation)


func _load_older(generation: int) -> void:
	_state.older = "loading"
	_notify()
	var local := await _read_local_older(generation)
	if generation != _generation:
		return
	var messages: Array = local.get("data", {}).get("messages", [])
	if not messages.is_empty():
		_finish_older(messages)
		return
	if _next_end <= 0:
		_exhaust_older()
		return
	await _fetch_older(generation)


## 本地还有连续记录时直接读库；存在缺口时不读本地，避免跨缺口伪装连续。
func _read_local_older(generation: int) -> Dictionary:
	var unusable := not _open or _oldest_id.is_empty() or bool(_state.has_gap)
	if unusable:
		return {"ok": false, "code": "STORAGE_UNAVAILABLE", "data": {}}
	var result: Dictionary = await _persistence.read_before(_oldest_id, Policy.PAGE_SIZE)
	return result if generation == _generation else {"ok": false, "code": "CANCELLED", "data": {}}


func _fetch_older(generation: int) -> void:
	var response: Dictionary = await _fetcher.fetch(_session, _next_end, Policy.PAGE_SIZE)
	if generation != _generation:
		return
	var page := _validated(response, _next_end)
	if not page.ok:
		_state.older = "failed"
		_state.code = str(page.code)
		_notify()
		return
	var saved := await _persist(page.data.rows, int(page.data.start), "older")
	if generation != _generation:
		return
	if not saved.ok:
		_state.older = "failed"
		_state.code = str(saved.code)
		_notify()
		return
	_apply_saved(saved)
	_emit_removed(saved)
	_next_end = int(page.data.start)
	_state.has_older = _next_end > 0
	_finish_older(_messages_of(page.data.rows))


func _finish_older(messages: Array) -> void:
	_remember(messages, true)
	_state.has_older = _next_end > 0 or messages.size() >= Policy.PAGE_SIZE
	_state.older = "idle" if _state.has_older else "exhausted"
	_notify()
	older_page.emit(_typed(messages))


func _exhaust_older() -> void:
	_state.older = "exhausted"
	_state.has_older = false
	_notify()


func _persist(rows: Array, start: int, direction: String) -> Dictionary:
	if not _open or _persistence == null:
		return {"ok": true, "code": "OK", "data": {}}
	return await _persistence.save_page(
		{"start_index": start, "history": rows},
		{"direction": direction}
	)


func _apply_saved(saved: Dictionary) -> void:
	if saved.data.has("baseline_index"):
		_baseline_index = int(saved.data.baseline_index)


func _emit_removed(saved: Dictionary) -> void:
	var removed: Array = saved.get("data", {}).get("removed", [])
	if not removed.is_empty():
		delivery_reconciled.emit(removed)


func _validated(response: Dictionary, end_index: int) -> Dictionary:
	if not response.ok:
		return _failure(str(response.code))
	var data: Dictionary = response.data
	var rows: Array = data.get("history", [])
	if not Policy.valid_bounds(end_index, data.get("start_index"), rows.size(), Policy.PAGE_SIZE):
		return _failure("HISTORY_INVALID")
	if not _valid_rows(rows):
		return _failure("HISTORY_INVALID")
	return {"ok": true, "code": "OK", "data": {"rows": rows, "start": int(data.start_index)}}


func _valid_rows(rows: Array) -> bool:
	for row in rows:
		if not _valid_row(row):
			return false
	return true


func _valid_row(row: Variant) -> bool:
	if not row is Dictionary or not row.get("uuid") is String:
		return false
	if str(row.get("uuid", "")).is_empty():
		return false
	if not str(row.get("source", "")) in ["agent", "user", "system"]:
		return false
	if not str(row.get("type", "")) in ["text", "image", "sing", "cmd"]:
		return false
	if str(row.get("type")) == "image":
		return true
	return row.get("content") is String


func _messages_of(rows: Array) -> Array:
	var messages: Array = []
	for row in rows:
		messages.append({
			"id": str(row.uuid),
			"id_source": "server",
			"role": "assistant" if str(row.source) == "agent" else str(row.source),
			"text": "" if str(row.type) == "image" else str(row.get("content", "")),
			"type": str(row.type),
			"timestamp": row.timestamp,
			"history": true,
			"status": "received",
			"code": "",
		})
	return messages


func _remember(messages: Array, track_oldest: bool) -> void:
	for message in messages:
		if _seen.has(str(message.id)):
			_state.has_gap = true
		_seen[str(message.id)] = true
	_state.count += messages.size()
	if track_oldest and not messages.is_empty():
		_oldest_id = str(messages[0].id)


func _release_boundary_once() -> void:
	if _boundary_released:
		return
	_boundary_released = true
	boundary_ready.emit()


func _empty() -> Dictionary:
	return {
		"storage": "closed" if _persistence == null else "opening",
		"initial": "idle", "catchup": "idle", "older": "idle",
		"has_older": false, "has_gap": false, "unsaved": 0, "code": "",
		"paused": false, "joined": false, "has_baseline": false,
		"next_end": -1, "count": 0,
	}


func _legacy_phase() -> String:
	if _state.initial == "idle":
		return "idle"
	if _state.catchup == "failed" or _state.older == "failed":
		return "failed"
	return str(LEGACY_PHASES.get(str(_state.initial), "complete"))


func _notify() -> void:
	_state.next_end = _next_end
	if _logger != null:
		_logger.record_as("business", "history_state", {
			"storage": _state.storage, "initial": _state.initial,
			"catchup": _state.catchup, "older": _state.older,
			"code": _state.code, "count": _state.count, "next_end": _next_end, "reason":"history",
			"phase":"running", "level":"WARN" if _state.code not in ["", "OK"] else "INFO"})
	state_changed.emit(get_state())


func _typed(messages: Array) -> Array[Dictionary]:
	var typed: Array[Dictionary] = []
	for message in messages:
		if message is Dictionary:
			typed.append(message)
	return typed


func _exit_tree() -> void:
	stop()


static func _failure(code: String) -> Dictionary:
	return {"ok": false, "code": code, "data": {}}
