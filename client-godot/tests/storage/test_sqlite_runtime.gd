extends SceneTree
## 探针：确认 SQLite GDExtension 在本工程的实际行为。
##
## 只回答四个问题，不进入生产链：
##   1) 类是否注册（ClassDB.class_exists）
##   2) path 能否直接吃 "user://..."
##   3) query/query_with_bindings/query_result 的返回结构
##   4) 工作线程内能否创建并独占使用连接

var failures: Array[String] = []
var _facts: Dictionary = {}


func _initialize() -> void:
	run.call_deferred()


func run() -> void:
	check(ClassDB.class_exists("SQLite"), "SQLite class is registered")
	var root := "user://probe-sqlite"
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(root))
	var relative_path: String = root.path_join("relative.db")
	var absolute_path: String = ProjectSettings.globalize_path(root.path_join("absolute.db"))
	_probe_relative(relative_path)
	_probe_absolute(absolute_path)
	_probe_bindings(absolute_path)
	_probe_thread(root.path_join("thread.db"))
	_probe_thread_absolute(ProjectSettings.globalize_path(root.path_join("thread_absolute.db")))
	_cleanup(root)
	print("facts: ", JSON.stringify(_facts))
	print("SQLite runtime probe: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func check(ok: bool, label: String) -> void:
	if ok:
		return
	failures.append(label)
	print("FAIL: ", label)


## user:// 直接作为 path 是否可用。
func _probe_relative(path: String) -> void:
	var db: Object = ClassDB.instantiate("SQLite")
	check(db != null, "instantiate in main thread")
	if db == null:
		return
	db.path = path
	db.verbosity_level = 0
	var opened: bool = db.open_db()
	_facts.user_relative_open = opened
	if opened:
		db.query("CREATE TABLE IF NOT EXISTS probe(value TEXT)")
		db.close_db()
	check(opened, "user:// path opens directly")
	DirAccess.remove_absolute(ProjectSettings.globalize_path(path))


## 绝对路径 + PRAGMA 配置。
func _probe_absolute(path: String) -> void:
	var db: Object = ClassDB.instantiate("SQLite")
	if db == null:
		return
	db.path = path
	db.verbosity_level = 0
	db.foreign_keys = true
	check(db.open_db(), "absolute path opens")
	for pragma in ["PRAGMA journal_mode=WAL", "PRAGMA synchronous=FULL", "PRAGMA busy_timeout=3000"]:
		var ok: bool = db.query(pragma)
		if pragma.contains("journal_mode"):
			_facts.wal_rows = db.query_result.duplicate(true)
			check(ok, "journal_mode query returns rows")
	db.close_db()
	DirAccess.remove_absolute(path)


## 绑定参数与返回结构。
func _probe_bindings(path: String) -> void:
	var db: Object = ClassDB.instantiate("SQLite")
	if db == null:
		return
	db.path = path
	db.verbosity_level = 0
	if not db.open_db():
		check(false, "bindings connection opens")
		return
	db.query("CREATE TABLE probe(id TEXT PRIMARY KEY, n INTEGER NOT NULL)")
	check(db.query_with_bindings("INSERT INTO probe(id,n) VALUES(?,?)", ["a", 7]), "insert with bindings")
	check(db.query_with_bindings("SELECT * FROM probe WHERE id=?", ["a"]), "select with bindings")
	var rows: Array = db.query_result
	_facts.row_type = typeof(rows[0]) if not rows.is_empty() else TYPE_NIL
	_facts.row = rows[0] if not rows.is_empty() else {}
	check(rows.size() == 1 and int(rows[0].get("n", -1)) == 7, "binding round trip")
	check(db.query("SELECT count(*) AS n FROM probe"), "aggregate query")
	_facts.aggregate = db.query_result.duplicate(true)
	db.close_db()
	DirAccess.remove_absolute(path)


## 工作线程内创建实例（数据库连接原则上只属于一个线程）。
func _probe_thread(relative_path: String) -> void:
	var state := {"created": false, "opened": false, "count": -1}
	var worker := Thread.new()
	worker.start(func() -> void:
		var db: Object = ClassDB.instantiate("SQLite")
		state.created = db != null
		if db == null:
			return
		db.path = relative_path
		db.verbosity_level = 0
		state.opened = db.open_db()
		if not state.opened:
			return
		db.query("CREATE TABLE IF NOT EXISTS t(a TEXT)")
		if db.query("SELECT count(*) AS n FROM t") and not db.query_result.is_empty():
			state.count = int(db.query_result[0].get("n", -1))
		db.close_db()
	)
	worker.wait_to_finish()
	_facts.thread_relative = state
	check(state.created, "instantiate inside worker thread")
	check(state.opened, "user:// path opens inside worker thread")
	check(state.count == 0, "query inside worker thread")
	DirAccess.remove_absolute(ProjectSettings.globalize_path(relative_path))


func _probe_thread_absolute(path: String) -> void:
	var state := {"opened": false, "wal": ""}
	var worker := Thread.new()
	worker.start(func() -> void:
		var db: Object = ClassDB.instantiate("SQLite")
		if db == null:
			return
		db.path = path
		db.verbosity_level = 0
		db.foreign_keys = true
		state.opened = db.open_db()
		if not state.opened:
			return
		if db.query("PRAGMA journal_mode=WAL") and not db.query_result.is_empty():
			state.wal = str(db.query_result[0].values()[0])
		db.close_db()
	)
	worker.wait_to_finish()
	_facts.thread_absolute = state
	check(state.opened, "absolute path opens inside worker thread")
	check(state.wal.to_lower() == "wal", "WAL is accepted inside worker thread")
	DirAccess.remove_absolute(path)


func _cleanup(root: String) -> void:
	for name in ["relative.db", "absolute.db", "thread.db", "thread_absolute.db"]:
		DirAccess.remove_absolute(ProjectSettings.globalize_path(root.path_join(name)))
		DirAccess.remove_absolute(ProjectSettings.globalize_path(root.path_join(name + "-wal")))
		DirAccess.remove_absolute(ProjectSettings.globalize_path(root.path_join(name + "-shm")))
	DirAccess.remove_absolute(ProjectSettings.globalize_path(root))
