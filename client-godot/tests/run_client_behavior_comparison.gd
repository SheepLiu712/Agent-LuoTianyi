extends SceneTree

# Run the same wire behavior sequence as server/scripts/client_behavior_python.py.

const PASSWORD := "bG9jYWwtcGFzc3dvcmQ="
const IMAGE := "bG9jYWwtaW1hZ2U="
const MAX_PACKET := 8 * 1024 * 1024
const HTTP_TIMEOUT := 10.0

var _server := "http://127.0.0.1:60030"
var _username := "behavior-comparison"
var _log_path := "user://client-behavior-godot.jsonl"
var _log: FileAccess
var _peer: WebSocketPeer
var _message_token := ""
var _login_token := ""
var _failed := false


func _init() -> void:
	_parse_args()
	if _log_path.is_absolute_path():
		DirAccess.make_dir_recursive_absolute(_log_path.get_base_dir())
	_log = FileAccess.open(_log_path, FileAccess.WRITE)
	if _log == null:
		push_error("cannot open behavior log: " + _log_path)
		quit(1)
		return
	call_deferred("_run")


func _parse_args() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		args = OS.get_cmdline_args()
	var index := 0
	while index < args.size():
		var arg: String = args[index]
		if arg == "--server" and index + 1 < args.size():
			_server = String(args[index + 1]).trim_suffix("/")
			index += 2
		elif arg == "--username" and index + 1 < args.size():
			_username = String(args[index + 1])
			index += 2
		elif arg == "--log-file" and index + 1 < args.size():
			_log_path = String(args[index + 1])
			index += 2
		else:
			index += 1


func _run() -> void:
	var ok := await _run_http_sequence()
	if ok:
		ok = await _run_websocket_sequence()
	if ok:
		_log_record({"step":"client.finished", "direction":"client", "transport":"runner", "result":"passed"})
		print("Godot behavior test passed: ", _log_path)
		_log.close()
		quit(0)
	else:
		_log_record({"step":"client.error", "direction":"client", "transport":"runner", "error":"behavior sequence failed"})
		_log.close()
		quit(1)


func _run_http_sequence() -> bool:
	if not await _authenticate_http(): return false
	var auth := PackedStringArray(["Authorization: Bearer " + _message_token])
	var encoded_user := _username.uri_encode()
	if not await _read_http_content(auth, encoded_user): return false
	return await _write_http_content(auth, encoded_user)
func _http_call(step: String, method: int, path: String, body: Dictionary = {},
		extra_headers: PackedStringArray = PackedStringArray(), expected_status: int = 200) -> Variant:
	var request := HTTPRequest.new()
	request.timeout = HTTP_TIMEOUT
	request.body_size_limit = MAX_PACKET
	get_root().add_child(request)
	var headers := extra_headers.duplicate()
	headers.append("Content-Type: application/json")
	var request_data := "" if method == HTTPClient.METHOD_GET else JSON.stringify(body)
	_log_record({
		"step": step,
		"direction": "client_to_server",
		"transport": "http",
		"method": _method_name(method),
		"path": path,
		"request_payload": body if method != HTTPClient.METHOD_GET else null,
	})
	var request_error := request.request(_server + path, headers, method, request_data)
	if request_error != OK:
		request.queue_free()
		push_error(step + ": HTTPRequest failed")
		return null
	var result: Array = await request.request_completed
	var status := int(result[1])
	var response_body: PackedByteArray = result[3]
	var text := response_body.get_string_from_utf8()
	var parsed: Variant = JSON.parse_string(text) if not text.is_empty() else null
	var response_payload: Variant = parsed if parsed != null else {"_body": "<binary len=" + str(response_body.size()) + ">"}
	_log_record({
		"step": step + ".response",
		"direction": "server_to_client",
		"transport": "http",
		"method": _method_name(method),
		"path": path,
		"status": status,
		"response_payload": response_payload,
	})
	request.queue_free()
	if status != expected_status:
		push_error(step + ": expected HTTP " + str(expected_status) + ", got " + str(status))
		return null
	return parsed if parsed is Dictionary else {}


func _run_websocket_sequence() -> bool:
	if not await _authenticate_socket(): return false
	if not await _test_text_sequence(): return false
	if not await _test_image_sequence(): return false
	_peer.close()
	_log_record({"step":"ws.closed", "direction":"client", "transport":"websocket", "result":"closed"})
	return true
func _wait_socket_open() -> bool:
	var deadline := Time.get_ticks_msec() + 10000
	while Time.get_ticks_msec() < deadline:
		_peer.poll()
		if _peer.get_ready_state() == WebSocketPeer.STATE_OPEN:
			return true
		if _peer.get_ready_state() == WebSocketPeer.STATE_CLOSED:
			return false
		await process_frame
	return false


