extends RefCounted
## 账号作用域内的本地库仓储：连接生命周期 + 命令白名单 + 硬重置。
## 对外只有一个入口 `execute(operation, payload)` 与 `open(root, scope)`；
## 连接、建库、文件头检测、命令分发全部收在这里，不向上层泄漏 SQLite 细节。
## 除 `open_scope` 外，所有命令都必须核对 scope，防止旧账号的请求写进新账号。

const Schema = preload("res://src/storage/history_schema.gd")
const Access = preload("res://src/storage/sqlite_access.gd")
const Reader = preload("res://src/storage/timeline_reader.gd")
const Writer = preload("res://src/storage/history_page_writer.gd")
const Installer = preload("res://src/storage/history_schema_installer.gd")
const DynamicsStore = preload("res://src/storage/dynamics_store.gd")

## 文件头偏移：SQLite 头固定 100 字节，user_version@60、application_id@68。
const HEADER_SIZE := 100
const USER_VERSION_OFFSET := 60
const APPLICATION_ID_OFFSET := 68
## 先删 WAL/SHM，最后删主库：即使中途失败，也不会留下「新库 + 旧 WAL」的配对。
const CRITICAL_CACHE_SUFFIXES := ["-wal", "-shm", ""]
const BACKUP_FILE_SUFFIXES := [".v1.bak", ".v2.bak", ".discarded"]
const WAITING_HISTORY_TTL_MS := 24 * 60 * 60 * 1000

var _db: Object
var _access: RefCounted
var _reader: RefCounted
var _writer: RefCounted
var _dynamics: RefCounted
var _scope := ""
var _path := ""
var _rebuild_attempted := false
var _handlers: Dictionary = {}


func _init() -> void:
	_configure_handlers()


func open(root_path: String, scope: String) -> Dictionary:
	close()
	_rebuild_attempted = false
	var preflight := _preflight(root_path, scope)
	if not preflight.ok:
		return preflight
	var opened := _open_connection(str(preflight.data.path), scope)
	if not opened.ok:
		close()
		return opened
	var prepared: Dictionary = _prepare()
	if not prepared.ok:
		close()
	return prepared


func close() -> void:
	if _db != null:
		if _access != null:
			_access.execute(Schema.WAL_CHECKPOINT)
			_access.execute(Schema.OPTIMIZE)
		_db.close_db()
	_db = null
	_access = null
	_reader = null
	_writer = null
	_dynamics = null
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
		"next_end": int(row.next_end),
		"baseline_index": int(row.baseline_index),
		"revision": int(row.revision),
	})


func execute(operation: String, payload: Dictionary) -> Dictionary:
	if not _handlers.has(operation):
		return _failure("UNKNOWN_STORAGE_OPERATION")
	var handler: Callable = _handlers[operation]
	return handler.call(payload)


func _configure_handlers() -> void:
	_handlers = {
		"open_scope": _open_command,
		"read_latest": _read_latest_command,
		"read_before": _read_before_command,
		"save_page": _save_page_command,
		"save_local": _save_local_command,
		"update_local": _update_local_command,
		"delete_local": _delete_local_command,
		"read_sync_state": _read_sync_command,
		"flush": _flush_command,
		"close_scope": _close_command,
		"reset_scope": _reset_command,
		"dynamics_load": _dynamics_load_command,
		"dynamics_save_posts": _dynamics_save_posts_command,
		"dynamics_save_comments": _dynamics_save_comments_command,
		"dynamics_mark_read": _dynamics_mark_read_command,
		"dynamics_state": _dynamics_state_command,
	}


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


func _save_page_command(payload: Dictionary) -> Dictionary:
	var guard := _guard(payload)
	if not guard.ok:
		return guard
	var page: Dictionary = payload.get("page", {})
	var context: Dictionary = payload.get("context", {})
	return _access.transaction(func(): return _writer.save_page(page, context), "save_page")


func _save_local_command(payload: Dictionary) -> Dictionary:
	var guard := _guard(payload)
	if not guard.ok:
		return guard
	var message: Dictionary = payload.get("message", {})
	var entry: Dictionary = payload.get("entry", {})
	return _access.transaction(func(): return _writer.save_local(message, entry), "save_local")


func _update_local_command(payload: Dictionary) -> Dictionary:
	var guard := _guard(payload)
	if not guard.ok:
		return guard
	var message_id := str(payload.get("message_id", ""))
	var patch: Dictionary = payload.get("patch", {})
	return _access.transaction(func(): return _writer.update_local(message_id, patch), "update_local")


