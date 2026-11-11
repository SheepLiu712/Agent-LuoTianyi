extends RefCounted
## 日志事件工具：统一 HTTP/WS/UI 访问、安全与文件事务的字段形状。
## 各模块只传业务事实，不重复拼 category/scope/phase 等公共字段。

const Schema = preload("res://src/storage/log_schema.gd")

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
	logger.log_access("access_http", {"channel":"http", "action":"request", "method":method, "route":route,
		"status":status, "duration_ms":_duration_ms(started_usec), "bytes":bytes,
		"outcome":outcome, "trace_id":trace_id, "detail":"" if response.get("ok", false) else str(response.get("code", ""))})

static func ui(logger: RefCounted, route: String, action: String = "open", duration_ms: int = 0,
		outcome: String = "success", method: String = "OPEN") -> void:
	if logger == null:
		return
	logger.log_access("access_ui", {"channel":"ui", "action":action, "method":method, "route":route,
		"outcome":outcome, "duration_ms":duration_ms})

static func ws(logger: RefCounted, trace_id: String, action: String, method: String, outcome: String,
		duration_ms: int, bytes: int, detail: String = "") -> void:
	if logger == null:
		return
	logger.log_access("access_ws", {"channel":"ws", "action":action, "method":method, "route":"/chat_ws",
		"outcome":outcome, "duration_ms":maxi(0, duration_ms), "bytes":maxi(0, bytes),
		"trace_id":trace_id if Schema.is_trace_id(trace_id) else Schema.new_trace_id("ws"), "detail":detail})

static func ws_audio(logger: RefCounted, trace_id: String, frames: int, bytes: int, duration_ms: int) -> void:
	if logger == null:
		return
	logger.log_performance("performance_ws_audio", {"operation":"audio_frames", "outcome":"success",
		"duration_ms":maxi(0, duration_ms), "bytes":bytes, "frames":frames, "count":frames,
		"trace_id":trace_id if Schema.is_trace_id(trace_id) else Schema.new_trace_id("ws")})

static func security_auth(logger: RefCounted, action: String, outcome: String, reason_code: String,
		server: String, username: String, trace_id: String = "") -> void:
	if logger == null:
		return
	var fields := {"action":action, "outcome":outcome, "reason_code":reason_code,
		"subject":Schema.hash_subject(server, username)}
	if Schema.is_trace_id(trace_id):
		fields.trace_id = trace_id
	logger.log_security("security_auth", fields)

static func security_token(logger: RefCounted, action: String, subject: String, outcome: String, reason_code: String) -> void:
	if logger == null:
		return
	logger.log_security("security_token", {"action":action, "outcome":outcome, "reason_code":reason_code,
		"subject":subject, "channel":"app"})

static func file_transaction(logger: RefCounted, module: String, operation: String, transaction_id: String,
		success: bool, started_usec: int, code: String, extra: Dictionary = {}) -> void:
	if logger == null:
		return
	var fields := {"module":module, "transaction_id":transaction_id, "scope":"file", "operation":operation,
		"phase":"committed" if success else "rolled_back", "outcome":"success" if success else "failure",
		"duration_ms":_duration_ms(started_usec), "trace_id":transaction_id, "code":code}
	fields.merge(extra, false)
	logger.log_transaction("transaction_file", fields)

static func _outcome(response: Dictionary) -> String:
	if response.get("ok", false):
		return "success"
	return "cancelled" if response.get("code", "") == "CANCELLED" else "failure"

static func _duration_ms(started_usec: int) -> int:
	return int((Time.get_ticks_usec() - started_usec) / 1000)
