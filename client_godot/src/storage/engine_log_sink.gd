extends Logger
var _logger: RefCounted
func _init(logger: RefCounted) -> void:
	_logger = logger
func _log_error(_function: String, _file: String, _line: int, _code: String, _rationale: String, _editor_notify: bool, error_type: int, _script_backtraces: Array[ScriptBacktrace]) -> void:
	_save.call_deferred(error_type)
func _save(error_type: int) -> void:
	if _logger != null:
		_logger.record("engine_error",{"module":"engine","code":"ENGINE_WARNING" if error_type == 1 else "ENGINE_ERROR","level":"WARN" if error_type == 1 else "ERROR","count":1})
func stop() -> void:
	_logger = null
