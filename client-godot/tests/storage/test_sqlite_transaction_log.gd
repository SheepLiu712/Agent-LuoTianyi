extends SceneTree
const Access = preload("res://src/storage/sqlite_access.gd")
const Worker = preload("res://src/storage/sqlite_worker.gd")
var failures: Array[String] = []

class FakeDB:
	extends RefCounted
	var query_result: Array = []
	var fail_on := ""
	var error_message := "synthetic sqlite error"
	func query_with_bindings(sql: String, _bindings: Array = []) -> bool:
		return sql != fail_on

class FakeLogger:
	extends RefCounted
	var entries: Array = []
	func record_as(category: String, event: String, fields: Dictionary) -> Error:
		entries.append({"category":category, "event":event, "fields":fields})
		return OK

func check(value: bool, description: String) -> void:
	if not value:
		failures.append(description)
		print("FAIL: ", description)

func _initialize() -> void:
	var db := FakeDB.new()
	var access := Access.new(db)
	_check_commit(access)
	_check_rollback(access)
	_check_rollback_failure(access, db)
	_check_failures(access, db)
	_check_sql_details(access, db)
	_check_worker()
	print("SQLite transaction logging: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func _check_commit(access) -> void:
	var committed: Dictionary = access.transaction(func(): return Access.success(), "save_live")
	check(committed.ok and committed.transaction.phase == "committed", "commit transaction metadata")
	check(committed.transaction.scope == "sqlite" and committed.transaction.operation == "save_live", "transaction scope and operation")
	check(committed.transaction.trace_id == committed.transaction.transaction_id, "transaction trace id")

func _check_rollback(access) -> void:
	var rolled: Dictionary = access.transaction(func(): return Access.failure("CACHE_SQL_FAILED"), "save_page")
	check(not rolled.ok and rolled.transaction.phase == "rolled_back", "rollback transaction metadata")

func _check_rollback_failure(access, db) -> void:
	db.fail_on = "ROLLBACK"
	var rolled: Dictionary = access.transaction(func(): return Access.failure("CACHE_SQL_FAILED", "original sql detail"), "save_page")
	check(not rolled.ok and rolled.code == "CACHE_SQL_FAILED", "rollback failure keeps original code")
	check(rolled.detail.contains("original sql detail") and rolled.detail.contains("synthetic sqlite error"),
		"rollback failure keeps original and rollback detail")
	db.fail_on = ""

func _check_failures(access, db) -> void:
	db.fail_on = "BEGIN IMMEDIATE"
	var begin_failed: Dictionary = access.transaction(func(): return Access.success(), "save_reconcile")
	check(not begin_failed.ok and begin_failed.transaction.phase == "begin_failed", "begin failure metadata")
	db.fail_on = "COMMIT"
	var commit_failed: Dictionary = access.transaction(func(): return Access.success(), "update_attempt")
	check(not commit_failed.ok and commit_failed.transaction.phase == "commit_failed", "commit failure metadata")

func _check_sql_details(access, db) -> void:
	db.fail_on = "SELECT broken"
	var failed: Dictionary = access.query("SELECT broken")
	check(failed.code == "CACHE_SQL_FAILED" and failed.detail.contains("synthetic sqlite error")
		and failed.detail.contains("SELECT broken"), "sql failure keeps driver message and statement")
	db.fail_on = ""
	var offline := Access.new(null)
	var unavailable: Dictionary = offline.query("SELECT 1")
	check(unavailable.code == "CACHE_CONNECTION_INVALID" and not unavailable.detail.is_empty(),
		"missing connection failure explains itself")

func _check_worker() -> void:
	var logger := FakeLogger.new()
	var worker = Worker.new(func(): return FakeDB.new(), logger)
	worker._log_result({"ok":true, "operation":"save_live", "duration_ms":2,
		"transaction":{"transaction_id":"tx_abcdef123456", "scope":"sqlite", "operation":"save_live",
			"phase":"committed", "outcome":"success", "duration_ms":2, "trace_id":"tx_abcdef123456"}})
	check(logger.entries.size() == 1 and logger.entries[0].event == "storage_sqlite_operation", "single sqlite operation logged")
	check(logger.entries[0].category == "storage" and logger.entries[0].fields.phase == "committed" and logger.entries[0].fields.scope == "sqlite", "sqlite transaction fields merged")
	check(logger.entries[0].fields.transaction_id == "tx_abcdef123456", "sqlite transaction id kept")
	worker._log_result({"ok":true, "operation":"read_latest", "duration_ms":4, "code":"OK"})
	check(logger.entries.size() == 1, "fast reads are not logged")
	worker._log_result({"ok":true, "operation":"read_latest", "duration_ms":20, "code":"OK"})
	check(logger.entries.size() == 2, "slow reads are logged")
	worker._log_result({"ok":false, "operation":"save_live", "duration_ms":1, "code":"CACHE_SQL_FAILED", "detail":"boom"})
	check(logger.entries.size() == 3 and logger.entries[2].fields.level == "ERROR", "failed operations are logged")
	worker.free()
