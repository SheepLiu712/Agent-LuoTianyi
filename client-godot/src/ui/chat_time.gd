extends RefCounted

const GAP_SECONDS := 300.0

static func markers(messages: Array[Dictionary]) -> Dictionary:
	var result := {}
	var previous := -1.0
	for message in messages:
		if message.get("role") == "system": continue
		var current := seconds(message.get("timestamp"))
		if current < 0: continue
		if previous < 0 or current - previous >= GAP_SECONDS:
			result[message.id] = label(current)
		previous = maxf(previous, current)
	return result

static func seconds(raw: Variant) -> float:
	if raw is int or raw is float: return _numeric_seconds(float(raw))
	if not raw is String: return -1.0
	var text: String = raw.strip_edges()
	if text.is_valid_float(): return _numeric_seconds(text.to_float())
	return _calendar_seconds(text)

static func label(value: float) -> String:
	var formatted := Time.get_datetime_string_from_unix_time(int(value), true)
	var today := Time.get_date_string_from_system()
	if formatted.begins_with(today): return formatted.substr(11, 5)
	return formatted.substr(0, 16)

static func _numeric_seconds(value: float) -> float:
	if not is_finite(value) or value < 0: return -1.0
	if value >= 100000000000.0: value /= 1000.0
	return value + Time.get_time_zone_from_system().bias * 60

static func _calendar_seconds(text: String) -> float:
	var pattern := RegEx.new()
	pattern.compile("^\\d{4}-\\d{2}-\\d{2}[ T]\\d{2}:\\d{2}:\\d{2}(?:\\.(\\d+))?(Z|[+-]\\d{2}:\\d{2})?$")
	var matched := pattern.search(text)
	if matched == null or not _valid_calendar(text): return -1.0
	var normalized := text.left(19).replace(" ", "T")
	var value := float(Time.get_unix_time_from_datetime_string(normalized))
	var fraction := matched.get_string(1)
	if not fraction.is_empty(): value += ("0." + fraction).to_float()
	var zone := matched.get_string(2)
	if zone.is_empty(): return value
	var offset := _zone_minutes(zone)
	if not is_finite(offset): return -1.0
	return value + (Time.get_time_zone_from_system().bias - offset) * 60

static func _zone_minutes(zone: String) -> float:
	if zone == "Z": return 0.0
	var hours := int(zone.substr(1, 2))
	var minutes := int(zone.substr(4, 2))
	if hours > 23 or minutes > 59: return INF
	return (hours * 60 + minutes) * (-1.0 if zone.begins_with("-") else 1.0)

static func _valid_calendar(text: String) -> bool:
	var year := int(text.substr(0, 4))
	var month := int(text.substr(5, 2))
	var day := int(text.substr(8, 2))
	if year < 1970 or month < 1 or month > 12: return false
	var days := [31, _february_days(year), 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
	if day < 1 or day > days[month - 1]: return false
	return int(text.substr(11, 2)) < 24 and int(text.substr(14, 2)) < 60 and int(text.substr(17, 2)) < 60

static func _february_days(year: int) -> int:
	return 29 if year % 400 == 0 or (year % 4 == 0 and year % 100 != 0) else 28
