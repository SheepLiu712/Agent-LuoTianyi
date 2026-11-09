extends SceneTree
## 草稿库迁移：v1 结构必须被重建为 v3 且消息不丢，未知版本必须拒绝写入。
##
## 迁移的可观察契约：旧消息还在、主键沿用服务端 UUID、有备份文件、
## user_version 变成 3、旧表不再残留；未知版本时库文件保持原样。

const Database = preload("res://src/storage/sqlite_history_database.gd")

const LEGACY_V1 := """
CREATE TABLE messages (
	uuid TEXT PRIMARY KEY NOT NULL,
	source TEXT NOT NULL,
	message_type TEXT NOT NULL,
	content TEXT NOT NULL DEFAULT '',
	timestamp_json TEXT NOT NULL,
	server_time_key INTEGER NOT NULL,
	updated_revision INTEGER NOT NULL
)
"""

var failures: Array[String] = []
var _root := ""


func _initialize() -> void:
	run.call_deferred()


func run() -> void:
	_root = "user://test-sqlite-migration-%d" % Time.get_ticks_usec()
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(_root))
	_case_legacy_v1()
	_case_unknown_version()
	_cleanup()
	print("SQLite migration: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func check(ok: bool, label: String) -> void:
	if ok:
		return
	failures.append(label)
	print("FAIL: ", label)


func _case_legacy_v1() -> void:
	var scope := _scope("a1")
	var path := _create_legacy(scope, 1, [["legacy-1", "user", "text", "kept", "1700000000", 1700000000, 1]])
	check(not path.is_empty(), "legacy v1 database is created")
	var database := Database.new()
	var opened: Dictionary = database.open(_root, scope)
	check(opened.ok, "legacy v1 opens and migrates (%s)" % opened.code)
	if not opened.ok:
		return
	var rows := _latest(database)
	check(rows.size() == 1, "migrated database keeps the legacy row")
	if not rows.is_empty():
		check(str(rows[0].message_id) == "legacy-1", "server uuid is reused as message id")
		check(str(rows[0].content) == "kept", "content survives migration")
		check(str(rows[0].id_source) == "server", "migrated rows are marked as server source")
	check(int(_version(database)) == 3, "user_version becomes 3")
	check(not database._access.has_table("legacy_messages"), "legacy table is dropped")
	check(FileAccess.file_exists(path + ".v1.bak"), "legacy file is backed up before migrating")
	database.close()


func _case_unknown_version() -> void:
	var scope := _scope("b2")
	var path := _create_legacy(scope, 9, [["blocked", "user", "text", "intact", "1700000000", 1700000000, 1]])
	check(not path.is_empty(), "future version database is created")
	var database := Database.new()
	var opened: Dictionary = database.open(_root, scope)
	check(opened.code == "CACHE_VERSION_UNSUPPORTED", "unknown version is refused (%s)" % opened.code)
	var rows := _read_raw(path)
	check(rows.size() == 1 and str(rows[0].uuid) == "blocked", "refused database keeps its rows")
	check(rows.size() == 1 and str(rows[0].content) == "intact", "refused database keeps its content")
	database.close()


# ---------------------------------------------------------------- 辅助

func _scope(seed: String) -> String:
	return (seed + "0".repeat(64)).substr(0, 64)


func _create_legacy(scope: String, version: int, rows: Array) -> String:
	var directory := ProjectSettings.globalize_path(_root).path_join(scope)
	DirAccess.make_dir_recursive_absolute(directory)
	var path := directory.path_join("history.db")
	var db: Object = ClassDB.instantiate("SQLite")
	db.path = path
	db.verbosity_level = 0
	if not db.open_db():
		return ""
	db.query(LEGACY_V1)
	for row in rows:
		db.query_with_bindings(
			"INSERT INTO messages(uuid,source,message_type,content,timestamp_json,server_time_key,updated_revision) VALUES(?,?,?,?,?,?,?)",
			row
		)
	db.query("PRAGMA user_version=%d" % version)
	db.close_db()
	return path


func _read_raw(path: String) -> Array:
	var db: Object = ClassDB.instantiate("SQLite")
	db.path = path
	db.verbosity_level = 0
	if not db.open_db():
		return []
	db.query("SELECT * FROM messages")
	var rows: Array = db.query_result.duplicate(true)
	db.close_db()
	return rows


func _version(database: RefCounted) -> int:
	var row: Dictionary = database._access.first_row(database._access.query("PRAGMA user_version"))
	return int(row.get("user_version", 0))


func _latest(database: RefCounted) -> Array:
	var result: Dictionary = database.execute("read_latest", {"scope": database._scope, "limit": 30})
	return result.get("data", {}).get("messages", [])


func _cleanup() -> void:
	var directory := DirAccess.open(_root)
	if directory == null:
		return
	for name in directory.get_directories():
		_remove_tree(_root.path_join(name))
	DirAccess.remove_absolute(ProjectSettings.globalize_path(_root))


func _remove_tree(path: String) -> void:
	var directory := DirAccess.open(path)
	if directory == null:
		return
	for name in directory.get_files():
		DirAccess.remove_absolute(ProjectSettings.globalize_path(path.path_join(name)))
	for name in directory.get_directories():
		_remove_tree(path.path_join(name))
	DirAccess.remove_absolute(ProjectSettings.globalize_path(path))
