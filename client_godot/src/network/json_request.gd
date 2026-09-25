extends Node
signal _done(response: Dictionary)
var _http: HTTPRequest
var _timeout: float
var _limit: int
func _init(timeout: float = 15.0, limit: int = 8*1024*1024) -> void:
	_timeout = timeout
	_limit = limit
func send(url: String, method: int, data: Dictionary = {}, headers: PackedStringArray = []) -> Dictionary:
	if _http != null:
		return _failure("BUSY")
	if not is_inside_tree():
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
		if result != HTTPRequest.RESULT_SUCCESS:
			_done.emit(_failure("TIMEOUT" if result == HTTPRequest.RESULT_TIMEOUT else "NETWORK_ERROR",status))
		elif status < 200 or status >= 300:
			_done.emit(_failure("AUTH_REJECTED" if status == 401 else "HTTP_ERROR",status))
		else:
			var parser := JSON.new()
			var valid := parser.parse(body.get_string_from_utf8()) == OK and parser.data is Dictionary
			_done.emit({"ok":true,"code":"OK","status":status,"data":parser.data} if valid else _failure("INVALID_RESPONSE",status)))
	var request_headers := headers.duplicate()
	request_headers.append("Content-Type: application/json")
	var error := http.request(url,request_headers,method,"" if method == HTTPClient.METHOD_GET else JSON.stringify(data))
	var result: Dictionary = _failure("NETWORK_ERROR") if error != OK else await _done
	if _http == http:
		_http = null
	http.queue_free()
	return result
func cancel() -> void:
	if _http != null:
		_http.cancel_request()
		_done.emit(_failure("CANCELLED"))
func _exit_tree() -> void:
	cancel()
static func _failure(code: String,status: int = 0) -> Dictionary:
	return {"ok":false,"code":code,"status":status,"data":{}}
