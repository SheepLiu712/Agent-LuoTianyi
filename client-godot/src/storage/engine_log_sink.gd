extends Logger

var _logger: RefCounted

func _init(logger: RefCounted) -> void:
	_logger = logger

func _log_error(function: String, file: String, line: int, code: String, rationale: String,
		_editor_notify: bool, error_type: int, script_backtraces: Array[ScriptBacktrace]) -> void:
	_save.call_deferred(function, file, line, code, rationale, error_type, _stack_frames(function, file, line, script_backtraces))

func _save(function: String, file: String, line: int, code: String, rationale: String, error_type: int, frames: Array) -> void:
	if _logger == null:
		return
	var warning := error_type == 1
	var event := "warning_engine" if warning else "error_engine"
	var fields := {
		"module": "engine",
		"code": _engine_code(error_type, code),
		"detail": rationale if not rationale.is_empty() else code,
		"stack": frames,
		"phase": "warning" if warning else "error",
		"count": 1,
	}
	if warning:
		_logger.log_warning(event, fields)
	else:
		_logger.log_error(event, fields)

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
