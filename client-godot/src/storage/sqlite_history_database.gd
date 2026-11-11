extends RefCounted
## 账号作用域内的历史库仓储：连接生命周期 + 命令白名单。
## 对外只有一个入口 `execute(operation, payload)`，因此工作线程只需要搬运纯数据；
## 连接、迁移、结构校验、命令分发全部收在这里，不向上层泄漏 SQLite 细节。
## 除 `open_scope` 外，所有命令都必须核对 scope，防止旧账号的请求写进新账号。

const Schema = preload("res://src/storage/history_schema.gd")
const Access = preload("res://src/storage/sqlite_access.gd")
const Reader = preload("res://src/storage/timeline_reader.gd")
const Writer = preload("res://src/storage/history_page_writer.gd")
const Installer = preload("res://src/storage/history_schema_installer.gd")
const Migration = preload("res://src/storage/history_migration.gd")

var _db: Object
var _access: RefCounted
var _reader: RefCounted
var _writer: RefCounted
var _scope := ""
var _path := ""
var _handlers: Dictionary = {}


func _init() -> void:
	_configure_handlers()


func open(root_path: String, scope: String) -> Dictionary:
	close()
	var preflight := _preflight(root_path, scope)
	if not preflight.ok:
		return preflight
	var opened := _open_connection(str(preflight.data.path), scope)
	if not opened.ok:
		return opened
	return _prepare()


func close() -> void:
	if _db != null:
		_db.close_db()
	_db = null
	_access = null
	_reader = null
	_writer = null
	_scope = ""
	_path = ""


func metadata() -> Dictionary:
	var result: Dictionary = _access.query(Schema.READ_SYNC_STATE)
	if not result.ok:
		return result
	var row: Dictionary = _access.first_row(result)
	if row.is_empty():
		return _failure("CACHE_METADATA_INVALID")
	return _success({
		"scope": _scope,
		"epoch": int(row.active_epoch),
		"order_revision": int(row.order_revision),
		"next_end": int(row.next_end),
		"caught_up": int(row.caught_up),
		"baseline": _text_or_empty(row.get("baseline_message_id")),
	})


func _configure_handlers() -> void:
	_handlers = {
		"open_scope": _open_command,
		"read_latest": _read_latest_command,
		"read_before": _read_before_command,
		"save_live": _save_live_command,
		"save_history": _save_history_command,
		"save_reconcile": _save_reconcile_command,
		"reconcile_delivery": _reconcile_delivery_command,
		"record_attempt": _record_attempt_command,
		"update_attempt": _update_attempt_command,
		"read_sync_state": _read_sync_command,
		"flush": _flush_command,
		"close_scope": _close_command,
	}


func execute(operation: String, payload: Dictionary) -> Dictionary:
	if not _handlers.has(operation):
		return _failure("UNKNOWN_STORAGE_OPERATION")
	var handler: Callable = _handlers[operation]
	return handler.call(payload)


func _open_command(payload: Dictionary) -> Dictionary:
	return open(str(payload.get("root", "")), str(payload.get("scope", "")))


func _read_latest_command(payload: Dictionary) -> Dictionary:
	var guard := _guard(payload)
	if not guard.ok:
		return guard
	return _reader.latest(int(payload.get("limit", Reader.DEFAULT_LIMIT)))


func _read_before_command(payload: Dictionary) -> Dictionary:
	var guard := _guard(payload)
	if not guard.ok:
		return guard
	return _reader.before(str(payload.get("anchor_id", "")), int(payload.get("limit", Reader.DEFAULT_LIMIT)))


func _save_live_command(payload: Dictionary) -> Dictionary:
	var guard := _guard(payload)
	if not guard.ok:
		return guard
	return _writer.save_live(payload.get("message", {}))


func _save_history_command(payload: Dictionary) -> Dictionary:
	var guard := _guard(payload)
	if not guard.ok:
		return guard
	return _writer.save_page(payload.get("page", {}), payload.get("context", {}))


func _save_reconcile_command(payload: Dictionary) -> Dictionary:
	var guard := _guard(payload)
	if not guard.ok:
		return guard
	return _writer.save_reconcile(payload.get("rows", []))


