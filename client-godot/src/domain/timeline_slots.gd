extends RefCounted
const GAP: int = 1048576
const SAFE_BOUND: int = 1152921504606846976

static func allocate(left: Variant, right: Variant, count: int) -> Dictionary:
	if count < 0 or count > 1000000:
		return _error("INVALID_COUNT")
	if count == 0:
		return {"ok": true, "values": []}
	if left == null and right == null:
		return _sequence(0, GAP, count)
	if left == null:
		return _sequence(int(right) - GAP * (count + 1), GAP, count)
	if right == null:
		return _sequence(int(left), GAP, count)
	return _between(int(left), int(right), count)

static func _between(left: int, right: int, count: int) -> Dictionary:
	if left >= right:
		return _error("ORDER_CONFLICT")
	if left < -SAFE_BOUND or right > SAFE_BOUND:
		return _error("RENUMBER_REQUIRED")
	@warning_ignore("integer_division")
	var step: int = (right - left) / (count + 1)
	if step < 1:
		return _error("RENUMBER_REQUIRED")
	return _sequence(left, step, count)

static func _sequence(base: int, step: int, count: int) -> Dictionary:
	var last := base + step * count
	if base < -SAFE_BOUND or last > SAFE_BOUND:
		return _error("RENUMBER_REQUIRED")
	var values: Array[int] = []
	for index in count:
		values.append(base + step * (index + 1))
	return {"ok": true, "values": values}

static func _error(code: String) -> Dictionary:
	return {"ok": false, "code": code, "values": []}
