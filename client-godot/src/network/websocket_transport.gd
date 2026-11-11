extends Node
const ServerAddress = preload("res://src/domain/server_address.gd")
const Schema = preload("res://src/storage/log_schema.gd")
const Events = preload("res://src/storage/log_events.gd")
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
var _ping_sent_at := -1
var _last_rx := 0
var _logger: RefCounted
var _connect_started := 0
var _connect_trace := ""
var _audio_frames := 0
var _audio_bytes := 0
var _audio_started := -1

func _init(clock: Callable = Callable(), logger: RefCounted = null) -> void:
	_clock = clock if clock.is_valid() else Time.get_ticks_msec
	_logger = logger
	_outbox.delivery_changed.connect(func(id, state, code): delivery_changed.emit(id, state, code))

func start(session: Dictionary) -> Error:
	for field in ["server", "username", "message_token"]:
		if not session.get(field) is String or session[field].is_empty():
			return ERR_INVALID_PARAMETER
	var base := ServerAddress.normalize(session.server)
	if base.is_empty() or not is_inside_tree():
		return ERR_INVALID_PARAMETER
	if not ServerAddress.allows_insecure(base):
		if _logger != null:
			_logger.log_security("security_ws_auth", {"action":"connect", "outcome":"denied", "reason_code":"INSECURE_SERVER",
				"subject":Schema.hash_subject(base, str(session.username)), "channel":"ws"})
		return ERR_INVALID_PARAMETER
	var fingerprint := JSON.stringify([base, session.username, session.message_token]).sha256_text()
	stop()
	if fingerprint == _rejected:
		if _logger != null:
			_logger.log_security("security_ws_auth", {"action":"auth", "outcome":"denied", "reason_code":"AUTH_REJECTED",
				"subject":Schema.hash_subject(base, str(session.username)), "channel":"ws",
				"trace_id":Schema.new_trace_id("ws")})
		_set_state("auth_rejected", "AUTH_REJECTED")
		return ERR_UNAUTHORIZED
	_session = {"server":base, "username":session.username, "message_token":session.message_token}
	_fingerprint = fingerprint
	_reconnect_attempt = 0
	_connect_started = Time.get_ticks_usec()
	_connect_trace = Schema.new_trace_id("ws")
	_connect_socket(_clock.call())
	return OK

func send_event(type: String, payload: Dictionary, durable: bool = false, parallel: bool = false) -> String:
	if _state.phase in ["idle", "auth_rejected"]:
		return ""
	return _outbox.enqueue(type, payload, durable, _clock.call(), parallel)

func get_state() -> Dictionary:
	return _state.duplicate()

func stop() -> void:
	_flush_audio_access()
	_close_socket()
	_session.clear()
	_fingerprint = ""
	_set_state("idle", "")
	_outbox.stop()

func _process(_delta: float) -> void:
	var now: int = _clock.call()
	_tick_reconnect(now)
	if _peer != null:
		_poll_socket(now)
	_tick_deadline(now)
	_tick_heartbeat(now)
	_send_pending(now)
	_tick_audio_flush(now)

func _tick_reconnect(now: int) -> void:
	if _state.phase == "reconnecting" and now >= _next_connect:
		_connect_socket(now)

func _tick_deadline(now: int) -> void:
	if _state.phase in ["connecting", "authenticating"] and now >= _deadline:
		_disconnect(now, "CONNECT_TIMEOUT" if _state.phase == "connecting" else "AUTH_TIMEOUT")

func _tick_heartbeat(now: int) -> void:
	if _state.phase != "ready":
		return
	# TCP 半开时 WebSocketPeer 仍会报 OPEN；只发不收会让连接永远停在 ready。
	if _ping_sent_at >= 0 and now - _ping_sent_at >= 15000:
		_disconnect(now, "HEARTBEAT_TIMEOUT")
		return
	if now - _last_rx >= 35000:
		_disconnect(now, "HEARTBEAT_TIMEOUT")
		return
	if now >= _next_heartbeat:
		_ping_id += 1
		_next_heartbeat = now + 10000
		_ping_sent_at = now
		_send_control("hb_ping", {"ping_id":_ping_id}, now)

func _tick_audio_flush(now: int) -> void:
	if _audio_started >= 0 and now - _audio_started >= 30000:
		_flush_audio_access()
func _connect_socket(now: int) -> void:
	_peer = WebSocketPeer.new()
	_peer.inbound_buffer_size = MAX_PACKET
	_peer.outbound_buffer_size = MAX_PACKET
	_peer.max_queued_packets = 64
	var base: String = _session.server
	var url := ("wss://" + base.substr(8) if base.begins_with("https://") else "ws://" + base.substr(7)) + "/chat_ws"
	_deadline = now + 8000
	_ping_id = 0
	_ping_sent_at = -1
	_last_rx = now
	_set_state("connecting", "")
	if _peer.connect_to_url(url) != OK:
		_disconnect(now, "CONNECTION_FAILED")

func _handle_event(event: Dictionary, now: int) -> void:
	if event.type == "auth_error":
		_reject_auth(_error_code(event.payload, "AUTH_REJECTED"))
		return
	# 限流、系统未就绪等错误不是凭据失败，不能写永久黑名单。
	if event.type == "error" and _state.phase == "authenticating":
		_disconnect(now, _error_code(event.payload, "AUTH_UNAVAILABLE"))
		return
	if event.type == "auth_ok" and _state.phase == "authenticating":
		_reconnect_attempt = 0
		_next_heartbeat = now
		_ping_sent_at = -1
		_last_rx = now
		_set_state("ready", "")
		_log_ws("connect", "auth_ok", "success", int((Time.get_ticks_usec() - _connect_started) / 1000), 0)
		return
	if event.type == "hb_pong":
		_ping_sent_at = -1
		_last_rx = now
		return
	if event.type in ["system_ready", "auth_ok"]:
		return
	if event.type == "system_not_ready":
		_disconnect(now, "SYSTEM_RUNTIME_NOT_READY")
		return
	if _state.phase != "ready":
		return
	_dispatch_event(event, now)