func _reconcile_delivery_command(payload: Dictionary) -> Dictionary:
	var guard := _guard(payload)
	if not guard.ok:
		return guard
	return _writer.reconcile_delivery()


func _record_attempt_command(payload: Dictionary) -> Dictionary:
	var guard := _guard(payload)
	if not guard.ok:
		return guard
	return _writer.record_attempt(payload)


func _update_attempt_command(payload: Dictionary) -> Dictionary:
	var guard := _guard(payload)
	if not guard.ok:
		return guard
	return _writer.update_attempt(payload)


func _read_sync_command(payload: Dictionary) -> Dictionary:
	var guard := _guard(payload)
	if not guard.ok:
		return guard
	return metadata()


func _flush_command(payload: Dictionary) -> Dictionary:
	var guard := _guard(payload)
	if not guard.ok:
		return guard
	return _access.execute(Schema.WAL_CHECKPOINT)


func _close_command(_payload: Dictionary) -> Dictionary:
	close()
	return _success()


func _guard(payload: Dictionary) -> Dictionary:
	return _success() if str(payload.get("scope", "")) == _scope else _failure("STALE_SCOPE")


func _preflight(root_path: String, scope: String) -> Dictionary:
	if not _valid_scope(scope):
		return _failure("INVALID_INPUT")
	if not ClassDB.class_exists("SQLite"):
		return _failure("STORAGE_UNAVAILABLE")
	var directory := root_path.path_join(scope)
	if DirAccess.make_dir_recursive_absolute(directory) != OK:
		return _failure("CACHE_WRITE_FAILED")
	return _success({"path": directory.path_join("history.db")})


func _open_connection(path: String, scope: String) -> Dictionary:
	var db: Object = ClassDB.instantiate("SQLite")
	if db == null:
		return _failure("STORAGE_UNAVAILABLE")
	db.path = path
	db.verbosity_level = 0
	db.foreign_keys = true
	if not db.open_db():
		return _failure("CACHE_OPEN_FAILED")
	_attach(db, path, scope)
	return _success()


func _attach(db: Object, path: String, scope: String) -> void:
	_db = db
	_path = path
	_scope = scope
	_access = Access.new(db)
	_reader = Reader.new(_access)
	_writer = Writer.new(_access)


func _prepare() -> Dictionary:
	var configured := _configure()
	if not configured.ok:
		return _abort(configured)
	var schema := _ensure_schema()
	if not schema.ok:
		return _abort(schema)
	var recovered := _recover_delivery()
	return _abort(recovered) if not recovered.ok else metadata()


func _configure() -> Dictionary:
	for pragma in Schema.PRAGMAS:
		var result: Dictionary = _access.execute(pragma)
		if not result.ok:
			return result
	return _verify_pragmas()


func _verify_pragmas() -> Dictionary:
	var foreign: Dictionary = _access.query("PRAGMA foreign_keys")
	if not foreign.ok:
		return foreign
	if int(_access.first_row(foreign).get("foreign_keys", 0)) != 1:
		return _failure("CACHE_CONFIG_FAILED")
	var journal: Dictionary = _access.query("PRAGMA journal_mode")
	if not journal.ok:
		return journal
	var mode := str(_access.first_row(journal).values()[0]).to_lower()
	return _success() if mode == "wal" else _failure("CACHE_CONFIG_FAILED")


func _ensure_schema() -> Dictionary:
	var version := _version()
	if not version.ok:
		return version
	var state := _schema_state(int(version.data.version))
	if state == "current":
		return _validate()
	if state == "fresh":
		return _install()
	if state == "legacy":
		return _rebuild(int(version.data.version))
	return _failure("CACHE_VERSION_UNSUPPORTED")


func _version() -> Dictionary:
	var result: Dictionary = _access.query(Schema.READ_VERSION)
	if not result.ok:
		return result
	var row: Dictionary = _access.first_row(result)
	return _success({"version": int(row.get("user_version", 0))})


## 版本号不足信：0 号版本既可能是空库，也可能是没有 user_version 的草稿库。
func _schema_state(version: int) -> String:
	if version == Schema.VERSION:
		return "current"
	if version == 0:
		return _unversioned_state()
	if version == 1 or version == 2:
		return "legacy"
	return "unsupported"


