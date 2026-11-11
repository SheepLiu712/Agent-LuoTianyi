extends Node
## 历史同步控制器：本地优先、单请求分页、缺口与补齐边界。
## 只做编排：谁先显示、补到哪停、失败怎么报。落地与网络分别由
## MessagePersistence 与 HistoryFetcher 负责，因此这里既没有 SQL 也没有 HTTP。
## 三种变更来源分开上报：
##   restore_page —— 本机缓存，先显示；
##   page_received —— 本轮首批网络页，进入视图；
##   older_page —— 用户上翻取到的一页，前插；
##   reconciled —— 送达不确定后的对账页，按锚点并入视图；
## 自动补齐的页只落库、不推给视图（避免后台把用户正在读的窗口顶走）。

signal page_received(messages: Array[Dictionary])
signal older_page(messages: Array[Dictionary])
signal restore_page(messages: Array[Dictionary])
signal reconciled(messages: Array[Dictionary], position: String)
signal delivery_reconciled(ids: Array)
signal boundary_ready
signal state_changed(state: Dictionary)

const Policy = preload("res://src/session/history_sync_policy.gd")
const Fetcher = preload("res://src/session/history_fetcher.gd")

## 对账防抖：同一窗口内多条 uncertain 只发一次请求。
const RECONCILE_DEBOUNCE := 1.2

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
var _epoch := 0
var _baseline := ""
var _open := false
var _reconcile_fetcher: Node
var _reconcile_seq := 0
var _reconcile_wanted := false
var _reconcile_inflight := false
var _older_wanted := false
var _delivery_reconcile_inflight := false
var _delivery_reconcile_wanted := false


func _init(source: Node, persistence: RefCounted = null, logger: RefCounted = null, reconcile_source: Node = null) -> void:
	_persistence = persistence
	_logger = logger
	_fetcher = _build_fetcher(source)
	# 对账必须有独立的抓取器：共用实例会让上翻/首屏的 generation 取消对账（反之亦然）。
	_reconcile_fetcher = _fetcher if reconcile_source == null else _build_fetcher(reconcile_source)
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
	_reconcile_seq += 1
	_reconcile_wanted = false
	_reconcile_inflight = false
	_delivery_reconcile_wanted = false
	if _fetcher != null:
		_fetcher.cancel()
	if _reconcile_fetcher != null and _reconcile_fetcher != _fetcher:
		_reconcile_fetcher.cancel()
	_session.clear()
	_seen.clear()
	_next_end = -1
	_oldest_id = ""
	_epoch = 0
	_baseline = ""
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
	_reconcile_check_wanted.call_deferred()


func load_older() -> void:
	if _state.initial != "ready" or _state.older == "loading":
		return
	# catchup 与上翻共用 fetcher：直接发起会让两个请求互相判 CANCELLED/BUSY。
	# 先记下意图，等补齐结束后再读本地或发网络页。
	if _state.catchup == "running":
		_older_wanted = true
		return
	_load_older.call_deferred(_generation)


func pause_catchup(paused: bool) -> void:
	_state.paused = paused
	_notify()


## 可重复调用：同一窗口内的多次 uncertain 只发起一次请求。
## 只补消息与顺序，不推进分页游标，因此与 _save()/分页状态完全解耦。
func request_reconcile() -> void:
	if _persistence == null or _session.is_empty():
		return
	_reconcile_wanted = true
	_reconcile_seq += 1
	_reconcile_later(_reconcile_seq, _generation)


func _reconcile_later(seq: int, generation: int) -> void:
	await get_tree().create_timer(RECONCILE_DEBOUNCE).timeout
	if not is_inside_tree() or seq != _reconcile_seq or generation != _generation or not _reconcile_wanted:
		return
	if not _reconcile_ready():
		return
	await _reconcile_run(seq, generation)


## 首屏/补齐/上翻进行中一律让路：不抢占抓取器，也不在落位途中动尾部。
func _reconcile_ready() -> bool:
	if _reconcile_inflight or not _open or _persistence == null:
		return false
	if _state.initial in ["idle", "loading"]:
		return false
	return _state.catchup != "running" and _state.older != "loading"


