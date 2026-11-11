extends Node
signal _done(response: Dictionary)
const Schema = preload("res://src/storage/log_schema.gd")
const Events = preload("res://src/storage/log_events.gd")
const ServerAddress = preload("res://src/domain/server_address.gd")
var _http: HTTPRequest
var _timeout: float
var _limit: int
var _logger: RefCounted
func _init(timeout: float = 15.0, limit: int = 8*1024*1024, logger: RefCounted = null) -> void:
	_timeout = timeout
	_limit = limit
	_logger = logger
func send(url: String, method: int, data: Dictionary = {}, headers: PackedStringArray = []) -> Dictionary:
	var started := Time.get_ticks_usec()
	var trace_id := Schema.new_trace_id("req")
	var route := Schema.route_for(url)
	var method_name := Events.method_name(method)
	if not _allowed_url(url):
		Events.http(_logger, _failure("INSECURE_SERVER"), 0, 0, started, trace_id, route, method_name)
		return _failure("INSECURE_SERVER")
	if _http != null:
		Events.http(_logger, _failure("BUSY"), 0, 0, started, trace_id, route, method_name)
		return _failure("BUSY")
	if not is_inside_tree():
		Events.http(_logger, _failure("CANCELLED"), 0, 0, started, trace_id, route, method_name)
		return _failure("CANCELLED")
	var http := HTTPRequest.new()
	_http = http
	http.timeout = _timeout
	http.max_redirects = 0
	http.body_size_limit = _limit
	add_child(http)
	http.request_completed.connect(func(result,status,_headers,body):
		if _http != http:
			return
		var response: Dictionary
		if result != HTTPRequest.RESULT_SUCCESS:
			response = _failure("TIMEOUT" if result == HTTPRequest.RESULT_TIMEOUT else "NETWORK_ERROR",status)
		elif status < 200 or status >= 300:
			response = _failure("AUTH_REJECTED" if status == 401 else "HTTP_ERROR",status)
		else:
			var parser := JSON.new()
			var valid := parser.parse(body.get_string_from_utf8()) == OK and parser.data is Dictionary
			response = {"ok":true,"code":"OK","status":status,"data":parser.data} if valid else _failure("INVALID_RESPONSE",status)
		Events.http(_logger, response, status, body.size(), started, trace_id, route, method_name)
		response.trace_id = trace_id
		response.duration_ms = int((Time.get_ticks_usec() - started) / 1000)
		response.bytes = body.size()
		_done.emit(response))
	var request_headers := headers.duplicate()
	request_headers.append("Content-Type: application/json")
	var error := http.request(url,request_headers,method,"" if method == HTTPClient.METHOD_GET else JSON.stringify(data))
	var result: Dictionary
	if error != OK:
		result = _failure("NETWORK_ERROR")
		Events.http(_logger, result, 0, 0, started, trace_id, route, method_name)
	else:
		result = await _done
	if _http == http:
		_http = null
	http.queue_free()
	return result
func _allowed_url(url: String) -> bool:
	var scheme_end := url.find("://")
	if scheme_end < 0:
		return false
	var scheme := url.left(scheme_end).to_lower()
	if scheme == "https":
		return true
	if scheme != "http":
		return false
	return ServerAddress.is_loopback(url.left(url.find("/", scheme_end + 3) if url.find("/", scheme_end + 3) >= 0 else url.length()))
func cancel() -> void:
	if _http != null:
		_http.cancel_request()
		_done.emit(_failure("CANCELLED"))
func _exit_tree() -> void:
	cancel()
static func _failure(code: String,status: int = 0) -> Dictionary:
	return {"ok":false,"code":code,"status":status,"data":{}}
