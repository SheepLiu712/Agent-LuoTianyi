extends Node
## 历史页 HTTP 客户端：一次只允许一个在途请求。
## 只负责「发请求 / 识别失败类别 / 解析响应」三件事，
## 分页、重试与边界判定都在会话层，避免这里再长出一套状态机。

const ServerAddress = preload("res://src/domain/server_address.gd")
const Schema = preload("res://src/storage/log_schema.gd")
const Events = preload("res://src/storage/log_events.gd")

## 每批 30 条：与分页口径一致，避免「首屏拉 50 条」的隐性放大。
const DEFAULT_COUNT := 30
const MAX_COUNT := 100
const MAX_BODY_BYTES := 8 * 1024 * 1024

signal _completed(response: Dictionary)

var _http: HTTPRequest
var _timeout: float
var _logger: RefCounted
var _started := 0
var _trace_id := ""


func _init(timeout: float = 15.0, logger: RefCounted = null) -> void:
	_timeout = timeout
	_logger = logger


func fetch_page(session: Dictionary, end_index: int = -1, count: int = DEFAULT_COUNT) -> Dictionary:
	var started := Time.get_ticks_usec()
	var trace_id := Schema.new_trace_id("req")
	_started = started
	_trace_id = trace_id
	if not _valid_request(session, end_index, count):
		return _log_and_return(_failure("INVALID_INPUT"), 0, 0, started, trace_id)
	if _http != null:
		return _log_and_return(_failure("BUSY"), 0, 0, started, trace_id)
	var http := _open()
	http.request_completed.connect(_on_completed.bind(http))
	var error := http.request(_url(session, end_index, count), _headers(session), HTTPClient.METHOD_GET)
	if error != OK:
		_release(http)
		return _log_and_return(_failure("NETWORK_ERROR"), 0, 0, started, trace_id)
	var response: Dictionary = await _completed
	_release(http)
	response.trace_id = trace_id
	response.duration_ms = int((Time.get_ticks_usec() - started) / 1000)
	return response


func cancel() -> void:
	if _http == null:
		return
	_http.cancel_request()
	var response := _failure("CANCELLED")
	Events.http(_logger, response, 0, 0, _started, _trace_id, "/history", "GET")
	_completed.emit(response)


func _exit_tree() -> void:
	cancel()


func _open() -> HTTPRequest:
	var http := HTTPRequest.new()
	http.timeout = _timeout
	http.max_redirects = 0
	http.body_size_limit = MAX_BODY_BYTES
	_http = http
	add_child(http)
	return http


func _release(http: HTTPRequest) -> void:
	if _http == http:
		_http = null
	if is_instance_valid(http):
		http.queue_free()


func _on_completed(result: int, status: int, _headers: PackedStringArray, body: PackedByteArray, http: HTTPRequest) -> void:
	# 旧请求的回调必须被身份识别掉，不能覆盖当前请求的结果。
	if _http != http:
		return
	var response := _response(result, status, body)
	response.bytes = body.size()
	Events.http(_logger, response, status, body.size(), _started, _trace_id, "/history", "GET")
	_completed.emit(response)


func _response(result: int, status: int, body: PackedByteArray) -> Dictionary:
	if result != HTTPRequest.RESULT_SUCCESS:
		return _transport_failure(result, status)
	if status != 200:
		return _http_failure(status)
	return _parse(status, body)


func _transport_failure(result: int, status: int) -> Dictionary:
	return _failure("TIMEOUT" if result == HTTPRequest.RESULT_TIMEOUT else "NETWORK_ERROR", status)


func _http_failure(status: int) -> Dictionary:
	if status == 401 or status == 403:
		return _failure("AUTH_REJECTED", status)
	return _failure("HTTP_ERROR", status)


func _parse(status: int, body: PackedByteArray) -> Dictionary:
	var parser := JSON.new()
	if parser.parse(body.get_string_from_utf8()) != OK:
		return _failure("INVALID_RESPONSE", status)
	if not _valid_page(parser.data):
		return _failure("INVALID_RESPONSE", status)
	return {"ok": true, "code": "OK", "status": status, "data": parser.data}


func _valid_page(data: Variant) -> bool:
	return data is Dictionary and data.get("history") is Array and _valid_index(data.get("start_index"))


func _valid_request(session: Dictionary, end_index: int, count: int) -> bool:
	if not _valid_count(count) or end_index < -1:
		return false
	return _valid_credentials(session)


func _valid_count(count: int) -> bool:
	return count >= 1 and count <= MAX_COUNT


func _valid_credentials(session: Dictionary) -> bool:
	return not _text(session, "username").is_empty() \
		and not _text(session, "message_token").is_empty() \
		and not _server(session).is_empty() \
		and ServerAddress.allows_insecure(_server(session))


func _url(session: Dictionary, end_index: int, count: int) -> String:
	return "%s/history?username=%s&count=%s&end_index=%s" % [
		_server(session), _text(session, "username").uri_encode(), count, end_index,
	]


func _headers(session: Dictionary) -> PackedStringArray:
	return PackedStringArray(["Authorization: Bearer " + _text(session, "message_token")])


func _server(session: Dictionary) -> String:
	return ServerAddress.normalize(_text(session, "server"))


func _text(session: Dictionary, key: String) -> String:
	var value: Variant = session.get(key)
	return value if value is String else ""


static func _failure(code: String, status: int = 0) -> Dictionary:
	return {"ok": false, "code": code, "status": status, "data": {}}

func _log_and_return(response: Dictionary, status: int, bytes: int, started: int, trace_id: String) -> Dictionary:
	Events.http(_logger, response, status, bytes, started, trace_id, "/history", "GET")
	response.trace_id = trace_id
	response.duration_ms = int((Time.get_ticks_usec() - started) / 1000)
	return response


static func _valid_index(value: Variant) -> bool:
	return (value is float or value is int) and is_finite(float(value)) and value >= 0 and value == floor(value)
