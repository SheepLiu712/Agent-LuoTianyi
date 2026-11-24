extends SceneTree
## 历史分页编排：本地优先、单请求、30 条一批、写失败不推进游标。
##
## 存储用真实临时库，网络用固定脚本的假源，因此断言的是「请求了几页」
## 与「给视图推了哪几页」，而不是任何真实服务器行为。

const Worker = preload("res://src/storage/sqlite_worker.gd")
const Database = preload("res://src/storage/sqlite_history_database.gd")
const ScopeSession = preload("res://src/storage/scope_session.gd")
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
				"timestamp": "2026-09-19 %02d:%02d:%02d" % [index / 3600, index / 60 % 60, index % 60],
			})
		return rows


class FaultyPersistence extends RefCounted:
	var inner: RefCounted
	var fail_on := -1
	var saves := 0

	func _init(persistence: RefCounted) -> void:
		inner = persistence

	func open_scope(root: String, scope: String) -> Dictionary:
		return await inner.open_scope(root, scope)

	func read_latest(limit: int) -> Dictionary:
		return await inner.read_latest(limit)

	func read_before(anchor_id: String, limit: int) -> Dictionary:
		return await inner.read_before(anchor_id, limit)

	func read_sync_state() -> Dictionary:
		return await inner.read_sync_state()

	func save_page(page: Dictionary, context: Dictionary) -> Dictionary:
		saves += 1
		if saves == fail_on:
			return {"ok": false, "code": "CACHE_SQL_FAILED", "data": {}}
		return await inner.save_page(page, context)

	func unsaved_count() -> int:
		return 0


func _initialize() -> void:
	run.call_deferred()


func run() -> void:
	_root = "user://test-paging-%d" % Time.get_ticks_usec()
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(_root))
	await _case_first_login_takes_one_page()
	await _case_second_login_restores_then_joins()
	await _case_local_older_needs_no_request()
	await _case_gap_forces_network()
	await _case_write_failure_stops_cursor()
	await _case_initial_failure_releases_boundary()
	await _case_warm_cache_failure_releases_boundary()
	await _case_media_rows_are_accepted()
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
	var scope_session := ScopeSession.new(worker)
	var persistence := Persistence.new(scope_session)
	var opened: Dictionary = await persistence.open_scope(_root, scope)
	check(opened.ok, "open scope (%s)" % opened.code)
	return {"worker": worker, "persistence": persistence, "opened": opened}


func _sync(source: Node, persistence: RefCounted) -> Node:
	var sync := Sync.new(source, persistence)
	root.add_child(sync)
	sync.restore_page.connect(func(rows): events.append(["restore", rows.size(), _first_id(rows)]))
	sync.page_received.connect(func(rows): events.append(["page", rows.size(), _first_id(rows)]))
	sync.older_page.connect(func(rows): events.append(["older", rows.size(), _first_id(rows)]))
	return sync


func _until(predicate: Callable, timeout_ms: int = 8000) -> bool:
	var deadline := Time.get_ticks_msec() + timeout_ms
	while not predicate.call() and Time.get_ticks_msec() < deadline:
		await process_frame
	return predicate.call()


func _first_id(rows: Array) -> String:
	return "" if rows.is_empty() else str(rows[0].id)


func _teardown(sync: Node, opened: Dictionary) -> void:
	sync.stop()
	opened.worker.begin_shutdown()
	opened.worker.wait_to_finish()


## 首次登录没有可接合的旧边界：只取最新一批，并把本页最新槽位记为下次基线。
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
	check(sync.get_state().has_baseline and sync.get_state().joined, "first login records a joined baseline")
	var latest: Dictionary = await opened.persistence.read_latest(30)
	check(latest.ok and latest.data.messages.size() == 30, "first page persisted")
	var meta: Dictionary = await opened.persistence.read_sync_state()
	check(int(meta.data.meta.baseline_index) == 99, "baseline is the newest server slot")
	_teardown(sync, opened)


## 再次登录：先显示本地窗口，再补齐到上次的基线为止。
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
	check(source.requests == [-1, 165, 135, 105], "catch-up stops on the previous baseline")
	check(sync.get_state().joined and not sync.get_state().has_gap, "catch-up joins the old range")
	check(_count_of("page") == 1 and _count_of("older") == 0, "catch-up pages stay out of the view")
	var meta: Dictionary = await opened.persistence.read_sync_state()
	check(int(meta.data.meta.baseline_index) == 194, "newest message becomes the next baseline")
	_teardown(sync, opened)


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
	_teardown(sync, opened)


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
	_teardown(sync, opened)