func _unversioned_state() -> String:
	if not _access.has_table("messages"):
		return "fresh"
	if not _access.column_names("messages").has("message_id"):
		return "legacy"
	# version=0 且结构缺表/缺列：这是建库中断留下的半成品，不能当 current。
	if not _missing_tables().is_empty() or not _missing_columns().is_empty():
		return "fresh"
	if not Schema.REQUIRED_UNIQUE_INDEX in _access.index_names("messages"):
		return "fresh"
	return "current"


func _install() -> Dictionary:
	return _access.transaction(_install_in_transaction, "install_schema")


## 建表、写 epoch/scope、写 user_version 必须同事务；
## 否则崩溃会留下一个被误判为 current 的永久坏库。
func _install_in_transaction() -> Dictionary:
	var dropped: Dictionary = _access.execute_block(Schema.DROP_V3)
	if not dropped.ok:
		return dropped
	var created: Dictionary = _access.execute_block(Schema.CREATE_V3)
	if not created.ok:
		return created
	var installed := Installer.install_scope(_access, _scope)
	if not installed.ok:
		return installed
	var versioned := Installer.set_version(_access)
	if not versioned.ok:
		return versioned
	return _validate()


## 迁移必须先备份再改结构；备份在连接关闭状态完成。
func _rebuild(version: int) -> Dictionary:
	var checkpoint: Dictionary = _access.execute(Schema.WAL_CHECKPOINT)
	if not checkpoint.ok:
		return checkpoint
	var path := _path
	var scope := _scope
	close()
	var backup := Migration.backup(path, version)
	var reopened := _open_connection(path, scope)
	if not reopened.ok:
		return reopened
	if not backup.ok:
		return backup
	var migrated := Migration.migrate(_access, scope)
	return migrated if not migrated.ok else _validate()


func _validate() -> Dictionary:
	var missing := _missing_tables()
	if not missing.is_empty():
		return _failure("CACHE_SCHEMA_INVALID")
	if not _missing_columns().is_empty():
		return _failure("CACHE_SCHEMA_INVALID")
	if not Schema.REQUIRED_UNIQUE_INDEX in _access.index_names("messages"):
		return _failure("CACHE_SCHEMA_INVALID")
	if not _window_functions_available():
		return _failure("CACHE_SCHEMA_INVALID")
	return _validate_scope()


func _missing_tables() -> Array:
	var missing: Array = []
	for table in Schema.REQUIRED_TABLES:
		if not _access.has_table(table):
			missing.append(table)
	return missing


func _missing_columns() -> Array:
	var missing: Array = []
	for table in Schema.REQUIRED_COLUMNS:
		var present: Array = _access.column_names(table)
		for column in Schema.REQUIRED_COLUMNS[table]:
			if not present.has(column):
				missing.append("%s.%s" % [table, column])
	return missing


func _window_functions_available() -> bool:
	var result: Dictionary = _access.query("SELECT ROW_NUMBER() OVER(ORDER BY value) AS n FROM (SELECT 1 AS value)")
	return result.ok


## 结构就绪但缺少 scope 行时补建，避免「能查但永远写不进去」。
func _validate_scope() -> Dictionary:
	var result: Dictionary = _access.query(Schema.READ_SCOPE_KEY)
	if not result.ok:
		return result
	var row: Dictionary = _access.first_row(result)
	if row.is_empty():
		return _access.transaction(func(): return Installer.install_scope(_access, _scope), "install_scope")
	return _success() if str(row.scope_key) == _scope else _failure("STALE_SCOPE")


func _recover_delivery() -> Dictionary:
	return _access.execute_block(Schema.RECOVER_UNCERTAIN + ";\n" + Schema.RECOVER_UNSENT)


func _abort(result: Dictionary) -> Dictionary:
	close()
	return result


static func _valid_scope(scope: String) -> bool:
	return scope.length() == 64 and scope.is_valid_hex_number(false)


static func _text_or_empty(value: Variant) -> String:
	return "" if value == null else str(value)


static func _failure(code: String) -> Dictionary:
	return {"ok": false, "code": code, "data": {}}


static func _success(data: Dictionary = {}) -> Dictionary:
	return {"ok": true, "code": "OK", "data": data}