func _send_control(type: String, payload: Dictionary, now: int) -> void:
	var packet := {"type":type, "payload":payload, "client_msg_id":"c-" + Crypto.new().generate_random_bytes(16).hex_encode(),
		"ts":int(Time.get_unix_time_from_system() * 1000), "reply_to":null}
	var encoded := JSON.stringify(packet)
	if _peer == null or _peer.send_text(encoded) != OK:
		_disconnect(now, "SEND_FAILED")
	else:
		_log_ws("send", type, "success", 0, encoded.length())

func _disconnect(now: int, code: String) -> void:
	_log_ws("disconnect", code, "failure", int((Time.get_ticks_usec() - _connect_started) / 1000), 0, code)
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
	if _logger != null:
		_logger.log_debug("debug_state", {"data":{"phase":phase, "code":code, "reconnect":_reconnect_attempt}})

func _reject_auth(code: String) -> void:
	if _logger != null:
		_logger.log_security("security_ws_auth", {"action":"auth", "outcome":"denied", "reason_code":code,
			"subject":Schema.hash_subject(str(_session.get("server", "")), str(_session.get("username", ""))),
			"channel":"ws", "trace_id":_connect_trace if Schema.is_trace_id(_connect_trace) else Schema.new_trace_id("ws")})
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

func _poll_socket(now: int) -> void:
	_peer.poll()
	var ready := _peer.get_ready_state()
	if ready == WebSocketPeer.STATE_OPEN:
		if _state.phase == "connecting":
			_deadline = now + 5000
			_set_state("authenticating", "")
			_send_control("user_auth", {"username":_session.username, "token":_session.message_token,
				"capabilities":["negative_ack_v1"]}, now)
	# 关闭帧可能与 auth_error 或最终回复同批到达：先消费队列再决定是否重连。
	_receive_packets(now)
	if _peer != null and ready in [WebSocketPeer.STATE_CLOSED, WebSocketPeer.STATE_CLOSING]:
		if _state.phase == "authenticating" and _peer.get_close_code() == 1008:
			_reject_auth("AUTH_REJECTED")
		else:
			_disconnect(now, "CONNECTION_LOST")

func _receive_packets(now: int) -> void:
	var processed := 0
	while _can_receive(processed):
		var bytes := _peer.get_packet()
		var event := _parse_packet(bytes)
		if event.is_empty():
			_protocol_error(now)
			break
		_note_received(event, bytes.size(), now)
		_handle_event(event, now)
		processed += 1

func _can_receive(processed: int) -> bool:
	return _peer != null and _peer.get_available_packet_count() > 0 and processed < 64

func _parse_packet(bytes: PackedByteArray) -> Dictionary:
	if not _peer.was_string_packet() or bytes.size() > MAX_PACKET:
		return {}
	var parser := JSON.new()
	if parser.parse(bytes.get_string_from_utf8()) != OK:
		return {}
	return parser.data if _valid_event(parser.data) else {}

func _note_received(event: Dictionary, bytes: int, now: int) -> void:
	_last_rx = now
	if _is_audio_event(event):
		if _audio_started < 0:
			_audio_started = now
		_audio_frames += 1
		_audio_bytes += event.payload.audio.length()
	else:
		_log_ws("receive", str(event.type), "success", 0, bytes)

func _is_audio_event(event: Dictionary) -> bool:
	var payload: Variant = event.get("payload", {})
	return event.get("type") == "agent_message" and payload is Dictionary \
		and payload.get("audio") is String and not payload.audio.is_empty()

func _valid_event(event: Variant) -> bool:
	return event is Dictionary and event.get("type") is String and event.get("payload") is Dictionary

func _dispatch_event(event: Dictionary, now: int) -> void:
	if event.type == "server_ack":
		if event.get("reply_to") is String:
			_outbox.acknowledge(event.reply_to, event.payload, now)
	elif event.type == "error":
		system_error.emit(_error_code(event.payload, "SERVER_ERROR"))
	else:
		event_received.emit(event.duplicate(true))

func _send_pending(now: int) -> void:
	var packets: Array[Dictionary] = _outbox.take_ready(now, _state.phase == "ready")
	for packet in packets:
		var encoded := JSON.stringify(packet)
		if _peer == null or _peer.send_text(encoded) != OK:
			_disconnect(now, "SEND_FAILED")
			break
		_log_ws("send", str(packet.get("type", "unknown")), "success", 0, encoded.length())

func _log_ws(action: String, method: String, outcome: String, duration_ms: int, bytes: int, code: String = "") -> void:
	Events.ws(_logger, _connect_trace, action, method, outcome, duration_ms, bytes, code)

func _flush_audio_access() -> void:
	if _audio_frames <= 0:
		return
	if _logger != null:
		var now: int = _clock.call()
		Events.ws_audio(_logger, _connect_trace, _audio_frames, _audio_bytes, now - _audio_started)
	_audio_frames = 0
	_audio_bytes = 0
	_audio_started = -1
