extends SceneTree
## 历史分页编排：本地优先、单请求、30 条一批、缺口不冒充连续。
##
## 存储用真实临时库，网络用固定脚本的假源，因此断言的是「请求了几页」
## 与「给视图推了哪几页」，而不是任何真实服务器行为。

const Worker = preload("res://src/storage/sqlite_worker.gd")
const Database = preload("res://src/storage/sqlite_history_database.gd")
const Persistence = preload("res://src/session/message_persistence.gd")
const Sync = preload("res://src/session/history_sync.gd")

var failures: Array[String] = []
var _root := ""
var events: Array = []


## 固定脚本的服务器：total 条消息，按 30 条一批返回，可被 overrides 覆盖某页。
class FakeSource:
	extends Node

	var total := 0
	var requests: Array = []
	var overrides: Dictionary = {}
	var fail := false

	func cancel() -> void:
		pass

	func fetch(_session: Dictionary, end_index: int, count: int) -> Dictionary:
		requests.append(end_index)
		if fail:
			return {"ok": false, "code": "NETWORK_OFFLINE", "status": 0, "data": {}}
		var stop := total if end_index < 0 else end_index
		var start := maxi(0, stop - count)
		var rows: Array = overrides.get(end_index, _rows(start, stop))
		return {"ok": true, "code": "OK", "status": 200, "data": {"history": rows, "start_index": start}}

	func _rows(start: int, stop: int) -> Array:
		var rows: Array = []
		for index in range(start, stop):
			rows.append({
				"uuid": "m-%d" % index,
				"source": "agent" if index % 2 == 0 else "user",
				"type": "text",
				"content": "record %d" % index,
				"timestamp": float(index),
			})
		return rows


## 直接暴露 fetch_page 的假客户端：用来走真实的 HistoryFetcher（含一次重试）。
class FakeApi:
	extends Node

	var total := 0
	var fail := false
	var calls := 0

	func cancel() -> void:
		pass

	func fetch_page(_session: Dictionary, end_index: int, count: int) -> Dictionary:
		calls += 1
		if fail:
			return {"ok": false, "code": "NETWORK_ERROR", "status": 0, "data": {}}
		var stop := total if end_index < 0 else end_index
		var start := maxi(0, stop - count)
		var rows: Array = []
		for index in range(start, stop):
			rows.append({"uuid": "m-%d" % index, "source": "user", "type": "text", "content": "r%d" % index, "timestamp": float(index)})
		return {"ok": true, "code": "OK", "status": 200, "data": {"history": rows, "start_index": start}}


func _initialize() -> void:
	run.call_deferred()


