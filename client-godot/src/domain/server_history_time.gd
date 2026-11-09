extends RefCounted

static func key(raw: Variant) -> String:
	if not raw is String or raw.length() != 19:
		return ""
	var pattern := RegEx.new()
	pattern.compile("^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$")
	if pattern.search(raw) == null:
		return ""
	if not _valid_date(int(raw.substr(0,4)),int(raw.substr(5,2)),int(raw.substr(8,2))):
		return ""
	return raw if _valid_clock(raw) else ""

static func _valid_date(year: int, month: int, day: int) -> bool:
	if year < 1970 or month < 1 or month > 12:
		return false
	var days := [31,_february_days(year),31,30,31,30,31,31,30,31,30,31]
	return day >= 1 and day <= days[month-1]

static func _february_days(year: int) -> int:
	return 29 if year % 400 == 0 or (year % 4 == 0 and year % 100 != 0) else 28

static func _valid_clock(value: String) -> bool:
	var parts := [int(value.substr(11,2)),int(value.substr(14,2)),int(value.substr(17,2))]
	var maximum := [23,59,59]
	for i in 3:
		if parts[i] > maximum[i]:
			return false
	return true

static func minimum(rows: Array) -> String:
	var result := ""
	for row in rows:
		if not row is Dictionary:
			return ""
		var value := key(row.get("timestamp"))
		if value.is_empty():
			return ""
		if result.is_empty() or value < result:
			result = value
	return result
