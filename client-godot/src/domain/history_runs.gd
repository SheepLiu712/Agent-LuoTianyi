extends RefCounted

static func split(rows: Array, known: Dictionary) -> Dictionary:
	var runs: Array[Dictionary] = []
	var pending: Array = []
	var left := ""
	var previous_order: Variant = null
	for row in rows:
		var uuid: String = row.uuid
		if not known.has(uuid):
			pending.append(row)
			continue
		var order: int = known[uuid].timeline_order
		if previous_order != null and order <= int(previous_order):
			return {"ok": false, "code": "ORDER_CONFLICT", "runs": []}
		_push(runs, pending, left, uuid)
		pending = []
		left = uuid
		previous_order = order
	_push(runs, pending, left, "")
	return {"ok": true, "code": "OK", "runs": runs}

static func _push(runs: Array[Dictionary], rows: Array, left: String, right: String) -> void:
	if rows.is_empty():
		return
	runs.append({"rows": rows.duplicate(true), "left": left, "right": right})
