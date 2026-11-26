extends RefCounted
## 消息时间在本地库里的唯一换算口径：sent_ts_ms 存「本地墙钟时间按 UTC 编码」的毫秒。
##
## 这样同一个数字既能直接格式化成本地日历串，也能和服务器下发的
## 「YYYY-MM-DD HH:MM:SS」无时区字符串做同口径比较（600 秒对账窗口）。
## 与 src/ui/chat_time.gd 的语义保持一致：数字时间戳会补上系统时区偏置。


static func now_ms() -> int:
	@warning_ignore("narrowing_conversion")
	return int(Time.get_unix_time_from_system() * 1000.0)


## 数字按 Unix 秒处理，无时区日历串按本地墙钟处理。
## 无法解析时返回 0，由调用方决定是否拒绝。
static func to_display_ms(raw: Variant) -> int:
	if raw is int or raw is float:
		var seconds := float(raw)
		if not is_finite(seconds) or seconds < 0:
			return 0
		return int((seconds + _bias_seconds()) * 1000.0)
	if not raw is String:
		return 0
	var text := str(raw).strip_edges()
	if text.is_empty():
		return 0
	if text.is_valid_float():
		return to_display_ms(text.to_float())
	if text.length() < 19:
		return 0
	var normalized := text.left(19).replace(" ", "T")
	return int(Time.get_unix_time_from_datetime_string(normalized) * 1000.0)


## 本地库时间 → UI 用的日历串；无时区，格式与服务器历史一致。
static func display_text(ms: int) -> String:
	if ms <= 0:
		return ""
	return Time.get_datetime_string_from_unix_time(int(ms / 1000)).replace("T", " ")


## 当前本地墙钟时间，用于和服务端动态时间戳做字符串比较。
static func local_wall_clock() -> String:
	@warning_ignore("narrowing_conversion")
	var wall: int = int(Time.get_unix_time_from_system() + _bias_seconds())
	return Time.get_datetime_string_from_unix_time(wall).replace("T", " ")


static func local_wall_clock_ms() -> int:
	return int(Time.get_unix_time_from_system() * 1000.0)


static func _bias_seconds() -> float:
	return Time.get_time_zone_from_system().bias * 60.0