func _reconcile_run(seq: int, generation: int) -> void:
	_reconcile_wanted = false
	_reconcile_inflight = true
	var response: Dictionary = await _reconcile_fetcher.fetch(_session, -1, Policy.PAGE_SIZE)
	if seq != _reconcile_seq or generation != _generation:
		_reconcile_inflight = false
		return
	var page := _validated(response, -1)
	if not page.ok:
		_reconcile_done(str(page.code), 0)
		return
	await _reconcile_store(_unique_page(page.data.rows), seq, generation)


func _reconcile_store(rows: Array, seq: int, generation: int) -> void:
	if rows.is_empty():
		_reconcile_done("OK", 0)
		return
	var saved: Dictionary = await _persistence.save_reconcile(rows)
	if seq != _reconcile_seq or generation != _generation:
		_reconcile_inflight = false
		return
	if not saved.ok:
		_reconcile_done(str(saved.code), 0)
		return
	_reconcile_delivery_async(generation)
	var inserted := int(saved.data.get("inserted", 0))
	# 整页下发而不是只发新增：内存需要页内已有 id 当锚点才能插到正确位置。
	if inserted > 0:
		reconciled.emit(_typed(_messages_of(rows)), str(saved.data.get("position", "tail")))
	_reconcile_done("OK", inserted)


func _reconcile_done(code: String, inserted: int) -> void:
	_reconcile_inflight = false
	if _logger != null:
		_logger.log_info("info_history_reconcile", {"count": inserted, "reason": code, "phase":"complete"})
	_reconcile_check_wanted()


func _reconcile_check_wanted() -> void:
	if _reconcile_wanted:
		request_reconcile.call_deferred()


## 页内重复 uuid 只保留第一次出现：同一页里它必然是同一个事实。
func _unique_page(rows: Array) -> Array:
	var seen := {}
	var unique: Array = []
	for row in rows:
		var uuid := str(row.uuid)
		if seen.has(uuid):
			continue
		seen[uuid] = true
		unique.append(row)
	return unique


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
		return false
	var result: Dictionary = await _persistence.open_scope(root, scope)
	if generation != _generation:
		return false
	if not result.ok:
		_state.storage = "unavailable"
		_state.code = str(result.code)
		return false
	_open = true
	_state.storage = "ready"
	_epoch = int(result.data.get("epoch", 0))
	_baseline = str(result.data.get("baseline", ""))
	_next_end = int(result.data.get("next_end", -1))
	_state.has_baseline = not _baseline.is_empty()
	return true


func _restore_local(generation: int) -> void:
	if _persistence != null:
		# 先把库内已有服务器副本能确认的本地 uncertain 副本收敛掉，
		# 再读最新窗口；这样启动时不会把已确认的副本又送进 UI。
		await _persistence.reconcile_delivery()
		if generation != _generation:
			return
	var result: Dictionary = await _persistence.read_latest(Policy.PAGE_SIZE)
	if generation != _generation or not result.ok:
		return
	var messages: Array = result.data.get("messages", [])
	if messages.is_empty():
		return
	# 本地窗口不参与「跨页重复即缺口」判定：它就是首屏将要覆盖的那批消息。
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
	_save(page.data.rows, int(page.data.start), -1, "initial")
	_next_end = int(page.data.start)
	_note_overlap(page.data.rows)
	_state.initial = "ready"
	_state.has_older = _next_end > 0
	_notify()
	var messages := _messages_of(page.data.rows)
	_remember(messages, true)
	page_received.emit(_typed(messages))
	_release_boundary_once()


func _fail_initial(code: String) -> void:
	_state.initial = "failed"
	_state.code = code
	_notify()
	# 首屏失败不能阻塞后续发送：本地无缓存时 boundary 否则永远不会释放，
	# 用户之后发出的每条消息都会停在 waiting_history。
	_release_boundary_once()
	_reconcile_check_wanted.call_deferred()


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
		_advance_catchup(page.data)
	_settle_catchup()


