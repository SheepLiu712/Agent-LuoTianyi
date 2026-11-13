extends RefCounted
## 日志事件工具：统一网络、界面、账号与文件事务的字段形状。
## 各模块只传业务事实，不重复拼 category/scope/phase 等公共字段。

const Schema = preload("res://src/storage/log_schema.gd")
const HTTP_RESULT_NAMES := {
	HTTPRequest.RESULT_SUCCESS: "RESULT_SUCCESS",
	HTTPRequest.RESULT_CHUNKED_BODY_SIZE_MISMATCH: "RESULT_CHUNKED_BODY_SIZE_MISMATCH",
	HTTPRequest.RESULT_CANT_CONNECT: "RESULT_CANT_CONNECT",
	HTTPRequest.RESULT_CANT_RESOLVE: "RESULT_CANT_RESOLVE",
	HTTPRequest.RESULT_CONNECTION_ERROR: "RESULT_CONNECTION_ERROR",
	HTTPRequest.RESULT_TLS_HANDSHAKE_ERROR: "RESULT_TLS_HANDSHAKE_ERROR",
	HTTPRequest.RESULT_NO_RESPONSE: "RESULT_NO_RESPONSE",
	HTTPRequest.RESULT_BODY_SIZE_LIMIT_EXCEEDED: "RESULT_BODY_SIZE_LIMIT_EXCEEDED",
	HTTPRequest.RESULT_BODY_DECOMPRESS_FAILED: "RESULT_BODY_DECOMPRESS_FAILED",
	HTTPRequest.RESULT_REQUEST_FAILED: "RESULT_REQUEST_FAILED",
	HTTPRequest.RESULT_DOWNLOAD_FILE_CANT_OPEN: "RESULT_DOWNLOAD_FILE_CANT_OPEN",
	HTTPRequest.RESULT_DOWNLOAD_FILE_WRITE_ERROR: "RESULT_DOWNLOAD_FILE_WRITE_ERROR",
	HTTPRequest.RESULT_REDIRECT_LIMIT_REACHED: "RESULT_REDIRECT_LIMIT_REACHED",
	HTTPRequest.RESULT_TIMEOUT: "RESULT_TIMEOUT",
}

static func method_name(method: int) -> String:
	match method:
		HTTPClient.METHOD_GET:
			return "GET"
		HTTPClient.METHOD_POST:
			return "POST"
		HTTPClient.METHOD_PUT:
			return "PUT"
		HTTPClient.METHOD_DELETE:
			return "DELETE"
		_:
			return "OTHER"

static func http(logger: RefCounted, response: Dictionary, status: int, bytes: int, started_usec: int,
		trace_id: String, route: String, method: String = "GET") -> void:
	if logger == null:
		return
	var outcome := _outcome(response)
	var ok: bool = response.get("ok", false)
	var detail := ""
	if not ok and response.get("detail") is String:
		detail = response.detail
	logger.record_as("network", "network_http", {"channel":"http", "action":"request", "method":method, "route":route,
		"status":status, "duration_ms":_duration_ms(started_usec), "bytes":bytes, "outcome":outcome,
		"trace_id":trace_id, "code":"OK" if ok else str(response.get("code", "UNKNOWN")),
		"detail":detail})

static func ui(logger: RefCounted, route: String, action: String = "open", duration_ms: int = 0,
		outcome: String = "success", method: String = "OPEN") -> void:
	if logger == null:
		return
	logger.record_as("system", "ui_access", {"channel":"ui", "action":action, "method":method, "route":route,
		"outcome":outcome, "duration_ms":duration_ms, "code":"OK" if outcome == "success" else "UI_ERROR"})

static func ws(logger: RefCounted, trace_id: String, action: String, method: String, outcome: String,
		duration_ms: int, bytes: int, code: String = "", detail: String = "") -> void:
	if logger == null:
		return
	var resolved := code if not code.is_empty() else ("OK" if outcome == "success" else "UNKNOWN")
	logger.record_as("network", "network_ws", {"channel":"ws", "action":action, "method":method, "route":"/chat_ws",
		"outcome":outcome, "duration_ms":maxi(0, duration_ms), "bytes":maxi(0, bytes),
		"trace_id":trace_id if Schema.is_trace_id(trace_id) else Schema.new_trace_id("ws"),
		"code":resolved, "detail":detail})

static func ws_audio(logger: RefCounted, trace_id: String, frames: int, bytes: int, duration_ms: int) -> void:
	if logger == null:
		return
	logger.record_as("network", "network_ws_audio_summary", {"channel":"ws", "action":"audio_frames",
		"method":"WS", "route":"/chat_ws", "operation":"audio_frames", "outcome":"success",
		"duration_ms":maxi(0, duration_ms), "bytes":bytes, "frames":frames, "count":frames, "code":"OK",
		"trace_id":trace_id if Schema.is_trace_id(trace_id) else Schema.new_trace_id("ws")})

static func security_auth(logger: RefCounted, action: String, outcome: String, reason_code: String,
		server: String, username: String, detail: String = "") -> void:
	if logger == null:
		return
	logger.record_as("business", "account_auth", {"phase":"complete", "action":action, "outcome":outcome,
		"reason_code":reason_code, "code":reason_code, "subject":Schema.hash_subject(server, username),
		"detail":detail})

static func security_token(logger: RefCounted, action: String, subject: String, outcome: String, reason_code: String) -> void:
	if logger == null:
		return
	logger.record_as("storage", "storage_credential", {"scope":"file", "operation":action, "outcome":outcome,
		"duration_ms":0, "code":reason_code, "subject":subject, "phase":"complete"})

static func file_transaction(logger: RefCounted, module: String, operation: String, transaction_id: String,
		success: bool, started_usec: int, code: String, extra: Dictionary = {}) -> void:
	if logger == null:
		return
	var fields := {"module":module, "transaction_id":transaction_id, "scope":"file", "operation":operation,
		"phase":"committed" if success else "rolled_back", "outcome":"success" if success else "failure",
		"duration_ms":_duration_ms(started_usec), "code":code, "detail":""}
	fields.merge(extra, false)
	if extra.get("detail") is String:
		fields.detail = extra.detail
	logger.record_as("storage", "storage_file_write", fields)

## 只接受服务端 JSON 中的字符串错误说明；结构化校验错误可能回显输入，不能整体序列化。
static func http_failure_detail(body: PackedByteArray, status: int = 0) -> String:
	var raw := body.get_string_from_utf8().strip_edges()
	if not raw.is_empty():
		var parsed: Variant = JSON.parse_string(raw)
		if parsed is Dictionary:
			for key in ["detail", "message", "error"]:
				var value: Variant = parsed.get(key)
				if value is String and not value.is_empty():
					return Schema.sanitize_text(value, 512)
		else:
			return Schema.sanitize_text(raw, 128)
	return "HTTP status %d" % status if status > 0 else ""

## HTTPRequest.Result 枚举必须保留，否则连接失败会退化成含糊的 NETWORK_ERROR。
static func http_result_name(result: int) -> String:
	return str(HTTP_RESULT_NAMES.get(result, "RESULT_%d" % result))

static func request_error_detail(error: int) -> String:
	return "%s (%d)" % [error_string(error), error]

static func _outcome(response: Dictionary) -> String:
	if response.get("ok", false):
		return "success"
	return "cancelled" if response.get("code", "") == "CANCELLED" else "failure"

static func _duration_ms(started_usec: int) -> int:
	return int((Time.get_ticks_usec() - started_usec) / 1000)
