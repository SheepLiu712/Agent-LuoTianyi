extends Node
const ServerAddress = preload("res://src/domain/server_address.gd")
const Schema = preload("res://src/storage/log_schema.gd")
const Events = preload("res://src/storage/log_events.gd")
signal _http_finished(response: Dictionary)
const FIELDS := {
	"login":["username", "password"], "register":["username", "password", "invite_code"],
	"reset":["invite_code", "new_username", "new_password"], "auto_login":["username", "token"]}
var _security: Object
var _timeout: float
var _busy := false
var _generation := 0
var _http: HTTPRequest
var _logger: RefCounted

func _init(security: Object, timeout: float = 15.0, logger: RefCounted = null) -> void:
	_security = security
	_timeout = maxf(timeout, 0.05)
	_logger = logger

func request(operation: String, server: String, fields: Dictionary) -> Dictionary:
	if _busy:
		return _failure("BUSY")
	var base := ServerAddress.normalize(server)
	if base.is_empty() or not is_inside_tree():
		return _failure("INVALID_INPUT")
	if not ServerAddress.allows_insecure(base):
		return _failure("INSECURE_SERVER")
	var prepared := _payload_for(operation, fields)
	if not prepared.ok:
		return prepared
	_busy = true
	var generation := _generation
	var response: Dictionary = await _perform(operation, base, prepared.data, generation)
	_busy = false
	return response


func _payload_for(operation: String, fields: Dictionary) -> Dictionary:
	if not FIELDS.has(operation):
		return _failure("INVALID_INPUT")
	var payload := {}
	for field in FIELDS[operation]:
		if not fields.get(field) is String or fields[field].is_empty():
			return _failure("INVALID_INPUT")
		payload[field] = fields[field]
	if operation == "login":
		if not fields.get("request_token", false) is bool:
			return _failure("INVALID_INPUT")
		payload.request_token = fields.get("request_token", false)
	return {"ok": true, "code": "OK", "status": 0, "data": payload}

func probe_server(address: String) -> Dictionary:
	if _busy: return _failure("BUSY")
	var base := ServerAddress.normalize(address)
	if base.is_empty() or not is_inside_tree(): return _failure("INVALID_INPUT")
	if not ServerAddress.allows_insecure(base): return _failure("INSECURE_SERVER")
	_busy = true
	var generation := _generation
	var response := await _exchange(base + "/auth/public_key", HTTPClient.METHOD_GET)
	_busy = false
	if generation != _generation: return _failure("CANCELLED")
	if not response.ok:
		return response if response.code in ["TIMEOUT", "CANCELLED"] else _failure("PUBLIC_KEY_ERROR", response.status, str(response.get("detail", "")))
	if not response.data.get("public_key") is String or response.data.public_key.is_empty():
		return _failure("PUBLIC_KEY_ERROR", response.status, "public_key missing from response")
	return {"ok":true,"code":"OK","status":response.status,"data":{"server":base}}

func _perform(operation: String, base: String, payload: Dictionary, generation: int) -> Dictionary:
	if operation != "auto_login":
		var prepared := await _encrypt_payload(operation, base, payload, generation)
		if not prepared.ok:
			return prepared
	var endpoint := "reset_account" if operation == "reset" else operation
	var response: Dictionary = await _exchange(base + "/auth/" + endpoint, HTTPClient.METHOD_POST, payload)
	if generation != _generation:
		return _failure("CANCELLED")
	if not response.ok:
		return response
	return _validated_response(operation, response)
func _exchange(url: String, method: int, payload: Dictionary = {}) -> Dictionary:
	var started := Time.get_ticks_usec()
	var trace_id := Schema.new_trace_id("req")
	var route := Schema.route_for(url)
	var method_name := Events.method_name(method)
	var http := HTTPRequest.new()
	_http = http
	http.timeout = _timeout
	http.max_redirects = 0
	http.body_size_limit = 65536
	add_child(http)
	http.request_completed.connect(func(result, status, _headers, body):
		if _http != http:
			return
		var response: Dictionary
		if result == HTTPRequest.RESULT_TIMEOUT:
			response = _failure("TIMEOUT", status, Events.http_result_name(result))
		elif result != HTTPRequest.RESULT_SUCCESS:
			response = _failure("NETWORK_ERROR", status, Events.http_result_name(result))
		elif status != 200:
			response = _failure("AUTH_REJECTED" if status == 401 else "HTTP_ERROR", status,
				Events.http_failure_detail(body, status))
		else:
			var parser := JSON.new()
			var valid := parser.parse(body.get_string_from_utf8()) == OK and parser.data is Dictionary
			response = {"ok":true, "code":"OK", "status":status, "data":parser.data} if valid else _failure("INVALID_RESPONSE", status)
		Events.http(_logger, response, status, body.size(), started, trace_id, route, method_name)
		response.trace_id = trace_id
		response.duration_ms = int((Time.get_ticks_usec() - started) / 1000)
		response.bytes = body.size()
		_http_finished.emit(response))
	var error := http.request(url, PackedStringArray(["Content-Type: application/json"]), method,
		JSON.stringify(payload) if method == HTTPClient.METHOD_POST else "")
	var response: Dictionary
	if error != OK:
		response = _failure("NETWORK_ERROR", 0, Events.request_error_detail(error))
		Events.http(_logger, response, 0, 0, started, trace_id, route, method_name)
	else:
		response = await _http_finished
	response.trace_id = trace_id
	response.duration_ms = int((Time.get_ticks_usec() - started) / 1000)
	_http = null
	http.queue_free()
	return response

static func _failure(code: String, status: int = 0, detail: String = "") -> Dictionary:
	return {"ok":false, "code":code, "status":status, "detail":detail, "data":{}}

func cancel() -> void:
	_generation += 1
	if is_instance_valid(_http):
		_http.cancel_request()
		_http_finished.emit(_failure("CANCELLED"))

func _exit_tree() -> void:
	cancel()

func _encrypt_payload(operation: String, base: String, payload: Dictionary, generation: int) -> Dictionary:
	var public_key: Dictionary = await _exchange(base + "/auth/public_key", HTTPClient.METHOD_GET)
	if generation != _generation:
		return _failure("CANCELLED")
	if not public_key.ok:
		return public_key if public_key.code in ["TIMEOUT", "CANCELLED"] else _failure("PUBLIC_KEY_ERROR", public_key.status, str(public_key.get("detail", "")))
	if not public_key.data.get("public_key") is String or public_key.data.public_key.is_empty():
		return _failure("PUBLIC_KEY_ERROR", public_key.status, "public_key missing from response")
	var password_field := "new_password" if operation == "reset" else "password"
	var encrypted: Dictionary = _security.encrypt_password(public_key.data.public_key, payload[password_field])
	payload[password_field] = ""
	if not encrypted.ok:
		return _failure("ENCRYPTION_ERROR", 0, str(encrypted.get("detail", "password encryption failed")))
	payload[password_field] = Marshalls.raw_to_base64(encrypted.data)
	return {"ok":true}

func _validated_response(operation: String, response: Dictionary) -> Dictionary:
	var required := ["user_id", "login_token", "message_token"]
	if operation == "register":
		required = ["message", "user_id"]
	elif operation == "reset":
		required = ["message", "username"]
	var data := {}
	for field in required:
		if not response.data.get(field) is String or response.data[field].is_empty():
			return _failure("INVALID_RESPONSE", response.status)
		data[field] = response.data[field]
	return {"ok":true, "code":"OK", "status":response.status, "data":data,
		"trace_id":response.get("trace_id", ""), "duration_ms":response.get("duration_ms", 0)}