func _send_event(step: String, event_type: String, payload: Dictionary) -> String:
	var message_id := "behavior-" + Crypto.new().generate_random_bytes(6).hex_encode()
	var packet := {
		"type": event_type, "payload": payload, "client_msg_id": message_id,
		"ts": int(Time.get_unix_time_from_system() * 1000), "reply_to": null
	}
	_log_record({
		"step": step,
		"direction": "client_to_server",
		"transport": "websocket",
		"event_type": event_type,
		"client_msg_id": message_id,
		"reply_to": null,
		"payload": payload,
	})
	if _peer.send_text(JSON.stringify(packet)) != OK:
		_failed = true
		return ""
	return message_id


func _expect_event(step: String, expected_type: String) -> Dictionary:
	var deadline := Time.get_ticks_msec() + 10000
	while Time.get_ticks_msec() < deadline:
		_peer.poll()
		if _peer.get_available_packet_count() > 0:
			var packet := _peer.get_packet()
			if not _peer.was_string_packet():
				return {"ok": false, "event": {}}
			var parsed: Variant = JSON.parse_string(packet.get_string_from_utf8())
			if not parsed is Dictionary:
				return {"ok": false, "event": {}}
			var event: Dictionary = parsed
			_log_record({
				"step": step,
				"direction": "server_to_client",
				"transport": "websocket",
				"event_type": event.get("type"),
				"client_msg_id": event.get("client_msg_id"),
				"reply_to": event.get("reply_to"),
				"payload": event.get("payload", {}),
			})
			return {"ok": event.get("type") == expected_type, "event": event}
		await process_frame
	return {"ok": false, "event": {}}


func _method_name(method: int) -> String:
	return "GET" if method == HTTPClient.METHOD_GET else "POST"


func _log_record(fields: Dictionary) -> void:
	if _log == null:
		return
	var record := {"ts": int(Time.get_unix_time_from_system() * 1000), "kind": "client_test", "client": "godot"}
	for key in fields:
		record[key] = _redact(fields[key], String(key))
	_log.store_line(JSON.stringify(record))
	_log.flush()


func _redact(value: Variant, key: String = "") -> Variant:
	var normalized := key.to_lower()
	if value is Dictionary:
		var result := {}
		for item_key in value:
			result[item_key] = _redact(value[item_key], String(item_key))
		return result
	if value is Array:
		var result_array := []
		for item in value:
			result_array.append(_redact(item, key))
		return result_array
	if value is String and (normalized in ["password", "new_password", "token", "login_token", "message_token", "authorization", "public_key"]
			or normalized.contains("token") or normalized.ends_with("_base64") or normalized == "audio"):
		var digest: String = value.sha256_text().left(12)
		return "<redacted len=" + str(value.length()) + " sha256=" + digest + ">"
	return value

func _authenticate_http() -> bool:
	var key: Variant = await _http_call("http.public_key", HTTPClient.METHOD_GET, "/auth/public_key")
	if key == null:
		return false
	var registered: Variant = await _http_call("http.register", HTTPClient.METHOD_POST, "/auth/register", {
		"username": _username, "password": PASSWORD, "invite_code": "local"
	})
	if registered == null:
		return false
	var login: Variant = await _http_call("http.login", HTTPClient.METHOD_POST, "/auth/login", {
		"username": _username, "password": PASSWORD, "request_token": false
	})
	if login == null:
		return false
	if not login.get("login_token", "") is String or not login.get("message_token", "") is String:
		return false
	_login_token = login.login_token
	_message_token = login.message_token
	if await _http_call("http.auto_login", HTTPClient.METHOD_POST, "/auth/auto_login", {
		"username": _username, "token": _login_token
	}) == null:
		return false
	if await _http_call("http.reset_account", HTTPClient.METHOD_POST, "/auth/reset_account", {
		"new_username": _username + "-reset", "new_password": PASSWORD, "invite_code": "local"
	}) == null:
		return false
	if await _http_call("http.client_model_types", HTTPClient.METHOD_GET, "/llm/client-model-types") == null:
		return false
	return true

func _read_http_content(auth: PackedStringArray, encoded_user: String) -> bool:
	if await _http_call("http.history", HTTPClient.METHOD_GET,
			"/history?username=" + encoded_user + "&count=50&end_index=-1", {}, auth) == null:
		return false
	if await _http_call("http.dynamics", HTTPClient.METHOD_GET,
			"/dynamics?username=" + encoded_user + "&limit=10", {}, auth) == null:
		return false
	if await _http_call("http.dynamics_unread", HTTPClient.METHOD_GET,
			"/dynamics/unread?username=" + encoded_user, {}, auth) == null:
		return false
	if await _http_call("http.preference_get", HTTPClient.METHOD_POST, "/preference/get", {
		"username": _username, "token": _message_token
	}) == null:
		return false
	if await _http_call("http.preference_overwrite", HTTPClient.METHOD_POST, "/preference/overwrite", {
		"username": _username, "token": _message_token, "preferences": {}
	}) == null:
		return false
	if await _http_call("http.dynamics_read", HTTPClient.METHOD_POST, "/dynamics/read", {
		"username": _username, "token": _message_token
	}) == null:
		return false
	return true