func _delete_local_command(payload: Dictionary) -> Dictionary:
	var guard := _guard(payload)
	if not guard.ok:
		return guard
	return _writer.delete_local(str(payload.get("message_id", "")))


func _read_sync_command(payload: Dictionary) -> Dictionary:
	var guard := _guard(payload)
	if not guard.ok:
		return guard
	return metadata()


func _flush_command(payload: Dictionary) -> Dictionary:
	var guard := _guard(payload)
	if not guard.ok:
		return guard
	var checkpoint: Dictionary = _access.execute(Schema.WAL_CHECKPOINT)
	if not checkpoint.ok:
		return checkpoint
	return _access.execute(Schema.OPTIMIZE)


func _close_command(payload: Dictionary) -> Dictionary:
	var guard := _guard(payload)
	if not guard.ok:
		return guard
	close()
	return _success()


func _reset_command(payload: Dictionary) -> Dictionary:
	var guard := _guard(payload)
	if not guard.ok:
		return guard
	return reset()


## 显式重建：旧库改名为 recovery 文件，再创建空库；失败不会伪装成可用。
func reset() -> Dictionary:
	var path := _path
	var scope := _scope
	close()
	if FileAccess.file_exists(path):
		var backup := path + ".recovery-%d" % Time.get_ticks_usec()
		if DirAccess.rename_absolute(path, backup) != OK:
			return _failure("CACHE_RESET_FAILED")
	var sidecars := _delete_files(path, ["-wal", "-shm"])
	if not sidecars.ok:
		return sidecars
	var opened := _open_connection(path, scope)
	if not opened.ok:
		return opened
	_rebuild_attempted = false
	return _prepare()


func _dynamics_load_command(payload: Dictionary) -> Dictionary:
	var guard := _guard(payload)
	if not guard.ok:
		return guard
	return _dynamics.load(payload)


func _dynamics_save_posts_command(payload: Dictionary) -> Dictionary:
	var guard := _guard(payload)
	if not guard.ok:
		return guard
	return _dynamics.save_posts(payload)


func _dynamics_save_comments_command(payload: Dictionary) -> Dictionary:
	var guard := _guard(payload)
	if not guard.ok:
		return guard
	return _dynamics.save_comments(payload)


func _dynamics_mark_read_command(payload: Dictionary) -> Dictionary:
	var guard := _guard(payload)
	if not guard.ok:
		return guard
	return _dynamics.mark_read(payload)


func _dynamics_state_command(payload: Dictionary) -> Dictionary:
	var guard := _guard(payload)
	if not guard.ok:
		return guard
	return _dynamics.state(payload)


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
	var path := directory.path_join("history.db")
	var reset := _discard_incompatible(path)
	if not reset.ok:
		return reset
	return _success({"path": path})


