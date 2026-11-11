extends SceneTree
## 真实临时库验证：身份去重、锚点插入、更早页前插、重编号后顺序不变、关闭重开。
##
## 每个用例都在自己的 scope 目录里跑，避免互相污染；
## 断言只看可观察结果（查询到的行与顺序），不镜像实现常数。

const Database = preload("res://src/storage/sqlite_history_database.gd")

var failures: Array[String] = []
var _root := ""


func _initialize() -> void:
	run.call_deferred()


func run() -> void:
	# 每次运行使用独立根目录：避免上一轮遗留的行影响顺序断言。
	_root = "user://test-sqlite-db-%d" % Time.get_ticks_usec()
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(_root))
	await _case_install()
	await _case_live_identity()
	await _case_history_order()
	await _case_renumber()
	await _case_unlisted_gap()
	await _case_zero_order_head()
	await _case_reopen()
	await _case_reconcile_tail()
	await _case_reconcile_head()
	await _case_reconcile_conflict()
	await _case_reconcile_closed()
	await _case_reconcile_delivery()
	DirAccess.remove_absolute(ProjectSettings.globalize_path(_root))
	print("SQLite database: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func check(ok: bool, label: String) -> void:
	if ok:
		return
	failures.append(label)
	print("FAIL: ", label)


func _open(scope: String) -> RefCounted:
	var database := Database.new()
	var opened: Dictionary = database.open(_root, scope)
	check(opened.ok, "open %s (%s)" % [scope.substr(0, 6), opened.code])
	return database


func _scope(seed: String) -> String:
	return (seed + "0".repeat(64)).substr(0, 64)


func _history(count: int, start_ordinal: int) -> Array:
	var rows: Array = []
	for index in count:
		rows.append({
			"uuid": "m%d" % (start_ordinal + index),
			"source": "user",
			"type": "text",
			"content": "text-%d" % (start_ordinal + index),
			"timestamp": 1700000000 + start_ordinal + index,
		})
	return rows


func _page(start_index: int, rows: Array) -> Dictionary:
	return {"start_index": start_index, "history": rows}


func _latest(database: RefCounted, limit: int = 30) -> Array:
	var result: Dictionary = database.execute("read_latest", {"scope": database._scope, "limit": limit})
	return result.get("data", {}).get("messages", [])


# ---------------------------------------------------------------- 用例

func _case_install() -> void:
	var database := _open(_scope("a1"))
	var meta: Dictionary = database.metadata()
	check(meta.ok and int(meta.data.epoch) == 1, "fresh database starts at epoch 1")
	check(meta.ok and int(meta.data.order_revision) == 1, "fresh database starts at revision 1")
	check(_latest(database).is_empty(), "fresh database has no messages")
	database.close()


func _case_live_identity() -> void:
	var database := _open(_scope("b2"))
	var message := _local("local-1", "hello", "sending")
	check(database.execute("save_live", {"scope": database._scope, "message": message}).ok, "save live message")
	var rows := _latest(database)
	check(rows.size() == 1 and str(rows[0].content) == "hello", "live message is readable")
	message.text = "edited"
	message.status = "sent"
	check(database.execute("save_live", {"scope": database._scope, "message": message}).ok, "update live message")
	rows = _latest(database)
	check(rows.size() == 1 and str(rows[0].content) == "edited", "update keeps a single row")
	check(str(rows[0].delivery_state) == "sent", "update writes delivery state")
	var conflict := _local("local-1", "changed", "sent")
	conflict.id_source = "server"
	var rejected: Dictionary = database.execute("save_live", {"scope": database._scope, "message": conflict})
	check(rejected.code == "MESSAGE_ID_CONFLICT", "cross-source id conflict is rejected")
	check(str(_latest(database)[0].content) == "edited", "conflict keeps the original content")
	var epoch := int(database.metadata().data.epoch)
	var history: Dictionary = database.execute("save_history", {
		"scope": database._scope,
		"page": _page(0, [{"uuid":"local-1", "source":"user", "type":"text", "content":"server overwrite", "timestamp":9}]),
		"context": {"epoch": epoch, "end_index": -1, "direction": "initial"},
	})
	check(history.ok, "history page with a local duplicate still saves")
	check(str(_latest(database)[0].content) == "edited", "history cannot overwrite a local message with the same UUID")
	database.close()


func _case_history_order() -> void:
	var database := _open(_scope("c3"))
	var epoch := int(database.metadata().data.epoch)
	var first: Dictionary = database.execute("save_history", {
		"scope": database._scope,
		"page": _page(3, _history(3, 3)),
		"context": {"epoch": epoch, "end_index": -1, "direction": "initial"},
	})
	check(first.ok, "save initial page (%s)" % first.code)
	check(_order_of(database) == ["m3", "m4", "m5"], "initial page keeps server order")
	var older: Dictionary = database.execute("save_history", {
		"scope": database._scope,
		"page": _page(0, _history(3, 0)),
		"context": {"epoch": epoch, "end_index": 3, "direction": "older"},
	})
	check(older.ok, "save older page (%s)" % older.code)
	check(_order_of(database) == ["m0", "m1", "m2", "m3", "m4", "m5"], "older page is prepended")
	await _case_anchor(database, epoch)
	database.close()


## 页内已知锚点两侧都要插入，不能整页放在锚点一侧。
func _case_anchor(database: RefCounted, epoch: int) -> void:
	var rows: Array = [
		{"uuid": "new-x", "source": "user", "type": "text", "content": "x", "timestamp": 1},
		{"uuid": "m4", "source": "user", "type": "text", "content": "refreshed", "timestamp": 2},
		{"uuid": "new-y", "source": "user", "type": "text", "content": "y", "timestamp": 3},
	]
	var saved: Dictionary = database.execute("save_history", {
		"scope": database._scope,
		"page": _page(2, rows),
		"context": {"epoch": epoch, "end_index": -1, "direction": "initial"},
	})
	check(saved.ok, "save anchored page (%s)" % saved.code)
	var order := _order_of(database)
	check(order.size() == 8, "anchored page inserts only unknown rows")
	check(order.find("new-x") == order.find("m4") - 1, "unknown block before an anchor stays before it")
	check(order.find("new-y") == order.find("m4") + 1, "unknown block after an anchor stays after it")
	check(str(_row_of(database, "m4").content) == "refreshed", "known row content is refreshed")


func _case_renumber() -> void:
	var database := _open(_scope("d4"))
	var epoch := int(database.metadata().data.epoch)
	database.execute("save_history", {
		"scope": database._scope,
		"page": _page(0, _history(2, 0)),
		"context": {"epoch": epoch, "end_index": -1, "direction": "initial"},
	})
	# 人为把两个位置压到相邻，制造「间隔耗尽」。
	database.execute("flush", {"scope": database._scope})
	_force_orders(database)
	var rows: Array = [
		{"uuid": "gap-a", "source": "user", "type": "text", "content": "a", "timestamp": 1},
		{"uuid": "m0", "source": "user", "type": "text", "content": "m0", "timestamp": 2},
		{"uuid": "gap-b", "source": "user", "type": "text", "content": "b", "timestamp": 3},
		{"uuid": "m1", "source": "user", "type": "text", "content": "m1", "timestamp": 4},
	]
	var saved: Dictionary = database.execute("save_history", {
		"scope": database._scope,
		"page": _page(0, rows),
		"context": {"epoch": epoch, "end_index": -1, "direction": "initial"},
	})
	check(saved.ok, "exhausted gap triggers renumber (%s)" % saved.code)
	check(_order_of(database) == ["gap-a", "m0", "gap-b", "m1"], "renumber preserves relative order")
	var meta: Dictionary = database.metadata()
	check(int(meta.data.order_revision) == 2, "renumber bumps order_revision exactly once")
	database.close()


func _case_reopen() -> void:
	var scope := _scope("e5")
	var database := _open(scope)
	database.execute("save_live", {"scope": scope, "message": _local("persist-1", "kept", "sent")})
	database.close()
	var reopened := _open(scope)
	var rows := _latest(reopened)
	check(rows.size() == 1 and str(rows[0].content) == "kept", "messages survive close and reopen")
	check(int(reopened.metadata().data.order_revision) == 1, "metadata survives reopen")
	reopened.close()


## 页内两个锚点之间可能还有本页没带上的旧行（本地消息、分页漂移）。
## 分配器必须避开这些行，不能把整个锚点区间均分后正好占用旧行的槽位。
func _case_unlisted_gap() -> void:
	var database := _open(_scope("a7"))
	var epoch := int(database.metadata().data.epoch)
	var seeded: Dictionary = database.execute("save_history", {
		"scope": database._scope,
		"page": _page(0, _history(3, 0)),
		"context": {"epoch": epoch, "end_index": -1, "direction": "initial"},
	})
	check(seeded.ok, "seed page for unlisted gap")
	var rows: Array = [
		_server_row("m0", 1),
		_server_row("new-in-gap", 2),
		_server_row("m2", 3),
	]
	var saved: Dictionary = database.execute("save_history", {
		"scope": database._scope,
		"page": _page(0, rows),
		"context": {"epoch": epoch, "end_index": -1, "direction": "initial"},
	})
	check(saved.ok, "unlisted row between anchors is skipped (%s)" % saved.code)
	check(_order_of(database) == ["m0", "new-in-gap", "m1", "m2"], "new row lands in a free slot between anchors")
	database.close()


## timeline_order=0 是合法位置，不能当成「空库」哨兵；
## 否则更早页会从 GAP 重新起算，正面撞上已有行。
func _case_zero_order_head() -> void:
	var database := _open(_scope("b8"))
	var epoch := int(database.metadata().data.epoch)
	database.execute("save_history", {
		"scope": database._scope,
		"page": _page(0, _history(3, 0)),
		"context": {"epoch": epoch, "end_index": -1, "direction": "initial"},
	})
	database.execute("flush", {"scope": database._scope})
	var seeded := _latest(database, 10)
	var gap := int(seeded[1].timeline_order) - int(seeded[0].timeline_order)
	var access = database._access
	access.execute("UPDATE messages SET timeline_order=0 WHERE message_id='m0'")
	access.execute("UPDATE messages SET timeline_order=%d WHERE message_id='m1'" % gap)
	access.execute("UPDATE messages SET timeline_order=%d WHERE message_id='m2'" % (gap * 2))
	var saved: Dictionary = database.execute("save_history", {
		"scope": database._scope,
		"page": _page(0, [_server_row("before-zero", 0)]),
		"context": {"epoch": epoch, "end_index": 1, "direction": "older"},
	})
	check(saved.ok, "zero order is not treated as an empty database (%s)" % saved.code)
	check(_order_of(database) == ["before-zero", "m0", "m1", "m2"], "older page prepends before zero")
	database.close()


# ---------------------------------------------------------------- 对账用例

## 有服务器时间线时贴尾：新增行插在尾部锚点之后、本地记录之前；
## 页内重复 uuid 只落一条，第二次写入幂等，且同步游标完全不动。
func _case_reconcile_tail() -> void:
	var database := _open(_scope("f6"))
	var epoch := int(database.metadata().data.epoch)
	database.execute("save_history", {
		"scope": database._scope,
		"page": _page(0, _history(3, 0)),
		"context": {"epoch": epoch, "end_index": -1, "direction": "initial"},
	})
	database.execute("save_live", {"scope": database._scope, "message": _local("local-1", "unsure", "uncertain")})
	var before := _cursor_snapshot(database)
	var page: Array = [_server_row("m2", 3), _server_row("new-a", 4), _server_row("new-a", 4), _server_row("new-b", 5)]
	var saved: Dictionary = database.execute("save_reconcile", {"scope": database._scope, "rows": page})
	check(saved.ok, "reconcile saves with a known tail anchor (%s)" % saved.code)
	check(int(saved.data.inserted) == 2, "only unknown uuids are inserted")
	check(int(saved.data.duplicates) == 1, "duplicate uuid inside one page is reported")
	check(str(saved.data.position) == "tail", "server timeline keeps the page at the tail")
	check(_order_of(database) == ["m0", "m1", "m2", "new-a", "new-b", "local-1"], "reconcile keeps server order before the local record")
	check(_cursor_snapshot(database) == before, "reconcile never advances or rewrites sync cursors")
	var again: Dictionary = database.execute("save_reconcile", {"scope": database._scope, "rows": page})
	check(again.ok and int(again.data.inserted) == 0, "second reconcile of the same page is idempotent")
	check(_order_of(database).size() == 6, "idempotent reconcile adds no duplicate row")
	check(str(_row_of(database, "local-1").delivery_state) == "uncertain", "local delivery state is untouched")
	database.close()


## 库里只有本机记录（首屏跳过/失败）时贴头，服务器历史不会被排到本机记录之后。
func _case_reconcile_head() -> void:
	var database := _open(_scope("f7"))
	database.execute("save_live", {"scope": database._scope, "message": _local("local-1", "unsure", "uncertain")})
	var saved: Dictionary = database.execute("save_reconcile", {
		"scope": database._scope,
		"rows": [_server_row("a", 1), _server_row("b", 2)],
	})
	check(saved.ok and str(saved.data.position) == "head", "local-only database places history at the head")
	check(_order_of(database) == ["a", "b", "local-1"], "history precedes the local record")
	database.close()


## 页内已知锚点顺序与库内 timeline_order 相反时整页拒绝，不改动任何行。
func _case_reconcile_conflict() -> void:
	var database := _open(_scope("f8"))
	var epoch := int(database.metadata().data.epoch)
	database.execute("save_history", {
		"scope": database._scope,
		"page": _page(0, _history(2, 0)),
		"context": {"epoch": epoch, "end_index": -1, "direction": "initial"},
	})
	var before := _order_of(database)
	var saved: Dictionary = database.execute("save_reconcile", {
		"scope": database._scope,
		"rows": [_server_row("m1", 2), _server_row("lost", 3), _server_row("m0", 4)],
	})
	check(not saved.ok and saved.code == "ORDER_CONFLICT", "reversed anchors are rejected")
	check(_order_of(database) == before, "rejected reconcile leaves rows untouched")
	database.close()


func _case_reconcile_closed() -> void:
	var database := _open(_scope("f9"))
	database.close()
	var saved: Dictionary = database.execute("save_reconcile", {"scope": _scope("f9"), "rows": [_server_row("a", 1)]})
	check(not saved.ok, "closed database refuses reconcile writes (%s)" % saved.code)


## 服务器已有同正文副本时，本地 uncertain 只软标记为 superseded：
## 不删除消息、不占用户时间线、不让重启恢复把它重新变成 uncertain。
func _case_reconcile_delivery() -> void:
	var database := _open(_scope("c9"))
	var server_text := "2023-11-14 22:13:20"
	var server_epoch := float(Time.get_unix_time_from_datetime_string("2023-11-14T22:13:20"))
	var local := _local("local-q", "重庆", "uncertain")
	local.timestamp = server_epoch - Time.get_time_zone_from_system().bias * 60.0 + 30.0
	check(database.execute("save_live", {"scope": database._scope, "message": local}).ok, "seed local uncertain")
	check(database.execute("record_attempt", {
		"scope": database._scope, "attempt_id": "attempt:local-q", "message_id": "local-q",
		"wire_id": "wire-q", "state": "sending", "ever_sent": true,
	}).ok, "seed send attempt")
	var epoch := int(database.metadata().data.epoch)
	var saved: Dictionary = database.execute("save_history", {
		"scope": database._scope,
		"page": _page(0, [{
			"uuid": "server-q", "source": "user", "type": "text",
			"content": "重庆", "timestamp": server_text,
		}]),
		"context": {"epoch": epoch, "end_index": -1, "direction": "initial"},
	})
	check(saved.ok, "seed server copy")
	var result: Dictionary = database.execute("reconcile_delivery", {"scope": database._scope})
	check(result.ok and result.data.ids.has("local-q"), "server copy supersedes the local duplicate")
	check(_order_of(database) == ["server-q"], "superseded local copy leaves the visible timeline")
	var row: Dictionary = database._access.first_row(database._access.query(
		"SELECT delivery_state,error_code FROM messages WHERE message_id='local-q'"
	))
	check(str(row.delivery_state) == "superseded" and str(row.error_code) == "SERVER_COPY_MATCHED", "local copy is marked, not deleted")
	var attempt: Dictionary = database._access.first_row(database._access.query(
		"SELECT state FROM send_attempts WHERE message_id='local-q'"
	))
	check(str(attempt.state) == "superseded", "attempt no longer recovers as uncertain")
	database.close()


# ---------------------------------------------------------------- 辅助

func _server_row(uuid: String, timestamp: int) -> Dictionary:
	return {"uuid": uuid, "source": "user", "type": "text", "content": "server-%s" % uuid, "timestamp": timestamp}


## 对账不得触碰分页游标与位置记录，这里把可观察到的状态一次拍平比较。
func _cursor_snapshot(database: RefCounted) -> Dictionary:
	var meta: Dictionary = database.metadata().data
	var access = database._access
	return {
		"next_end": int(meta.next_end), "baseline": str(meta.baseline),
		"caught_up": int(meta.caught_up), "revision": int(meta.order_revision),
		"ranges": int(access.first_row(access.query("SELECT COUNT(*) AS n FROM cached_ranges")).n),
		"positions": int(access.first_row(access.query("SELECT COUNT(*) AS n FROM history_positions")).n),
	}


func _force_orders(database: RefCounted) -> void:
	for spec in [["m0", 1], ["m1", 2]]:
		database.execute("flush", {"scope": database._scope})
		var access = database._access
		access.execute("UPDATE messages SET timeline_order=? WHERE message_id=?", [int(spec[1]), str(spec[0])])


func _order_of(database: RefCounted) -> Array:
	var ids: Array = []
	for row in _latest(database, 100):
		ids.append(str(row.message_id))
	return ids


func _row_of(database: RefCounted, message_id: String) -> Dictionary:
	for row in _latest(database, 100):
		if str(row.message_id) == message_id:
			return row
	return {}


func _local(id: String, text: String, status: String) -> Dictionary:
	return {
		"id": id, "id_source": "local", "origin": "local", "role": "user", "type": "text",
		"text": text, "timestamp": 1700000000, "status": status, "code": "",
		"content_origin": "local", "stream_complete": true,
	}
