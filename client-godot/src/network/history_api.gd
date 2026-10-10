extends Node
const ServerAddress = preload("res://src/domain/server_address.gd")
signal _completed(response: Dictionary)
var _http: HTTPRequest
var _timeout: float
func _init(timeout: float = 15.0) -> void:
	_timeout = timeout
func fetch_page(session: Dictionary, end_index: int = -1) -> Dictionary:
	if _http != null:
		return _failure("BUSY")
	var server := ServerAddress.normalize(str(session.get("server","")))
	if server.is_empty() or not session.get("username") is String or not session.get("message_token") is String or session.username.is_empty() or session.message_token.is_empty() or end_index < -1:
		return _failure("INVALID_INPUT")
	var http := HTTPRequest.new()
	_http = http
	http.timeout = _timeout
	http.max_redirects = 0
	http.body_size_limit = 8 * 1024 * 1024
	add_child(http)
	http.request_completed.connect(func(result,status,_headers,body):
		if _http != http:
			return
		if result != HTTPRequest.RESULT_SUCCESS:
			_completed.emit(_failure("TIMEOUT" if result == HTTPRequest.RESULT_TIMEOUT else "NETWORK_ERROR",status))
		elif status != 200:
			_completed.emit(_failure("AUTH_REJECTED" if status == 401 else "HTTP_ERROR",status))
		else:
			var parser := JSON.new()
			if parser.parse(body.get_string_from_utf8()) != OK or not parser.data is Dictionary or not parser.data.get("history") is Array or not _valid_index(parser.data.get("start_index")):
				_completed.emit(_failure("INVALID_RESPONSE",status))
			else:
				_completed.emit({"ok":true,"code":"OK","status":status,"data":parser.data}))
	var url := "%s/history?username=%s&count=50&end_index=%s" % [server,session.username.uri_encode(),end_index]
	var error := http.request(url,PackedStringArray(["Authorization: Bearer " + session.message_token]),HTTPClient.METHOD_GET)
	var response: Dictionary = _failure("NETWORK_ERROR") if error != OK else await _completed
	if _http == http:
		_http = null
	http.queue_free()
	return response
func cancel() -> void:
	if _http != null:
		_http.cancel_request()
		_completed.emit(_failure("CANCELLED"))
func _exit_tree() -> void:
	cancel()
static func _failure(code: String, status: int = 0) -> Dictionary:
	return {"ok":false,"code":code,"status":status,"data":{}}
static func _valid_index(value: Variant) -> bool:
	return (value is float or value is int) and is_finite(float(value)) and value >= 0 and value == floor(value)
