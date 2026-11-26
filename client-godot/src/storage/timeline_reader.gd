extends RefCounted
## 聊天读路径：服务器历史按 server_index 升序，本地尾部按 local_seq 升序。
## 两个资源分开查询再拼接，不做全表排序、不做重编号。

const Schema = preload("res://src/storage/history_schema.gd")

const DEFAULT_LIMIT := 30
const MAX_LIMIT := 100

var _access: RefCounted


func _init(access: RefCounted) -> void:
	_access = access


## 最新窗口：服务端最近一页（升序返回）+ 全部本地尾部。
func latest(limit: int = DEFAULT_LIMIT) -> Dictionary:
	if not _valid(limit):
		return _failure("INVALID_INPUT")
	var server: Dictionary = _access.query(Schema.READ_LATEST_SERVER, [limit])
	if not server.ok:
		return server
	var local: Dictionary = _access.query(Schema.READ_ALL_LOCAL)
	if not local.ok:
		return local
	var rows: Array = _access.rows_of(server)
	rows.reverse()
	rows.append_array(_access.rows_of(local))
	return _page(rows)


## 上翻一页：锚点可能位于服务器历史或本地尾部。
func before(anchor_id: String, limit: int = DEFAULT_LIMIT) -> Dictionary:
	if not _valid(limit) or anchor_id.is_empty():
		return _failure("INVALID_INPUT")
	var local: Dictionary = _access.query(Schema.READ_LOCAL_BY_ID, [anchor_id])
	if not local.ok:
		return local
	var local_row: Dictionary = _access.first_row(local)
	if not local_row.is_empty():
		return _before_local(int(local_row.local_seq), limit)
	var server: Dictionary = _access.query(Schema.READ_SERVER_BY_ID, [anchor_id])
	if not server.ok:
		return server
	var server_row: Dictionary = _access.first_row(server)
	if server_row.is_empty():
		return _failure("ANCHOR_MISSING")
	return _before_server(int(server_row.server_index), limit)


## 本地尾部之前的记录：先取更早的本地行，不足一页再用最新服务器历史补足。
func _before_local(local_seq: int, limit: int) -> Dictionary:
	var older: Dictionary = _access.query(Schema.READ_LOCAL_BEFORE, [local_seq, limit])
	if not older.ok:
		return older
	var rows: Array = _access.rows_of(older)
	rows.reverse()
	var missing := limit - rows.size()
	if missing <= 0:
		return _page(rows)
	var server: Dictionary = _access.query(Schema.READ_SERVER_TAIL, [missing])
	if not server.ok:
		return server
	var server_rows: Array = _access.rows_of(server)
	server_rows.reverse()
	server_rows.append_array(rows)
	return _page(server_rows)


func _before_server(server_index: int, limit: int) -> Dictionary:
	var result: Dictionary = _access.query(Schema.READ_SERVER_BEFORE, [server_index, limit])
	if not result.ok:
		return result
	var rows: Array = _access.rows_of(result)
	rows.reverse()
	return _page(rows)


func _page(rows: Array) -> Dictionary:
	var revision: Dictionary = _access.query(Schema.READ_REVISION)
	if not revision.ok:
		return revision
	return _success({
		"messages": rows,
		"revision": int(_access.first_row(revision).get("revision", 0)),
	})


static func _valid(limit: int) -> bool:
	return limit >= 1 and limit <= MAX_LIMIT


static func _failure(code: String) -> Dictionary:
	return {"ok": false, "code": code, "data": {}}


static func _success(data: Dictionary) -> Dictionary:
	return {"ok": true, "code": "OK", "data": data}
