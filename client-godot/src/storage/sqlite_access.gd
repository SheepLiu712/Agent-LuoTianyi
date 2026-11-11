extends RefCounted
## SQLite 访问层：唯一持有 SQL 执行细节的地方。
## 只做四件事：查、执行、按块执行、事务包裹。
## 业务语义（分页、去重、重编号）一律不在这一层，
## 上层因此可以只依赖 `{ok, code, data}` 这一种返回形态。

const Schema = preload("res://src/storage/history_schema.gd")
const LogSchema = preload("res://src/storage/log_schema.gd")

var _db: Object


func _init(db: Object) -> void:
	_db = db


static func failure(code: String) -> Dictionary:
	return {"ok": false, "code": code, "data": {}}


static func success(data: Dictionary = {}) -> Dictionary:
	return {"ok": true, "code": "OK", "data": data}


func query(sql: String, bindings: Array = []) -> Dictionary:
	if not ready():
		return failure("CACHE_CONNECTION_INVALID")
	if not _db.query_with_bindings(sql, bindings):
		return failure("CACHE_SQL_FAILED")
	return success({"rows": _db.query_result.duplicate(true)})


func execute(sql: String, bindings: Array = []) -> Dictionary:
	if not ready():
		return failure("CACHE_CONNECTION_INVALID")
	if not _db.query_with_bindings(sql, bindings):
		return failure("CACHE_SQL_FAILED")
	return success()


## 逐条执行多语句块；任一失败即返回，不再继续后续语句。
func execute_block(block: String) -> Dictionary:
	for sql in Schema.statements(block):
		var result := execute(sql)
		if not result.ok:
			return result
	return success()


## BEGIN IMMEDIATE：写事务一开始就拿写锁，避免提交时才暴露冲突。
func transaction(action: Callable, label: String = "") -> Dictionary:
	if not ready():
		return failure("CACHE_CONNECTION_INVALID")
	var started := Time.get_ticks_usec()
	var transaction_id := LogSchema.new_transaction_id()
	var begun := execute("BEGIN IMMEDIATE")
	if not begun.ok:
		begun.transaction = _transaction_meta(transaction_id, label, "begin_failed", "failure", started)
		return begun
	var result: Dictionary = action.call()
	if not result.get("ok", false):
		var rolled := _rollback(result)
		rolled.transaction = _transaction_meta(transaction_id, label, "rolled_back", "failure", started)
		return rolled
	var committed := execute("COMMIT")
	if not committed.ok:
		var failed := _rollback(committed)
		failed.transaction = _transaction_meta(transaction_id, label, "commit_failed", "failure", started)
		return failed
	result.transaction = _transaction_meta(transaction_id, label, "committed", "success", started)
	return result

func _transaction_meta(transaction_id: String, label: String, phase: String, outcome: String, started: int) -> Dictionary:
	return {"transaction_id":transaction_id, "scope":"sqlite", "operation":label if not label.is_empty() else "unknown",
		"phase":phase, "outcome":outcome, "duration_ms":int((Time.get_ticks_usec() - started) / 1000),
		"trace_id":transaction_id}


func ready() -> bool:
	return _db != null


func first_row(result: Dictionary) -> Dictionary:
	var rows: Array = result.get("data", {}).get("rows", [])
	return rows[0] if not rows.is_empty() else {}


func rows_of(result: Dictionary) -> Array:
	return result.get("data", {}).get("rows", [])


## 表名只来自本工程的常量，不接受外部输入。
func has_table(name: String) -> bool:
	var result := query("SELECT name FROM sqlite_master WHERE type='table' AND name=?", [name])
	return result.ok and not rows_of(result).is_empty()


func column_names(table: String) -> Array:
	var names: Array = []
	for row in rows_of(query(Schema.TABLE_COLUMNS % table)):
		names.append(str(row.name))
	return names


func index_names(table: String) -> Array:
	var names: Array = []
	for row in rows_of(query(Schema.TABLE_INDEXES % table)):
		names.append(str(row.name))
	return names


func table_names() -> Array:
	var names: Array = []
	for row in rows_of(query(Schema.SCHEMA_TABLES)):
		names.append(str(row.name))
	return names


func foreign_key_violations() -> Array:
	return rows_of(query(Schema.FOREIGN_KEY_CHECK))


func _rollback(failure_result: Dictionary) -> Dictionary:
	if not execute("ROLLBACK").ok:
		return failure("CACHE_CONNECTION_INVALID")
	return failure_result