## 只读文件头判断版本，绝不打开旧库（避免触发 WAL 回放）。
func _discard_incompatible(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		# 没有主库也要清掉崩溃残留的 sidecar / 旧版本备份，避免新库配旧日志。
		var orphan_sidecars := _delete_files(path, ["-wal", "-shm"])
		if not orphan_sidecars.ok:
			return orphan_sidecars
		_clear_backups(path)
		return _success()
	var header := _read_header(path)
	if not header.is_empty() \
			and int(header.get("version", -1)) in [100, Schema.VERSION] \
			and int(header.get("application_id", -1)) == Schema.APPLICATION_ID:
		_clear_backups(path)
		return _success()
	return _delete_cache_files(path)


func _read_header(path: String) -> Dictionary:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return {}
	var size := file.get_length()
	if size < HEADER_SIZE:
		file.close()
		return {}
	file.seek(0)
	var bytes := file.get_buffer(HEADER_SIZE)
	file.close()
	return {
		"version": _big_endian_32(bytes, USER_VERSION_OFFSET),
		"application_id": _big_endian_32(bytes, APPLICATION_ID_OFFSET),
	}


## 三件套必须一起删除；任一句柄被占用都直接失败，禁止降级使用旧库。
func _delete_cache_files(path: String) -> Dictionary:
	var critical := _delete_files(path, CRITICAL_CACHE_SUFFIXES)
	if not critical.ok:
		return critical
	_clear_backups(path)
	return _success()


func _delete_files(path: String, suffixes: Array) -> Dictionary:
	for suffix in suffixes:
		var target := path + str(suffix)
		if not FileAccess.file_exists(target):
			continue
		if DirAccess.remove_absolute(target) != OK:
			return _failure("CACHE_RESET_FAILED")
	return _success()


## 旧版本备份不参与新库配对，删除失败不应阻塞正常启动。
func _clear_backups(path: String) -> void:
	_delete_files(path, BACKUP_FILE_SUFFIXES)


func _open_connection(path: String, scope: String) -> Dictionary:
	var db: Object = ClassDB.instantiate("SQLite")
	if db == null:
		return _failure("STORAGE_UNAVAILABLE")
	db.path = path
	db.verbosity_level = 0
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
	_dynamics = DynamicsStore.new(_access)


func _prepare() -> Dictionary:
	var configured := _configure()
	if not configured.ok:
		if str(configured.get("code", "")) == "CACHE_CONFIG_FAILED" and not _rebuild_attempted:
			_rebuild_attempted = true
			var rebuilt := _rebuild_cache()
			if rebuilt.ok:
				return rebuilt
		return _abort(configured)
	var schema := _ensure_schema()
	if not schema.ok:
		return _abort(schema)
	var recovered := _recover_delivery()
	if not recovered.ok:
		return _abort(recovered)
	return metadata()


func _configure() -> Dictionary:
	for pragma in Schema.PRAGMAS:
		var result: Dictionary = _access.execute(pragma)
		if not result.ok:
			return result
	return _verify_pragmas()


func _verify_pragmas() -> Dictionary:
	var auto_vacuum: Dictionary = _access.query(Schema.READ_AUTO_VACUUM)
	if not auto_vacuum.ok:
		return auto_vacuum
	if int(_access.first_row(auto_vacuum).values()[0]) != 2:
		return _failure("CACHE_CONFIG_FAILED")
	var application: Dictionary = _access.query(Schema.READ_APPLICATION_ID)
	if not application.ok:
		return application
	if int(_access.first_row(application).values()[0]) != Schema.APPLICATION_ID:
		return _failure("CACHE_CONFIG_FAILED")
	var journal: Dictionary = _access.query(Schema.READ_JOURNAL_MODE)
	if not journal.ok:
		return journal
	if str(_access.first_row(journal).values()[0]).to_lower() != "wal":
		return _failure("CACHE_CONFIG_FAILED")
	var foreign: Dictionary = _access.query(Schema.READ_FOREIGN_KEYS)
	if not foreign.ok:
		return foreign
	if int(_access.first_row(foreign).values()[0]) != 1:
		return _failure("CACHE_CONFIG_FAILED")
	return _success()


func _ensure_schema() -> Dictionary:
	var version := _version()
	if not version.ok:
		return version
	if int(version.data.version) == Schema.VERSION:
		var valid := _validate()
		if valid.ok:
			return valid
		# 版本已标记但结构不完整：按测试期约定整库重建，避免永久卡死。
		return _rebuild_cache()
	if int(version.data.version) == 0:
		return _install()
	if int(version.data.version) == 100:
		var migrated: Dictionary = preload("res://src/storage/history_media_migration.gd").migrate(_access)
		if migrated.ok:
			var valid := _validate()
			if valid.ok:
				return valid
		return _rebuild_cache()
	return _rebuild_cache()


func _version() -> Dictionary:
	var result: Dictionary = _access.query(Schema.READ_VERSION)
	if not result.ok:
		return result
	var row: Dictionary = _access.first_row(result)
	return _success({"version": int(row.get("user_version", 0))})


func _install() -> Dictionary:
	return _access.transaction(_install_in_transaction, "install_schema")


func _install_in_transaction() -> Dictionary:
	var installed := Installer.install(_access, _scope)
	if not installed.ok:
		return installed
	return _validate()


func _rebuild_cache() -> Dictionary:
	var path := _path
	var scope := _scope
	close()
	if not FileAccess.file_exists(path):
		return _failure("CACHE_RESET_FAILED")
	# 配置损坏也先保留旧库，便于事后恢复待发消息。
	var backup := path + ".recovery-%d" % Time.get_ticks_usec()
	if DirAccess.rename_absolute(path, backup) != OK:
		return _failure("CACHE_RESET_FAILED")
	var sidecars := _delete_files(path, ["-wal", "-shm"])
	if not sidecars.ok:
		return sidecars
	var reopened := _open_connection(path, scope)
	if not reopened.ok:
		return reopened
	var configured := _configure()
	if not configured.ok:
		return configured
	return _install()


func _validate() -> Dictionary:
	var tables := _validate_tables()
	if not tables.ok:
		return tables
	var columns := _validate_columns()
	if not columns.ok:
		return columns
	var indexes := _validate_indexes()
	if not indexes.ok:
		return indexes
	if not _access.foreign_key_violations().is_empty():
		return _failure("CACHE_INTEGRITY_FAILED")
	var version := _version()
	if not version.ok:
		return version
	if int(version.data.version) != Schema.VERSION:
		return _failure("CACHE_VERSION_UNSUPPORTED")
	return _validate_scope()


func _validate_tables() -> Dictionary:
	for table in Schema.REQUIRED_TABLES:
		if not _access.has_table(table):
			return _failure("CACHE_SCHEMA_INVALID")
	return _success()


func _validate_columns() -> Dictionary:
	for table in Schema.REQUIRED_COLUMNS:
		var present: Array = _access.column_names(table)
		for column in Schema.REQUIRED_COLUMNS[table]:
			if not present.has(column):
				return _failure("CACHE_SCHEMA_INVALID")
	return _success()


func _validate_indexes() -> Dictionary:
	for table in Schema.REQUIRED_INDEXES:
		var indexes: Array = _access.index_names(table)
		for index in Schema.REQUIRED_INDEXES[table]:
			if not indexes.has(index):
				return _failure("CACHE_SCHEMA_INVALID")
	return _success()


## 结构就绪但缺少 scope 行时补建，避免「能查但永远写不进去」。
func _validate_scope() -> Dictionary:
	var repaired := _ensure_state_rows()
	if not repaired.ok:
		return repaired
	var result: Dictionary = _access.query(Schema.READ_SCOPE_KEY)
	if not result.ok:
		return result
	var row: Dictionary = _access.first_row(result)
	if row.is_empty():
		return _failure("CACHE_METADATA_INVALID")
	if str(row.scope_key) != _scope:
		return _failure("STALE_SCOPE")
	var dynamics: Dictionary = _access.query(Schema.READ_DYNAMICS_STATE)
	if not dynamics.ok:
		return dynamics
	var dynamics_row: Dictionary = _access.first_row(dynamics)
	if dynamics_row.is_empty():
		return _failure("CACHE_METADATA_INVALID")
	return _success() if str(dynamics_row.scope_key) == _scope else _failure("STALE_SCOPE")


## CREATE TABLE 成功但单行状态丢失（异常退出、外部误删）时补回，不重建整库。
func _ensure_state_rows() -> Dictionary:
	var chat: Dictionary = _access.query(Schema.READ_SCOPE_KEY)
	if not chat.ok:
		return chat
	if _access.first_row(chat).is_empty():
		var inserted_chat: Dictionary = _access.execute(Schema.INSTALL_CHAT_STATE, [_scope])
		if not inserted_chat.ok:
			return inserted_chat
	var dynamics: Dictionary = _access.query(Schema.READ_DYNAMICS_STATE)
	if not dynamics.ok:
		return dynamics
	if _access.first_row(dynamics).is_empty():
		var inserted_dynamics: Dictionary = _access.execute(Schema.INSTALL_DYNAMICS_STATE, [_scope])
		if not inserted_dynamics.ok:
			return inserted_dynamics
	return _success()


## 重启恢复：sending 一律显式失败且不重发；waiting_history 超过 24 小时过期。
func _recover_delivery() -> Dictionary:
	@warning_ignore("narrowing_conversion")
	var now := int(Time.get_unix_time_from_system() * 1000.0)
	var sending: Dictionary = _access.execute(Schema.RECOVER_SENDING, [now])
	if not sending.ok:
		return sending
	return _access.execute(Schema.RECOVER_EXPIRED_WAITING, [now, now - WAITING_HISTORY_TTL_MS])


func _abort(result: Dictionary) -> Dictionary:
	close()
	return result


static func _big_endian_32(bytes: PackedByteArray, offset: int) -> int:
	if bytes.size() < offset + 4:
		return -1
	return (int(bytes[offset]) << 24) | (int(bytes[offset + 1]) << 16) \
		| (int(bytes[offset + 2]) << 8) | int(bytes[offset + 3])


static func _valid_scope(scope: String) -> bool:
	return scope.length() == 64 and scope.is_valid_hex_number(false)


static func _failure(code: String) -> Dictionary:
	return {"ok": false, "code": code, "data": {}}


static func _success(data: Dictionary = {}) -> Dictionary:
	return {"ok": true, "code": "OK", "data": data}