func _catchup_facts() -> Dictionary:
	return {
		"paused": bool(_state.paused),
		"joined": bool(_state.joined),
		"has_baseline": bool(_state.has_baseline),
		"next_end": _next_end,
	}


func _advance_catchup(page: Dictionary) -> void:
	_save(page.rows, int(page.start), _next_end, "catchup")
	_note_overlap(page.rows)
	_next_end = int(page.start)
	_state.has_older = _next_end > 0


## 补到的页一旦压住上次的边界，新区间就和旧缓存接上了，可以停。
func _note_overlap(rows: Array) -> void:
	if _contains_baseline(rows):
		_state.joined = true


func _settle_catchup() -> void:
	if _state.catchup != "failed" and _state.has_baseline and not _state.joined:
		_state.has_gap = true
	_state.catchup = "failed" if _state.catchup == "failed" else "done"
	_notify()
	if _older_wanted and _state.older == "idle":
		_older_wanted = false
		_load_older.call_deferred(_generation)
	_reconcile_check_wanted.call_deferred()


func _contains_baseline(rows: Array) -> bool:
	if _baseline.is_empty():
		return false
	for row in rows:
		if str(row.uuid) == _baseline:
			return true
	return false


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
	await _fetch_older(generation)


## 本地还有连续的更早记录时直接读库，不发起网络请求。
## 存在缺口时不读本地：跨缺口连起来会把两段记录伪装成连续。
func _read_local_older(generation: int) -> Dictionary:
	var unusable := not _open or _oldest_id.is_empty() or bool(_state.has_gap)
	if unusable:
		return {"ok": false, "code": "STORAGE_UNAVAILABLE", "data": {}}
	var result: Dictionary = await _persistence.read_before(_oldest_id, Policy.PAGE_SIZE)
	return result if generation == _generation else {"ok": false, "code": "CANCELLED", "data": {}}


func _fetch_older(generation: int) -> void:
	if _next_end <= 0:
		_exhaust_older()
		return
	var response: Dictionary = await _fetcher.fetch(_session, _next_end, Policy.PAGE_SIZE)
	if generation != _generation:
		return
	var page := _validated(response, _next_end)
	if not page.ok:
		_state.older = "failed"
		_state.code = str(page.code)
		_notify()
		return
	_save(page.data.rows, int(page.data.start), _next_end, "older")
	_next_end = int(page.data.start)
	_state.has_older = _next_end > 0
	_finish_older(_messages_of(page.data.rows))


func _finish_older(messages: Array) -> void:
	_remember(messages, true)
	_state.older = "idle" if _state.has_older else "exhausted"
	_notify()
	older_page.emit(_typed(messages))
	_reconcile_check_wanted.call_deferred()


func _exhaust_older() -> void:
	_state.older = "exhausted"
	_state.has_older = false
	_notify()
	_reconcile_check_wanted.call_deferred()


func _save(rows: Array, start: int, end_index: int, direction: String) -> void:
	if not _open or _persistence == null:
		return
	_persistence.save_history(
		{"start_index": start, "history": rows},
		{"epoch": _epoch, "end_index": end_index, "direction": direction}
	)
	# worker 按提交顺序执行：这条对账一定排在 save_history 之后。
	_reconcile_delivery_async(_generation)


func _reconcile_delivery_async(generation: int) -> void:
	if _persistence == null or not _open:
		return
	if _delivery_reconcile_inflight:
		_delivery_reconcile_wanted = true
		return
	_delivery_reconcile_inflight = true
	var result: Dictionary = await _persistence.reconcile_delivery()
	_delivery_reconcile_inflight = false
	if generation == _generation and result.ok:
		var ids: Array = result.data.get("ids", [])
		if not ids.is_empty():
			delivery_reconciled.emit(ids)
	if _delivery_reconcile_wanted:
		_delivery_reconcile_wanted = false
		_reconcile_delivery_async(generation)


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
		_logger.log_runtime("runtime_history_state", {
			"storage": _state.storage, "initial": _state.initial,
			"catchup": _state.catchup, "older": _state.older,
			"code": _state.code, "count": _state.count, "next_end": _next_end, "reason":"history",
		})
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