## 落库失败不得推进游标：下一次重试仍从同一页开始。
func _case_write_failure_stops_cursor() -> void:
	var scope := _scope("e")
	await _seed(scope, 100)
	events.clear()
	var opened: Dictionary = await _open(scope)
	var faulty := FaultyPersistence.new(opened.persistence)
	faulty.fail_on = 2
	var source := FakeSource.new()
	source.total = 195
	var sync: Node = _sync(source, faulty)
	sync.start(_session(scope))
	check(await _until(func(): return sync.get_state().catchup == "failed"), "catch-up reports the write failure")
	check(sync.get_state().code == "CACHE_SQL_FAILED", "write failure code is explicit")
	check(sync.get_state().next_end == 165, "cursor stays before the failed page")
	check(_count_of("page") == 1, "initial page was still delivered")
	faulty.fail_on = -1
	sync.retry()
	check(await _until(func(): return sync.get_state().catchup == "done"), "retry resumes catch-up")
	check(sync.get_state().joined, "retry reaches the old baseline")
	_teardown(sync, opened)


## 首屏失败时保持发送等待；用户显式跳过才释放 boundary。
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
	check(not released[0], "initial failure keeps sends waiting")
	sync.skip()
	check(released[0], "skip releases the send boundary")
	_teardown(sync, opened)


## 有持久化基线的暖缓存允许离线发送；没有基线的本地尾部仍需等待。
func _case_warm_cache_failure_releases_boundary() -> void:
	var scope := _scope("f1")
	await _seed(scope, 100)
	var opened: Dictionary = await _open(scope)
	var source := FakeSource.new()
	source.fail = true
	var sync: Node = _sync(source, opened.persistence)
	var released := [false]
	sync.boundary_ready.connect(func(): released[0] = true)
	sync.start(_session(scope))
	check(await _until(func(): return sync.get_state().initial == "failed"), "warm cache initial failure settles")
	check(released[0], "warm cache with a persisted baseline releases sends")
	_teardown(sync, opened)


## 服务端历史包含语音/通话行时，媒体类型不能把整个首屏判成坏页。
func _case_media_rows_are_accepted() -> void:
	events.clear()
	var scope := _scope("f2")
	var opened: Dictionary = await _open(scope)
	var source := FakeSource.new()
	source.total = 100
	var newest: Array = source._rows(70, 100)
	newest[0] = {
		"uuid": "voice-70", "source": "user", "type": "audio", "content": "[语音消息]",
		"timestamp": "2026-09-19 00:01:10", "duration_ms": 3200, "audio_available": true,
	}
	newest[1] = {
		"uuid": "call-71", "source": "user", "type": "call", "content": "[语音通话] 01:20",
		"timestamp": "2026-09-19 00:01:11", "call_id": "call-71", "outcome": "connected",
		"active_duration_ms": 80000,
	}
	newest[2] = {
		"uuid": "legacy-72", "source": "user", "type": "voice_call", "content": "{\"duration_ms\":1000}",
		"timestamp": "2026-09-19 00:01:12",
	}
	source.overrides[-1] = newest
	var sync: Node = _sync(source, opened.persistence)
	sync.start(_session(scope))
	check(await _until(func(): return sync.get_state().phase == "complete"), "media history page reaches complete")
	check(sync.get_state().code == "", "media history page has no error code")
	check(_count_of("page") == 1 and _last_of("page")[1] == 30, "media history page is delivered")
	var latest: Dictionary = await opened.persistence.read_latest(30)
	check(latest.ok and latest.data.messages.any(
		func(message): return message.id == "voice-70" and message.type == "audio"), "audio history row persisted")
	check(latest.ok and latest.data.messages.any(
		func(message): return message.id == "call-71" and message.type == "call"), "call history row persisted")
	_teardown(sync, opened)


# ---------------------------------------------------------------- 夹具

## 建一个有历史的账号：跑首屏，再按需上翻若干页，让库里留下连续区段和基线。
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
