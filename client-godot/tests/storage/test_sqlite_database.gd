extends SceneTree
## 新聊天库：PRAGMA/版本、槽位自愈、尾部状态机、历史页确认与硬重置。

const Database = preload("res://src/storage/sqlite_history_database.gd")
const MessageTime = preload("res://src/domain/message_time.gd")

var failures: Array[String] = []
var _root := ""


func _initialize() -> void:
	run.call_deferred()


func run() -> void:
	# 每次运行使用独立根目录：避免上一轮遗留的行影响顺序断言。
	_root = "user://test-sqlite-db-%d" % Time.get_ticks_usec()
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(_root))
	_case_install()
	_case_save_and_page()
	_case_initial_page_purges_stale_slots()
	_case_slot_self_heal()
	_case_local_tail()
	_case_restart_recovery()
	_case_confirmation()
	_case_confirmation_keeps_sending()
	_case_delete_local()
	_case_query_plan()
	_case_stale_scope()
	_case_config_rebuild()
	_case_explicit_reset()
	_case_reset_legacy()
	_case_reset_orphans()
	_case_repair_metadata()
	print("SQLite database: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func check(ok: bool, label: String) -> void:
	if ok:
		return
	failures.append(label)
	print("FAIL: ", label)


func _scope(tag: String) -> String:
	return (tag + "0".repeat(64)).substr(0, 64)


func _open(scope: String) -> RefCounted:
	var database = Database.new()
	var opened: Dictionary = database.open(_root, scope)
	check(opened.ok, "open scope (%s)" % opened.code)
	return database


func _row(database: RefCounted, sql: String, bindings: Array = []) -> Dictionary:
	var result: Dictionary = database._access.query(sql, bindings)
	return database._access.first_row(result)


func _execute(database: RefCounted, operation: String, scope: String, extra: Dictionary = {}) -> Dictionary:
	var payload := {"scope": scope}
	payload.merge(extra, true)
	return database.execute(operation, payload)


func _server_rows(seed: String, start: int, count: int) -> Array:
	var rows: Array = []
	for index in range(start, start + count):
		rows.append({
			"uuid": "m-%s-%d" % [seed, index],
			"source": "user" if index % 2 == 0 else "agent",
			"type": "text",
			"content": "record %d" % index,
			"timestamp": "2026-09-19 %02d:%02d:%02d" % [index / 3600 % 24, index / 60 % 60, index % 60],
		})
	return rows


func _ids(messages: Array) -> Array:
	return messages.map(func(message): return str(message.id))


func _case_install() -> void:
	var scope := _scope("a")
	var database := _open(scope)
	check(int(_row(database, "PRAGMA auto_vacuum")["auto_vacuum"]) == 2, "auto_vacuum is incremental")
	check(int(_row(database, "PRAGMA user_version")["user_version"]) == 100, "schema version is 100")
	check(int(_row(database, "PRAGMA application_id")["application_id"]) == 1280591961, "application id is LTHY")
	check(str(_row(database, "PRAGMA journal_mode")["journal_mode"]).to_lower() == "wal", "journal is WAL")
	check(int(_row(database, "PRAGMA foreign_keys")["foreign_keys"]) == 1, "foreign keys are on")
	var tables: Array = database._access.table_names()
	for table in ["messages", "local_messages", "sync_state", "dynamic_posts", "dynamic_comments", "dynamic_state"]:
		check(tables.has(table), "table %s exists" % table)
	var meta: Dictionary = database.metadata()
	check(meta.ok and int(meta.data.baseline_index) == -1 and int(meta.data.next_end) == -1, "fresh sync state")
	var state: Dictionary = _execute(database, "dynamics_state", scope)
	check(state.ok and str(state.data.state.scope_key) == scope, "dynamics state is bound to scope")
	database.close()


func _case_save_and_page() -> void:
	var scope := _scope("b")
	var database := _open(scope)
	var first: Dictionary = _execute(database, "save_page", scope, {
		"page": {"start_index": 0, "history": _server_rows("b", 0, 60)},
		"context": {"direction": "initial"},
	})
	check(first.ok, "save initial page")
	check(int(first.data.baseline_index) == 59, "initial page records the newest slot")
	var latest: Dictionary = _execute(database, "read_latest", scope, {"limit": 30})
	check(_ids(latest.data.messages) == _server_ids("b", 30, 30), "latest returns the newest server page in ascending order")
	var anchor := "m-b-30"
	var older: Dictionary = _execute(database, "read_before", scope, {"anchor_id": anchor, "limit": 30})
	check(_ids(older.data.messages) == _server_ids("b", 0, 30), "older page stops before the anchor")
	var again: Dictionary = _execute(database, "save_page", scope, {
		"page": {"start_index": 30, "history": _server_rows("b", 30, 30)},
		"context": {"direction": "catchup"},
	})
	check(again.ok and int(again.data.baseline_index) == 59, "catch-up pages do not move the baseline")
	database.close()


func _case_initial_page_purges_stale_slots() -> void:
	var scope := _scope("b1")
	var database := _open(scope)
	var full: Dictionary = _execute(database, "save_page", scope, {
		"page": {"start_index": 0, "history": _server_rows("p", 0, 100)},
		"context": {"direction": "initial"},
	})
	check(full.ok and int(full.data.baseline_index) == 99, "full initial page records its baseline")
	var shortened: Dictionary = _execute(database, "save_page", scope, {
		"page": {"start_index": 0, "history": _server_rows("p", 0, 30)},
		"context": {"direction": "initial"},
	})
	check(shortened.ok and int(shortened.data.baseline_index) == 29, "shortened initial page moves the baseline down")
	check(int(_row(database, "SELECT COUNT(*) AS count FROM messages")["count"]) == 30,
		"stale slots above the new baseline are removed")
	var latest: Dictionary = _execute(database, "read_latest", scope, {"limit": 30})
	check(_ids(latest.data.messages) == _server_ids("p", 0, 30), "latest window excludes stale slots")
	var emptied: Dictionary = _execute(database, "save_page", scope, {
		"page": {"start_index": 0, "history": []},
		"context": {"direction": "initial"},
	})
	check(emptied.ok and int(emptied.data.baseline_index) == -1, "empty initial page resets the baseline")
	check(int(_row(database, "SELECT COUNT(*) AS count FROM messages")["count"]) == 0,
		"empty initial page clears cached server slots")
	database.close()


func _server_ids(seed: String, start: int, count: int) -> Array:
	var ids: Array = []
	for index in range(start, start + count):
		ids.append("m-%s-%d" % [seed, index])
	return ids


func _case_slot_self_heal() -> void:
	var scope := _scope("c")
	var database := _open(scope)
	var page: Array = _server_rows("c", 0, 3)
	_execute(database, "save_page", scope, {"page": {"start_index": 10, "history": page}, "context": {"direction": "initial"}})
	var replaced: Array = [_server_row("replacement", 42)]
	var saved: Dictionary = _execute(database, "save_page", scope, {
		"page": {"start_index": 10, "history": replaced}, "context": {"direction": "catchup"},
	})
	check(saved.ok, "same-slot replacement is accepted")
	var rows: Array = database._access.rows_of(database._access.query("SELECT * FROM messages WHERE server_index=10"))
	check(rows.size() == 1 and str(rows[0].id) == "replacement", "same slot keeps exactly one row")
	check(int(_row(database, "SELECT COUNT(*) AS count FROM messages")["count"]) == 3, "only the replaced slot is overwritten")
	# 同一 id 换槽位也只能留一行。
	var moved: Dictionary = _execute(database, "save_page", scope, {
		"page": {"start_index": 20, "history": [_server_row("replacement", 43)]},
		"context": {"direction": "catchup"},
	})
	check(moved.ok, "same id at a new slot is accepted")
	var moved_rows: Array = database._access.rows_of(database._access.query("SELECT * FROM messages WHERE id='replacement'"))
	check(moved_rows.size() == 1 and int(moved_rows[0].server_index) == 20, "id moves without duplication")
	check(int(_row(database, "SELECT COUNT(*) AS count FROM messages WHERE server_index=10")["count"]) == 0, "old slot is released")
	database.close()


func _server_row(id: String, index: int) -> Dictionary:
	return {
		"uuid": id, "source": "agent", "type": "text",
		"content": "record %d" % index, "timestamp": "2026-09-19 10:00:00",
	}


func _local(id: String, text: String, status: String, timestamp: float = 0.0) -> Dictionary:
	return {
		"id": id, "id_source": "local", "origin": "local", "role": "user",
		"type": "text", "text": text,
		"timestamp": timestamp if timestamp > 0 else Time.get_unix_time_from_system(),
		"status": status, "code": "", "stream_complete": true,
	}


func _case_local_tail() -> void:
	var scope := _scope("d")
	var database := _open(scope)
	var entry := {"event": "user_text", "payload": {"message": "hello"}}
	var saved: Dictionary = _execute(database, "save_local", scope, {
		"message": _local("local-1", "hello", "pending"), "entry": entry,
	})
	check(saved.ok, "local tail insert")
	check(int(saved.data.local_seq) == 1, "local sequence starts at one")
	var updated: Dictionary = _execute(database, "update_local", scope, {
		"message_id": "local-1", "patch": {"state": "sending", "attempts_delta": 1},
	})
	check(updated.ok, "local tail state update")
	var latest: Dictionary = _execute(database, "read_latest", scope, {"limit": 30})
	check(_ids(latest.data.messages) == ["local-1"], "local tail is returned")
	check(str(latest.data.messages[0].state) == "sending", "local state round trips")
	var payload: Variant = JSON.parse_string(str(latest.data.messages[0].payload_json))
	check(payload is Dictionary and str(payload.event) == "user_text", "send intent round trips")
	check(int(_row(database, "SELECT attempts FROM local_messages WHERE id='local-1'")["attempts"]) == 1, "attempts accumulate")
	database.close()


func _case_restart_recovery() -> void:
	var scope := _scope("e")
	var database := _open(scope)
	_execute(database, "save_local", scope, {"message": _local("sending-1", "maybe", "sending")})
	_execute(database, "save_local", scope, {"message": _local("pending-1", "later", "pending")})
	database.close()
	database = _open(scope)
	var latest: Dictionary = _execute(database, "read_latest", scope, {"limit": 30})
	var rows: Array = latest.data.messages
	check(_status(rows, "sending-1") == "failed", "sending becomes failed on restart")
	check(_code(rows, "sending-1") == "DELIVERY_UNCERTAIN", "sending carries DELIVERY_UNCERTAIN")
	check(_status(rows, "pending-1") == "pending", "pending stays pending for automatic resend")
	database.close()
	# waiting_history 超过 24 小时 → SEND_EXPIRED。
	database = _open(scope)
	var old := _local("old-waiting", "old", "waiting_history")
	var stale_ms := MessageTime.now_ms() - 25 * 60 * 60 * 1000
	_execute(database, "save_local", scope, {"message": old})
	database._access.execute("UPDATE local_messages SET created_at_ms=? WHERE id='old-waiting'", [stale_ms])
	database.close()
	database = _open(scope)
	var expired: Dictionary = _row(database, "SELECT state,error_code FROM local_messages WHERE id='old-waiting'")
	check(str(expired.state) == "failed" and str(expired.error_code) == "SEND_EXPIRED", "stale waiting_history expires")
	database.close()


func _status(messages: Array, id: String) -> String:
	for message in messages:
		if str(message.id) == id:
			return str(message.get("state", ""))
	return ""


func _code(messages: Array, id: String) -> String:
	for message in messages:
		if str(message.id) == id:
			return str(message.get("error_code", ""))
	return ""


func _case_confirmation() -> void:
	var scope := _scope("f")
	var database := _open(scope)
	var server_display: float = float(Time.get_unix_time_from_datetime_string("2026-09-19T10:00:00"))
	var local_ts: float = server_display - float(Time.get_time_zone_from_system().bias) * 60.0
	_execute(database, "save_local", scope, {"message": _local("local-hello", "hello", "sent", local_ts)})
	_execute(database, "save_local", scope, {"message": {
		"id": "reply-uuid", "id_source": "local", "role": "assistant", "type": "text",
		"text": "hi", "timestamp": local_ts, "status": "received", "code": "",
	}})
	var page: Dictionary = _execute(database, "save_page", scope, {
		"page": {"start_index": 0, "history": [
			{"uuid": "srv-hello", "source": "user", "type": "text", "content": "hello", "timestamp": "2026-09-19 10:00:00"},
			{"uuid": "reply-uuid", "source": "agent", "type": "text", "content": "hi", "timestamp": "2026-09-19 10:00:01"},
		]},
		"context": {"direction": "initial"},
	})
	check(page.ok, "confirmation page saves")
	var removed: Array = page.data.removed
	check(removed.has("local-hello") and removed.has("reply-uuid"), "both confirmation paths remove local rows")
	var remaining: int = int(_row(database, "SELECT COUNT(*) AS count FROM local_messages")["count"])
	check(remaining == 0, "confirmed local tail is gone")
	check(page.data.ids == ["srv-hello", "reply-uuid"], "server ids are reported for the view")
	database.close()


func _case_confirmation_keeps_sending() -> void:
	var scope := _scope("e1")
	var database := _open(scope)
	var server_display: float = float(Time.get_unix_time_from_datetime_string("2026-09-19T10:00:00"))
	var local_ts: float = server_display - float(Time.get_time_zone_from_system().bias) * 60.0
	_execute(database, "save_local", scope, {"message": _local("sending-hello", "hello", "sending", local_ts)})
	_execute(database, "save_local", scope, {"message": _local("failed-note", "not sent", "failed", local_ts)})
	var page: Dictionary = _execute(database, "save_page", scope, {
		"page": {"start_index": 0, "history": [
			{"uuid": "srv-hello", "source": "user", "type": "text", "content": "hello", "timestamp": "2026-09-19 10:00:00"},
			{"uuid": "srv-note", "source": "user", "type": "text", "content": "not sent", "timestamp": "2026-09-19 10:00:01"},
		]},
		"context": {"direction": "initial"},
	})
	check(page.ok, "confirmation page with in-flight rows saves")
	check(not page.data.removed.has("sending-hello"), "sending row is not claimed by content match")
	check(not page.data.removed.has("failed-note"), "failed row is not claimed by content match")
	check(int(_row(database, "SELECT COUNT(*) AS count FROM local_messages")["count"]) == 2,
		"in-flight and failed local rows remain visible")
	database.close()


func _case_delete_local() -> void:
	var scope := _scope("1")
	var database := _open(scope)
	_execute(database, "save_local", scope, {"message": _local("victim", "x", "failed")})
	var deleted: Dictionary = _execute(database, "delete_local", scope, {"message_id": "victim"})
	check(deleted.ok, "delete local row")
	check(int(_row(database, "SELECT COUNT(*) AS count FROM local_messages")["count"]) == 0, "deleted row is gone")
	var missing: Dictionary = _execute(database, "update_local", scope, {
		"message_id": "victim", "patch": {"state": "sent"},
	})
	check(not missing.ok and missing.code == "LOCAL_MESSAGE_MISSING", "updating a missing row is explicit")
	database.close()


func _case_query_plan() -> void:
	var scope := _scope("2")
	var database := _open(scope)
	var latest: Dictionary = database._access.query(
		"EXPLAIN QUERY PLAN SELECT * FROM messages ORDER BY server_index DESC LIMIT 30")
	var older: Dictionary = database._access.query(
		"EXPLAIN QUERY PLAN SELECT * FROM messages WHERE server_index < ? ORDER BY server_index DESC LIMIT 30", [10])
	check(_plan_uses(latest, "messages_server_index"), "latest page uses the slot index")
	check(_plan_uses(older, "messages_server_index"), "older page uses the slot index")
	var local: Dictionary = database._access.query(
		"EXPLAIN QUERY PLAN SELECT * FROM local_messages WHERE local_seq < ? ORDER BY local_seq DESC LIMIT 30", [10])
	check(_plan_uses(local, "local_messages_seq"), "local tail paging uses the sequence index")
	database.close()


func _plan_uses(result: Dictionary, index: String) -> bool:
	for row in database_rows(result):
		if str(row.get("detail", "")).contains(index):
			return true
	return false


func database_rows(result: Dictionary) -> Array:
	return result.get("data", {}).get("rows", [])


func _case_stale_scope() -> void:
	var scope := _scope("3")
	var database := _open(scope)
	var stale: Dictionary = _execute(database, "read_latest", _scope("4"), {"limit": 30})
	check(not stale.ok and stale.code == "STALE_SCOPE", "cross-scope reads are rejected")
	var write: Dictionary = _execute(database, "save_local", _scope("4"), {
		"message": _local("x", "x", "pending"),
	})
	check(not write.ok and write.code == "STALE_SCOPE", "cross-scope writes are rejected")
	var stale_close: Dictionary = _execute(database, "close_scope", _scope("4"))
	check(not stale_close.ok and stale_close.code == "STALE_SCOPE", "cross-scope close is rejected")
	check(database.metadata().ok, "stale close leaves the connection open")
	var closed: Dictionary = _execute(database, "close_scope", scope)
	check(closed.ok, "own scope can close the connection")


func _case_config_rebuild() -> void:
	var scope := _scope("6")
	var directory := _root.path_join(scope)
	DirAccess.make_dir_recursive_absolute(directory)
	var path := directory.path_join("history.db")
	var raw: Object = ClassDB.instantiate("SQLite")
	raw.path = path
	raw.open_db()
	raw.query("PRAGMA auto_vacuum=0")
	raw.query("PRAGMA user_version=100")
	raw.query("PRAGMA application_id=1280591961")
	raw.close_db()
	var database = Database.new()
	var opened: Dictionary = database.open(_root, scope)
	check(opened.ok, "config mismatch rebuilds the cache")
	check(_recovery_files(directory).size() == 1, "config rebuild keeps a recovery copy")
	database.close()


func _case_explicit_reset() -> void:
	var scope := _scope("6a")
	var database := _open(scope)
	var path: String = str(database._path)
	var directory := path.get_base_dir()
	var lock := FileAccess.open(path, FileAccess.READ)
	var blocked: Dictionary = _execute(database, "reset_scope", scope)
	check(not blocked.ok and blocked.code == "CACHE_RESET_FAILED", "occupied database cannot be reset")
	lock.close()
	check(database.open(_root, scope).ok, "database reopens after releasing the lock")
	var reset: Dictionary = _execute(database, "reset_scope", scope)
	check(reset.ok, "explicit reset rebuilds the cache")
	check(_recovery_files(directory).size() == 1, "explicit reset keeps a recovery copy")
	database.close()


func _recovery_files(directory: String) -> Array:
	return Array(DirAccess.get_files_at(directory)).filter(func(name): return str(name).contains(".recovery-"))


func _case_reset_legacy() -> void:
	var scope := _scope("5")
	var directory := _root.path_join(scope)
	DirAccess.make_dir_recursive_absolute(directory)
	var path := directory.path_join("history.db")
	var legacy: Object = ClassDB.instantiate("SQLite")
	legacy.path = path
	legacy.open_db()
	legacy.query("PRAGMA user_version=3")
	legacy.query("CREATE TABLE messages (message_id TEXT PRIMARY KEY)")
	legacy.query("INSERT INTO messages(message_id) VALUES ('old')")
	legacy.close_db()
	check(FileAccess.file_exists(path), "legacy fixture exists")
	for suffix in ["-wal", "-shm", ".v1.bak", ".v2.bak", ".discarded"]:
		var stale := FileAccess.open(path + suffix, FileAccess.WRITE)
		stale.store_string("stale")
		stale.close()
	var database = Database.new()
	var reset: Dictionary = database._discard_incompatible(path)
	check(reset.ok, "legacy reset succeeds")
	for suffix in ["-wal", "-shm", ".v1.bak", ".v2.bak", ".discarded"]:
		check(not FileAccess.file_exists(path + suffix), "legacy %s is removed" % suffix)
	var opened: Dictionary = database.open(_root, scope)
	check(opened.ok, "legacy cache is rebuilt (%s)" % opened.code)
	check(int(_row(database, "PRAGMA user_version")["user_version"]) == 100, "rebuilt cache has version 100")
	check(int(_row(database, "SELECT COUNT(*) AS count FROM messages")["count"]) == 0, "legacy rows are not migrated")
	var columns: Array = database._access.column_names("messages")
	check(columns.has("server_index") and columns.has("sent_ts_ms"), "rebuilt table uses the new columns")
	database.close()
	var header := _header(path)
	check(int(header.application_id) == 1280591961 and int(header.version) == 100, "file header advertises the new cache")


## 主库不存在时，残留 sidecar/备份也不能与新库配对。
func _case_reset_orphans() -> void:
	var scope := _scope("8")
	var directory := _root.path_join(scope)
	DirAccess.make_dir_recursive_absolute(directory)
	var path := directory.path_join("history.db")
	for suffix in ["-wal", "-shm", ".v1.bak", ".v2.bak", ".discarded"]:
		var stale := FileAccess.open(path + suffix, FileAccess.WRITE)
		stale.store_string("orphan")
		stale.close()
	var database = Database.new()
	var cleanup: Dictionary = database._discard_incompatible(path)
	check(cleanup.ok, "orphan cleanup succeeds")
	for suffix in ["-wal", "-shm", ".v1.bak", ".v2.bak", ".discarded"]:
		check(not FileAccess.file_exists(path + suffix), "orphan %s is removed" % suffix)
	var opened: Dictionary = database.open(_root, scope)
	check(opened.ok, "orphan sidecars do not block a fresh cache (%s)" % opened.code)
	database.close()


## 表结构完整但单行状态丢失时，补回绑定当前 scope 的状态行。
func _case_repair_metadata() -> void:
	var scope := _scope("9")
	var database := _open(scope)
	database._access.execute("DELETE FROM sync_state")
	database._access.execute("DELETE FROM dynamic_state")
	database.close()
	database = _open(scope)
	var meta: Dictionary = database.metadata()
	check(meta.ok and int(meta.data.baseline_index) == -1, "missing chat state is recreated")
	var state: Dictionary = _execute(database, "dynamics_state", scope)
	check(state.ok and str(state.data.state.scope_key) == scope, "missing dynamics state is recreated")
	database.close()


func _header(path: String) -> Dictionary:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return {}
	file.seek(0)
	var bytes := file.get_buffer(100)
	file.close()
	return {
		"version": (int(bytes[60]) << 24) | (int(bytes[61]) << 16) | (int(bytes[62]) << 8) | int(bytes[63]),
		"application_id": (int(bytes[68]) << 24) | (int(bytes[69]) << 16) | (int(bytes[70]) << 8) | int(bytes[71]),
	}