func run() -> void:
	_root = "user://test-paging-%d" % Time.get_ticks_usec()
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(_root))
	await _case_first_login_takes_one_page()
	await _case_second_login_restores_then_joins()
	await _case_local_older_needs_no_request()
	await _case_gap_forces_network()
	await _case_reconcile_debounced()
	await _case_reconcile_waits_for_initial()
	await _case_reconcile_silent_on_failure()
	await _case_reconcile_cancelled_by_stop()
	await _case_initial_failure_releases_boundary()
	print("History paging: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func check(ok: bool, label: String) -> void:
	if ok:
		return
	failures.append(label)
	print("FAIL: ", label)


func _scope(tag: String) -> String:
	return (tag + "0".repeat(64)).substr(0, 64)


func _session(scope: String) -> Dictionary:
	return {
		"history_root": _root,
		"scope": scope,
		"server": "http://127.0.0.1",
		"username": "paging",
		"message_token": "token",
	}


func _open(scope: String) -> Dictionary:
	var worker := Worker.new(func() -> RefCounted: return Database.new())
	root.add_child(worker)
	worker.start()
	var persistence := Persistence.new(worker)
	var opened: Dictionary = await persistence.open_scope(_root, scope)
	check(opened.ok, "open scope (%s)" % opened.code)
	return {"worker": worker, "persistence": persistence, "opened": opened}


func _sync(source: Node, persistence: RefCounted, reconcile_source: Node = null) -> Node:
	var sync := Sync.new(source, persistence, null, reconcile_source)
	root.add_child(sync)
	sync.restore_page.connect(func(rows): events.append(["restore", rows.size(), _first_id(rows)]))
	sync.page_received.connect(func(rows): events.append(["page", rows.size(), _first_id(rows)]))
	sync.older_page.connect(func(rows): events.append(["older", rows.size(), _first_id(rows)]))
	sync.reconciled.connect(func(rows, position): events.append(["reconcile", rows.size(), position]))
	return sync


func _until(predicate: Callable, timeout_ms: int = 8000) -> bool:
	var deadline := Time.get_ticks_msec() + timeout_ms
	while not predicate.call() and Time.get_ticks_msec() < deadline:
		await process_frame
	return predicate.call()


func _first_id(rows: Array) -> String:
	return "" if rows.is_empty() else str(rows[0].id)


# ---------------------------------------------------------------- 用例

## 首次登录没有可接合的历史边界：只取最新一批，不后台补齐。
func _case_first_login_takes_one_page() -> void:
	events.clear()
	var scope := _scope("a")
	var opened: Dictionary = await _open(scope)
	var source := FakeSource.new()
	source.total = 100
	var sync: Node = _sync(source, opened.persistence)
	sync.start(_session(scope))
	check(await _until(func(): return sync.get_state().catchup == "done"), "first login settles")
	check(source.requests == [-1], "first login fetches one page only")
	check(events.size() == 1 and events[0][0] == "page" and events[0][1] == 30, "first login shows the newest page")
	check(sync.get_state().has_baseline == false, "first login has no baseline yet")
	var latest: Dictionary = await opened.persistence.read_latest(30)
	check(latest.ok and latest.data.messages.size() == 30, "first page persisted")
	sync.stop()
	opened.worker.begin_shutdown()
	opened.worker.wait_to_finish()


## 再次登录：先显示本地窗口，再补齐到上次的边界为止。
func _case_second_login_restores_then_joins() -> void:
	var scope := _scope("b")
	await _seed(scope, 100)
	events.clear()
	var opened: Dictionary = await _open(scope)
	var source := FakeSource.new()
	source.total = 195
	var sync: Node = _sync(source, opened.persistence)
	sync.start(_session(scope))
	check(await _until(func(): return sync.get_state().catchup == "done"), "second login settles")
	check(events.size() >= 1 and events[0][0] == "restore" and events[0][1] == 30, "local window shows first")
	check(source.requests == [-1, 165, 135, 105], "catch-up stops on the previous boundary")
	check(sync.get_state().joined and not sync.get_state().has_gap, "catch-up joins the old range")
	check(_count_of("page") == 1 and _count_of("older") == 0, "catch-up pages stay out of the view")
	var baseline: Dictionary = await opened.persistence.read_sync_state()
	check(str(baseline.data.meta.baseline) == "m-194", "newest message becomes the next baseline")
	sync.stop()
	opened.worker.begin_shutdown()
	opened.worker.wait_to_finish()


## 上翻优先读本地连续区段：同一批数据不再发起网络请求。
func _case_local_older_needs_no_request() -> void:
	var scope := _scope("c")
	await _seed(scope, 120, 3)
	events.clear()
	var opened: Dictionary = await _open(scope)
	var source := FakeSource.new()
	source.total = 120
	var sync: Node = _sync(source, opened.persistence)
	sync.start(_session(scope))
	check(await _until(func(): return sync.get_state().catchup == "done"), "local older settles")
	var before := source.requests.size()
	sync.load_older()
	check(await _until(func(): return _count_of("older") == 1), "local older page delivered")
	check(source.requests.size() == before, "local older page needs no request")
	check(_last_of("older")[2] == "m-60", "local older page starts where the cache continues")
	sync.stop()
	opened.worker.begin_shutdown()
	opened.worker.wait_to_finish()


## 有缺口时不允许读本地：跨缺口拼起来会把两段记录伪装成连续。
func _case_gap_forces_network() -> void:
	var scope := _scope("d")
	await _seed(scope, 100)
	events.clear()
	var opened: Dictionary = await _open(scope)
	var source := FakeSource.new()
	source.total = 200
	var sync: Node = _sync(source, opened.persistence)
	sync.start(_session(scope))
	sync.pause_catchup(true)
	check(await _until(func(): return sync.get_state().initial == "ready"), "gap start shows the newest page")
	check(sync.get_state().has_gap, "unfinished catch-up is reported as a gap")
	var before := source.requests.size()
	sync.load_older()
	check(await _until(func(): return _count_of("older") == 1), "gap older page delivered")
	check(source.requests.size() == before + 1, "gap older page comes from the network")
	check(_last_of("older")[2] == "m-140", "gap older page does not jump into the older cache")
	sync.stop()
	opened.worker.begin_shutdown()
	opened.worker.wait_to_finish()


# ---------------------------------------------------------------- 对账用例

## 同一窗口内的多次 uncertain 只发起一次拉取，并把缺失的服务器页补到尾部。
func _case_reconcile_debounced() -> void:
	var scope := _scope("e1")
	await _seed(scope, 90)
	events.clear()
	var opened: Dictionary = await _open(scope)
	var source := FakeSource.new()
	source.total = 90
	var reconcile_source := FakeSource.new()
	reconcile_source.total = 120
	var sync: Node = _sync(source, opened.persistence, reconcile_source)
	sync.start(_session(scope))
	check(await _until(func(): return sync.get_state().catchup == "done"), "reconcile window starts settled")
	sync.request_reconcile()
	sync.request_reconcile()
	sync.request_reconcile()
	check(await _until(func(): return _count_of("reconcile") == 1, 6000), "repeated uncertain signals merge into one reconcile")
	check(reconcile_source.requests == [-1], "one reconcile fetch per debounce window")
	check(_last_of("reconcile")[2] == "tail", "reconcile page extends the server timeline at the tail")
	var latest: Dictionary = await opened.persistence.read_latest(100)
	check(latest.data.messages.size() == 60, "reconcile adds the missing page without duplicates")
	check(str(latest.data.messages[-1].id) == "m-119", "reconciled rows keep the server order")
	sync.stop()
	opened.worker.begin_shutdown()
	opened.worker.wait_to_finish()


## 首屏仍在加载时对账必须让路，并在首屏结束后自动补跑一次。
func _case_reconcile_waits_for_initial() -> void:
	var scope := _scope("e2")
	await _seed(scope, 60)
	events.clear()
	var opened: Dictionary = await _open(scope)
	var source := FakeSource.new()
	source.total = 60
	var reconcile_source := FakeSource.new()
	reconcile_source.total = 90
	var sync: Node = _sync(source, opened.persistence, reconcile_source)
	sync.start(_session(scope))
	check(await _until(func(): return sync.get_state().catchup == "done"), "reconcile gate starts settled")
	sync._state.initial = "loading"
	sync.request_reconcile()
	await create_timer(1.6).timeout
	check(reconcile_source.requests.is_empty(), "reconcile yields while the first page is loading")
	sync._state.initial = "ready"
	sync._reconcile_check_wanted()
	check(await _until(func(): return _count_of("reconcile") == 1, 6000), "deferred reconcile runs after the first page settles")
	sync.stop()
	opened.worker.begin_shutdown()
	opened.worker.wait_to_finish()


## 拉取失败只重试一次，不产生界面变更，也不改变同步相位。
func _case_reconcile_silent_on_failure() -> void:
	var scope := _scope("e3")
	await _seed(scope, 60)
	events.clear()
	var opened: Dictionary = await _open(scope)
	var source := FakeApi.new()
	source.total = 60
	var reconcile_api := FakeApi.new()
	reconcile_api.fail = true
	var sync: Node = _sync(source, opened.persistence, reconcile_api)
	sync.start(_session(scope))
	check(await _until(func(): return sync.get_state().catchup == "done"), "reconcile failure starts settled")
	sync.request_reconcile()
	check(await _until(func(): return reconcile_api.calls == 2, 6000), "failed reconcile retries exactly once")
	check(_count_of("reconcile") == 0, "failed reconcile never reaches the view")
	check(sync.get_state().phase == "complete", "failed reconcile keeps the sync phase")
	sync.stop()
	sync.queue_free()
	opened.worker.begin_shutdown()
	opened.worker.wait_to_finish()


## 停止或切号会丢弃仍在防抖窗口里的对账请求。
func _case_reconcile_cancelled_by_stop() -> void:
	var scope := _scope("e4")
	await _seed(scope, 60)
	events.clear()
	var opened: Dictionary = await _open(scope)
	var source := FakeSource.new()
	source.total = 60
	var reconcile_source := FakeSource.new()
	reconcile_source.total = 90
	var sync: Node = _sync(source, opened.persistence, reconcile_source)
	sync.start(_session(scope))
	check(await _until(func(): return sync.get_state().catchup == "done"), "reconcile cancel starts settled")
	sync.request_reconcile()
	sync.stop()
	await create_timer(1.8).timeout
	check(reconcile_source.requests.is_empty(), "stop cancels a pending reconcile")
	check(_count_of("reconcile") == 0, "cancelled reconcile never reaches the view")
	opened.worker.begin_shutdown()
	opened.worker.wait_to_finish()


## 首屏失败后 boundary 必须释放，否则之后用户发出的消息永远停在 waiting_history。
func _case_initial_failure_releases_boundary() -> void:
	var scope := _scope("f")
	var opened: Dictionary = await _open(scope)
	var source := FakeSource.new()
	source.fail = true
	var sync: Node = _sync(source, opened.persistence)
	var released := [false]
	sync.boundary_ready.connect(func(): released[0] = true)
	sync.start(_session(scope))
	check(await _until(func(): return sync.get_state().initial == "failed"), "initial failure settles")
	check(released[0], "initial failure releases the send boundary")
	sync.stop()
	opened.worker.begin_shutdown()
	opened.worker.wait_to_finish()


# ---------------------------------------------------------------- 夹具

## 建一个有历史的账号：跑首屏，再按需上翻若干页，让库里留下连续区段和边界。
func _seed(scope: String, total: int, older_pages: int = 0) -> void:
	var opened: Dictionary = await _open(scope)
	var source := FakeSource.new()
	source.total = total
	var sync: Node = _sync(source, opened.persistence)
	sync.start(_session(scope))
	await _until(func(): return sync.get_state().catchup == "done")
	for _page in older_pages:
		var delivered := _count_of("older")
		sync.load_older()
		await _until(func(): return _count_of("older") > delivered)
	await opened.persistence.flush()
	sync.stop()
	opened.worker.begin_shutdown()
	opened.worker.wait_to_finish()


func _count_of(kind: String) -> int:
	return events.filter(func(event): return event[0] == kind).size()


func _last_of(kind: String) -> Array:
	var matched: Array = events.filter(func(event): return event[0] == kind)
	return matched[matched.size() - 1] if not matched.is_empty() else []
