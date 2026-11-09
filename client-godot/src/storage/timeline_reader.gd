extends RefCounted
## 本地游标分页：只按 timeline_order 做 keyset 查询。
## 不使用 OFFSET、不在启动时整库读入。返回结果一律「旧到新」，
## 并附带读取时看到的 order_revision，供上层丢弃过期结果。

const Schema = preload("res://src/storage/history_schema.gd")

const DEFAULT_LIMIT := 30
const MAX_LIMIT := 100

var _access: RefCounted


func _init(access: RefCounted) -> void:
	_access = access


func latest(limit: int = DEFAULT_LIMIT) -> Dictionary:
	return _page(Schema.READ_LATEST, [limit], limit)


func before(anchor_id: String, limit: int = DEFAULT_LIMIT) -> Dictionary:
	if not _valid(limit) or anchor_id.is_empty():
		return _failure("INVALID_INPUT")
	var anchor := _order_of(anchor_id)
	if not anchor.ok:
		return anchor
	return _page(Schema.READ_BEFORE, [anchor.data.order, limit], limit)


func _order_of(anchor_id: String) -> Dictionary:
	var result: Dictionary = _access.query(Schema.READ_ORDER_OF, [anchor_id])
	if not result.ok:
		return result
	var row: Dictionary = _access.first_row(result)
	if row.is_empty():
		return _failure("ANCHOR_MISSING")
	return _success({"order": int(row.timeline_order)})


func _page(sql: String, bindings: Array, limit: int) -> Dictionary:
	if not _valid(limit):
		return _failure("INVALID_INPUT")
	var result: Dictionary = _access.query(sql, bindings)
	if not result.ok:
		return result
	var revision := _revision()
	if not revision.ok:
		return revision
	var rows: Array = _access.rows_of(result)
	rows.reverse()
	return _success({"messages": rows, "order_revision": int(revision.data.order_revision)})


func _revision() -> Dictionary:
	var result: Dictionary = _access.query(Schema.READ_ORDER_REVISION)
	if not result.ok:
		return result
	var row: Dictionary = _access.first_row(result)
	if row.is_empty():
		return _failure("CACHE_METADATA_INVALID")
	return _success({"order_revision": int(row.order_revision)})


static func _valid(limit: int) -> bool:
	return limit >= 1 and limit <= MAX_LIMIT


static func _failure(code: String) -> Dictionary:
	return {"ok": false, "code": code, "data": {}}


static func _success(data: Dictionary) -> Dictionary:
	return {"ok": true, "code": "OK", "data": data}