func _write_http_content(auth: PackedStringArray, encoded_user: String) -> bool:
	var created: Variant = await _http_call("http.dynamics_create", HTTPClient.METHOD_POST, "/dynamics", {
		"username": _username, "token": _message_token, "content": "behavior test"
	})
	if created == null:
		return false
	if not created.get("item", {}) is Dictionary:
		return false
	var dynamic_id: String = created.item.get("id", "")
	if dynamic_id.is_empty():
		return false
	if await _http_call("http.comments", HTTPClient.METHOD_GET,
			"/dynamics/" + dynamic_id + "/comments?username=" + encoded_user + "&limit=20", {}, auth) == null:
		return false
	if await _http_call("http.comment_create", HTTPClient.METHOD_POST,
			"/dynamics/" + dynamic_id + "/comments", {
				"username": _username, "token": _message_token, "content": "comment", "parent_comment_id": null
			}) == null:
		return false
	if await _http_call("http.update_image_client_path", HTTPClient.METHOD_POST, "/update_image_client_path", {
		"username": _username, "token": _message_token, "uuid": "behavior-image", "image_client_path": ""
	}) == null:
		return false
	if await _http_call("http.get_image", HTTPClient.METHOD_POST, "/get_image", {
		"username": _username, "token": _message_token, "uuid": "behavior-image"
	}, PackedStringArray(), 404) == null:
		return false
	return true

func _authenticate_socket() -> bool:
	_peer = WebSocketPeer.new()
	_peer.inbound_buffer_size = MAX_PACKET
	_peer.outbound_buffer_size = MAX_PACKET
	if _peer.connect_to_url(_server.replace("https://", "wss://").replace("http://", "ws://") + "/chat_ws") != OK:
		return false
	if not await _wait_socket_open():
		return false
	var ready := await _expect_event("ws.system_ready", "system_ready")
	if not ready.ok:
		return false
	var auth_id := _send_event("ws.user_auth.send", "user_auth", {
		"username": _username, "token": _message_token, "capabilities": ["negative_ack_v1"]
	})
	var auth := await _expect_event("ws.auth_ok.receive", "auth_ok")
	if not auth.ok or auth.event.get("reply_to") != auth_id:
		return false
	var ping_id := _send_event("ws.hb_ping.send", "hb_ping", {"ping_id": 1})
	var pong := await _expect_event("ws.hb_pong.receive", "hb_pong")
	if not pong.ok or pong.event.get("reply_to") != ping_id or pong.event.get("payload", {}).get("ping_id") != 1:
		return false
	return true

func _test_text_sequence() -> bool:
	for item in [["start", 2], ["end", 0]]:
		var typing_id := _send_event("ws.user_typing_" + item[0] + ".send", "user_typing", {"text_length": item[1]})
		var typing_ack := await _expect_event("ws.user_typing_" + item[0] + ".ack", "server_ack")
		if not typing_ack.ok or typing_ack.event.get("reply_to") != typing_id:
			return false
	var text_id := _send_event("ws.user_text.send", "user_text", {"message": "hello", "llm_mode": {"types": []}})
	var text_ack := await _expect_event("ws.user_text.ack", "server_ack")
	if not text_ack.ok or text_ack.event.get("reply_to") != text_id:
		return false
	var text_reply := await _expect_event("ws.user_text.reply", "agent_message")
	if not text_reply.ok or text_reply.event.get("reply_to") != text_id:
		return false
	return true

func _test_image_sequence() -> bool:
	for item in [["select", "user_image_selecting"], ["cancel", "user_image_selecting_cancel"]]:
		var selection_id := _send_event("ws.image_" + item[0] + ".send", item[1], {})
		var selection_ack := await _expect_event("ws.image_" + item[0] + ".ack", "server_ack")
		if not selection_ack.ok or selection_ack.event.get("reply_to") != selection_id:
			return false
	var touch_id := _send_event("ws.user_touch.send", "user_touch", {
		"touchArea": ["头"], "touchCount": 1, "timeSinceLastSentTouch": 0.0
	})
	var touch_ack := await _expect_event("ws.user_touch.ack", "server_ack")
	if not touch_ack.ok or touch_ack.event.get("reply_to") != touch_id:
		return false
	var image_id := _send_event("ws.user_image.send", "user_image", {
		"image_base64": IMAGE, "mime_type": "image/png", "image_client_path": "", "llm_mode": {"types": []}
	})
	var image_ack := await _expect_event("ws.user_image.ack", "server_ack")
	if not image_ack.ok or image_ack.event.get("reply_to") != image_id:
		return false
	var image_reply := await _expect_event("ws.user_image.reply", "agent_message")
	if not image_reply.ok or image_reply.event.get("reply_to") != image_id:
		return false
	return true
