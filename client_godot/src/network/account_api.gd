extends Node
const ServerAddress = preload("res://src/domain/server_address.gd")
signal _http_finished(response: Dictionary)
const FIELDS := {
	"login":["username", "password"], "register":["username", "password", "invite_code"],
	"reset":["invite_code", "new_username", "new_password"], "auto_login":["username", "token"]}
var _security: Object
var _timeout: float
var _busy := false
var _generation := 0
var _http: HTTPRequest

func _init(security: Object, timeout: float = 15.0) -> void:
	_security = security
	_timeout = maxf(timeout, 0.05)

func request(operation: String, server: String, fields: Dictionary) -> Dictionary:
	if _busy:
		return _failure("BUSY")
	var base := ServerAddress.normalize(server)
	if not FIELDS.has(operation) or base.is_empty() or not is_inside_tree():
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
	_busy = true
	var generation := _generation
	var response: Dictionary = await _perform(operation, base, payload, generation)
	_busy = false
	return response

func probe_server(address: String) -> Dictionary:
	if _busy: return _failure("BUSY")
	var base := ServerAddress.normalize(address)
	if base.is_empty() or not is_inside_tree(): return _failure("INVALID_INPUT")
	_busy = true
	var generation := _generation
	var response := await _exchange(base + "/auth/public_key", HTTPClient.METHOD_GET)
	_busy = false
	if generation != _generation: return _failure("CANCELLED")
	if not response.ok:
		return response if response.code in ["TIMEOUT", "CANCELLED"] else _failure("PUBLIC_KEY_ERROR", response.status)
	if not response.data.get("public_key") is String or response.data.public_key.is_empty():
		return _failure("PUBLIC_KEY_ERROR", response.status)
	return {"ok":true,"code":"OK","status":response.status,"data":{"server":base}}

func _perform(operation: String, base: String, payload: Dictionary, generation: int) -> Dictionary:
	if operation != "auto_login":
		var public_key: Dictionary = await _exchange(base + "/auth/public_key", HTTPClient.METHOD_GET)
		if generation != _generation:
			return _failure("CANCELLED")
		if not public_key.ok:
			return public_key if public_key.code in ["TIMEOUT", "CANCELLED"] else _failure("PUBLIC_KEY_ERROR", public_key.status)
		if not public_key.data.get("public_key") is String or public_key.data.public_key.is_empty():
			return _failure("PUBLIC_KEY_ERROR", public_key.status)
		var password_field := "new_password" if operation == "reset" else "password"
		var encrypted: Dictionary = _security.encrypt_password(public_key.data.public_key, payload[password_field])
		payload[password_field] = ""
		if not encrypted.ok:
			return _failure("ENCRYPTION_ERROR")
		payload[password_field] = Marshalls.raw_to_base64(encrypted.data)
	var endpoint := "reset_account" if operation == "reset" else operation
	var response: Dictionary = await _exchange(base + "/auth/" + endpoint, HTTPClient.METHOD_POST, payload)
	if generation != _generation:
		return _failure("CANCELLED")
	if not response.ok:
		return response
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
	return {"ok":true, "code":"OK", "status":response.status, "data":data}

func _exchange(url: String, method: int, payload: Dictionary = {}) -> Dictionary:
	var http := HTTPRequest.new()
	_http = http
	http.timeout = _timeout
	http.max_redirects = 0
	http.body_size_limit = 65536
	add_child(http)
	http.request_completed.connect(func(result, status, _headers, body):
		if _http != http:
			return
		if result == HTTPRequest.RESULT_TIMEOUT:
			_http_finished.emit(_failure("TIMEOUT"))
		elif result != HTTPRequest.RESULT_SUCCESS:
			_http_finished.emit(_failure("NETWORK_ERROR", status))
		elif status != 200:
			_http_finished.emit(_failure("AUTH_REJECTED" if status == 401 else "HTTP_ERROR", status))
		else:
			var parser := JSON.new()
			var valid := parser.parse(body.get_string_from_utf8()) == OK and parser.data is Dictionary
			_http_finished.emit({"ok":true, "code":"OK", "status":status, "data":parser.data} if valid else _failure("INVALID_RESPONSE", status)))
	var error := http.request(url, PackedStringArray(["Content-Type: application/json"]), method,
		JSON.stringify(payload) if method == HTTPClient.METHOD_POST else "")
	var response: Dictionary
	if error != OK:
		response = _failure("NETWORK_ERROR")
	else:
		response = await _http_finished
	_http = null
	http.queue_free()
	return response

static func _failure(code: String, status: int = 0) -> Dictionary:
	return {"ok":false, "code":code, "status":status, "data":{}}

func cancel() -> void:
	_generation += 1
	if is_instance_valid(_http):
		_http.cancel_request()
		_http_finished.emit(_failure("CANCELLED"))

func _exit_tree() -> void:
	cancel()
