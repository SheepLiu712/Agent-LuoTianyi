extends SceneTree
const Access = preload("res://src/storage/sqlite_access.gd")
const Worker = preload("res://src/storage/sqlite_worker.gd")
var failures: Array[String] = []

class FakeDB:
	extends RefCounted
	var query_result: Array = []
	var fail_on := ""
	func query_with_bindings(sql: String, _bindings: Array = []) -> bool:
		return sql != fail_on

class FakeLogger:
	extends RefCounted
	var performance: Array = []
	var transactions: Array = []
	func log_performance(event: String, fields: Dictionary) -> Error:
		performance.append({"event":event, "fields":fields})
		return OK
	func log_transaction(event: String, fields: Dictionary) -> Error:
		transactions.append({"event":event, "fields":fields})
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
	_check_failures(access, db)
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

func _check_failures(access, db) -> void:
	db.fail_on = "BEGIN IMMEDIATE"
	var begin_failed: Dictionary = access.transaction(func(): return Access.success(), "save_reconcile")
	check(not begin_failed.ok and begin_failed.transaction.phase == "begin_failed", "begin failure metadata")
	db.fail_on = "COMMIT"
	var commit_failed: Dictionary = access.transaction(func(): return Access.success(), "update_attempt")
	check(not commit_failed.ok and commit_failed.transaction.phase == "commit_failed", "commit failure metadata")

func _check_worker() -> void:
	var logger := FakeLogger.new()
	var worker = Worker.new(func(): return FakeDB.new(), logger)
	worker._log_result({"ok":true, "operation":"save_live", "duration_ms":2,
		"transaction":{"transaction_id":"tx_abcdef123456", "scope":"sqlite", "operation":"save_live",
			"phase":"committed", "outcome":"success", "duration_ms":2, "trace_id":"tx_abcdef123456"}})
	check(logger.performance.size() == 1 and logger.performance[0].event == "performance_sqlite", "sqlite performance logged")
	check(logger.transactions.size() == 1 and logger.transactions[0].event == "transaction_sqlite", "sqlite transaction logged")
	check(logger.transactions[0].fields.phase == "committed" and logger.transactions[0].fields.scope == "sqlite", "sqlite transaction fields")
	worker.free()
