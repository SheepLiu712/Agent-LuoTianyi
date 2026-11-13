extends Logger

const WINDOW_MS := 1000

var _logger: RefCounted
var _windows := {}

func _init(logger: RefCounted) -> void:
	_logger = logger

func _log_error(function: String, file: String, line: int, code: String, rationale: String,
		_editor_notify: bool, error_type: int, script_backtraces: Array[ScriptBacktrace]) -> void:
	_save.call_deferred(function, file, line, code, rationale, error_type, _stack_frames(function, file, line, script_backtraces))

func _save(function: String, file: String, line: int, code: String, rationale: String, error_type: int, frames: Array) -> void:
	if _logger == null:
		return
	var now := Time.get_ticks_msec()
	_flush_expired(now)
	var resolved := _engine_code(error_type, code)
	var key := "%s:%d:%s:%d" % [file, line, resolved, error_type]
	var window: Dictionary = _windows.get(key, {})
	if not window.is_empty() and now - int(window.started) < WINDOW_MS:
		window.suppressed = int(window.suppressed) + 1
		return
	if not window.is_empty():
		_emit_summary(key, window)
	_windows[key] = {"started":now, "suppressed":0, "code":resolved, "detail":rationale, "warning":error_type == 1}
	var warning := error_type == 1
	var fields := {
		"module": "engine",
		"code": resolved,
		"detail": rationale if not rationale.is_empty() else code,
		"stack": frames,
		"phase": "warning" if warning else "error",
		"count": 1,
		"level": "WARN" if warning else "ERROR",
	}
	_logger.record_as("system", "engine_warning" if warning else "engine_error", fields)

## 由主线程每帧调用；没有窗口时立即返回，不产生额外开销。
func flush(now_ms: int = -1) -> void:
	if _windows.is_empty():
		return
	_flush_expired(Time.get_ticks_msec() if now_ms < 0 else now_ms)

func _flush_expired(now: int) -> void:
	for key in _windows.keys():
		var window: Dictionary = _windows[key]
		if now - int(window.started) < WINDOW_MS:
			continue
		_emit_summary(str(key), window)
		_windows.erase(key)

func _emit_summary(key: String, window: Dictionary) -> void:
	if _logger == null or int(window.get("suppressed", 0)) <= 0:
		return
	var warning := bool(window.get("warning", false))
	var count := int(window.suppressed)
	var detail := str(window.get("detail", ""))
	var fields := {
		"module":"engine",
		"code":str(window.get("code", "ENGINE_ERROR")),
		"detail":"1 秒内重复 %d 次；首条：%s" % [count, detail],
		"phase":"warning" if warning else "error",
		"count":count,
		"level":"WARN" if warning else "ERROR",
		"data":{"window_ms":WINDOW_MS},
	}
	_logger.record_as("system", "engine_warning_repeated" if warning else "engine_error_repeated", fields)

func _engine_code(error_type: int, code: String) -> String:
	match error_type:
		1:
			return "ENGINE_WARNING"
		2:
			return "ENGINE_SCRIPT"
		3:
			return "ENGINE_SHADER"
		_:
			return "ENGINE_ERROR" if code.is_empty() else code

func _stack_frames(function: String, file: String, line: int, script_backtraces: Array[ScriptBacktrace]) -> Array:
	var frames: Array = []
	if not function.is_empty() or not file.is_empty():
		frames.append({"function":function, "source":file, "line":line})
	for trace in script_backtraces:
		if trace == null or not trace.has_method("get_frame_count"):
			continue
		var count: int = trace.get_frame_count()
		for index in count:
			frames.append({"function":trace.get_frame_function(index), "source":trace.get_frame_file(index), "line":trace.get_frame_line(index)})
	return frames

func stop() -> void:
	_logger = null
	_windows.clear()
