extends Node
const ServerAddress = preload("res://src/domain/server_address.gd")
signal state_changed(state: Dictionary)
signal delivery_changed(id: String, state: String, code: String)
signal event_received(event: Dictionary)
signal system_error(code: String)
const Outbox = preload("res://src/network/reliable_outbox.gd")
const MAX_PACKET := 8 * 1024 * 1024
var _clock: Callable
var _outbox = Outbox.new()
var _peer: WebSocketPeer
var _session: Dictionary = {}
var _state := {"phase":"idle", "code":""}
var _fingerprint := ""
var _rejected := ""
var _deadline := 0
var _next_connect := 0
var _reconnect_attempt := 0
var _next_heartbeat := 0
var _ping_id := 0

func _init(clock: Callable = Callable()) -> void:
	_clock = clock if clock.is_valid() else Time.get_ticks_msec
	_outbox.delivery_changed.connect(func(id, state, code): delivery_changed.emit(id, state, code))

func start(session: Dictionary) -> Error:
	for field in ["server", "username", "message_token"]:
		if not session.get(field) is String or session[field].is_empty():
			return ERR_INVALID_PARAMETER
	var base := ServerAddress.normalize(session.server)
	if base.is_empty() or not is_inside_tree():
		return ERR_INVALID_PARAMETER
	var fingerprint := JSON.stringify([base, session.username, session.message_token]).sha256_text()
	stop()
	if fingerprint == _rejected:
		_set_state("auth_rejected", "AUTH_REJECTED")
		return ERR_UNAUTHORIZED
	_session = {"server":base, "username":session.username, "message_token":session.message_token}
	_fingerprint = fingerprint
	_reconnect_attempt = 0
	_connect_socket(_clock.call())
	return OK

func send_event(type: String, payload: Dictionary, durable: bool = false) -> String:
	if _state.phase in ["idle", "auth_rejected"]:
		return ""
	return _outbox.enqueue(type, payload, durable, _clock.call())

func get_state() -> Dictionary:
	return _state.duplicate()

func stop() -> void:
	_close_socket()
	_session.clear()
	_fingerprint = ""
	_set_state("idle", "")
	_outbox.stop()

func _process(_delta: float) -> void:
	var now: int = _clock.call()
	if _state.phase == "reconnecting" and now >= _next_connect:
		_connect_socket(now)
	if _peer != null:
		_peer.poll()
		var ready := _peer.get_ready_state()
		if ready == WebSocketPeer.STATE_OPEN:
			if _state.phase == "connecting":
				_deadline = now + 5000
				_set_state("authenticating", "")
				_send_control("user_auth", {"username":_session.username, "token":_session.message_token,
					"capabilities":["negative_ack_v1"]}, now)
		# A close frame can arrive in the same poll as auth_error or a final reply.
		# Consume those queued packets before deciding to reconnect.
		var processed := 0
		while _peer != null and _peer.get_available_packet_count() > 0 and processed < 64:
			var bytes := _peer.get_packet()
			var parser := JSON.new()
			if not _peer.was_string_packet() or bytes.size() > MAX_PACKET or parser.parse(bytes.get_string_from_utf8()) != OK:
				_protocol_error(now)
				break
			var event: Variant = parser.data
			if not event is Dictionary or not event.get("type") is String or not event.get("payload") is Dictionary:
				_protocol_error(now)
				break
			_handle_event(event, now)
			processed += 1
		if _peer != null and ready in [WebSocketPeer.STATE_CLOSED, WebSocketPeer.STATE_CLOSING]:
			if _state.phase == "authenticating" and _peer.get_close_code() == 1008:
				_reject_auth("AUTH_REJECTED")
			else:
				_disconnect(now, "CONNECTION_LOST")
	if _state.phase in ["connecting", "authenticating"] and now >= _deadline:
		_disconnect(now, "CONNECT_TIMEOUT" if _state.phase == "connecting" else "AUTH_TIMEOUT")
	if _state.phase == "ready" and now >= _next_heartbeat:
		_ping_id += 1
		_next_heartbeat = now + 10000
		_send_control("hb_ping", {"ping_id":_ping_id}, now)
	var packets: Array[Dictionary] = _outbox.take_ready(now, _state.phase == "ready")
	for packet in packets:
		if _peer == null or _peer.send_text(JSON.stringify(packet)) != OK:
			_disconnect(now, "SEND_FAILED")
			break

func _connect_socket(now: int) -> void:
	_peer = WebSocketPeer.new()
	_peer.inbound_buffer_size = MAX_PACKET
	_peer.outbound_buffer_size = MAX_PACKET
	_peer.max_queued_packets = 64
	var base: String = _session.server
	var url := ("wss://" + base.substr(8) if base.begins_with("https://") else "ws://" + base.substr(7)) + "/chat_ws"
	_deadline = now + 8000
	_ping_id = 0
	_set_state("connecting", "")
	if _peer.connect_to_url(url) != OK:
		_disconnect(now, "CONNECTION_FAILED")

func _handle_event(event: Dictionary, now: int) -> void:
	if event.type == "auth_error" or (event.type == "error" and _state.phase == "authenticating"):
		_reject_auth(_error_code(event.payload, "AUTH_REJECTED"))
		return
	if event.type == "auth_ok" and _state.phase == "authenticating":
		_reconnect_attempt = 0
		_next_heartbeat = now
		_set_state("ready", "")
		return
	if event.type in ["system_ready", "hb_pong", "auth_ok"]:
		return
	if event.type == "system_not_ready":
		_disconnect(now, "SYSTEM_RUNTIME_NOT_READY")
		return
	if _state.phase != "ready":
		return
	if event.type == "server_ack":
		if event.get("reply_to") is String:
			_outbox.acknowledge(event.reply_to, event.payload, now)
	elif event.type == "error":
		system_error.emit(_error_code(event.payload, "SERVER_ERROR"))
	else:
		event_received.emit(event.duplicate(true))

func _send_control(type: String, payload: Dictionary, now: int) -> void:
	var packet := {"type":type, "payload":payload, "client_msg_id":"c-" + Crypto.new().generate_random_bytes(16).hex_encode(),
		"ts":int(Time.get_unix_time_from_system() * 1000), "reply_to":null}
	if _peer == null or _peer.send_text(JSON.stringify(packet)) != OK:
		_disconnect(now, "SEND_FAILED")

func _disconnect(now: int, code: String) -> void:
	_close_socket()
	_outbox.disconnected(now)
	_next_connect = now + mini(2000 * (1 << mini(_reconnect_attempt, 4)), 30000)
	_reconnect_attempt += 1
	_set_state("reconnecting", code)

func _close_socket() -> void:
	if _peer != null:
		_peer.close()
		_peer = null

func _protocol_error(now: int) -> void:
	system_error.emit("INVALID_RESPONSE")
	_disconnect(now, "INVALID_RESPONSE")

func _set_state(phase: String, code: String) -> void:
	_state = {"phase":phase, "code":code}
	state_changed.emit(get_state())

func _reject_auth(code: String) -> void:
	_rejected = _fingerprint
	_close_socket()
	_session.clear()
	_fingerprint = ""
	_set_state("auth_rejected", code)
	_outbox.stop("AUTH_REJECTED")
	system_error.emit(code)

static func _error_code(payload: Dictionary, fallback: String) -> String:
	return payload.code if payload.get("code") is String and not payload.code.is_empty() else fallback

func _exit_tree() -> void:
	stop()
