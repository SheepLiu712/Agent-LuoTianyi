extends Logger

const WINDOW_MS := 1000
## Godot 的 TLS 报错会把 mbedTLS 原始负码直接打进 detail；这里补上名称，避免只能靠猜。
const MBEDTLS_ERRORS := {
	-9984: "MBEDTLS_ERR_X509_CERT_VERIFY_FAILED",
	-29312: "MBEDTLS_ERR_SSL_PEER_VERIFY_FAILED",
	-30592: "MBEDTLS_ERR_SSL_FATAL_ALERT_MESSAGE",
	-28928: "MBEDTLS_ERR_SSL_BAD_INPUT_DATA",
	-32512: "MBEDTLS_ERR_SSL_CONN_EOF",
}
const MBEDTLS_CAUSES := {
	-9984: "certificate_verify_failed",
	-29312: "peer_verify_failed",
	-30592: "fatal_alert",
	-28928: "bad_input",
	-32512: "connection_eof",
}

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
	var annotated := tls_detail(rationale if not rationale.is_empty() else code)
	_windows[key] = {"started":now, "suppressed":0, "code":resolved, "detail":annotated.detail,
		"mbedtls_code":annotated.mbedtls_code, "mbedtls_name":annotated.mbedtls_name, "warning":error_type == 1}
	var warning := error_type == 1
	var fields := {
		"module": "engine",
		"code": resolved,
		"detail": annotated.detail,
		"stack": frames,
		"phase": "warning" if warning else "error",
		"count": 1,
		"level": "WARN" if warning else "ERROR",
	}
	var tls_data := _tls_data(annotated)
	if not tls_data.is_empty():
		fields.data = tls_data
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
	}
	var tls_data := _tls_data(window)
	tls_data.window_ms = WINDOW_MS
	fields.data = tls_data
	_logger.record_as("system", "engine_warning_repeated" if warning else "engine_error_repeated", fields)


## 把 “TLS handshake error: -9984” 这类引擎原文补成 “-9984 (MBEDTLS_ERR_...)”。
static func tls_detail(rationale: String) -> Dictionary:
	var marker := "TLS handshake error:"
	var index := rationale.find(marker)
	if index < 0:
		return {"detail":rationale, "mbedtls_code":0, "mbedtls_name":""}
	var rest := rationale.substr(index + marker.length()).strip_edges()
	var digits := ""
	var offset := 0
	while offset < rest.length():
		var code_point := rest.unicode_at(offset)
		var character := rest.substr(offset, 1)
		if character == "-" or (code_point >= 48 and code_point <= 57):
			digits += character
			offset += 1
		else:
			break
	if digits.is_empty() or digits == "-":
		return {"detail":rationale, "mbedtls_code":0, "mbedtls_name":""}
	var mbedtls_code := int(digits)
	var mbedtls_name := str(MBEDTLS_ERRORS.get(mbedtls_code, ""))
	if mbedtls_name.is_empty():
		return {"detail":rationale, "mbedtls_code":mbedtls_code, "mbedtls_name":""}
	return {"detail":"%s (%s)" % [rationale, mbedtls_name], "mbedtls_code":mbedtls_code, "mbedtls_name":mbedtls_name}


static func _tls_data(annotated: Dictionary) -> Dictionary:
	var code := int(annotated.get("mbedtls_code", 0))
	if code == 0:
		return {}
	var data := {"mbedtls_code":code, "mbedtls_name":str(annotated.mbedtls_name), "tls_stage":"handshake"}
	var cause := tls_cause(code)
	if not cause.is_empty():
		data.tls_cause = cause
	return data


static func tls_cause(code: int) -> String:
	return str(MBEDTLS_CAUSES.get(code, ""))

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
