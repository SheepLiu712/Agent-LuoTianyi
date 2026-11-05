extends SceneTree
const Transport = preload("res://src/network/websocket_transport.gd")
var failures: Array[String] = []
var now_ms := 0
var states: Dictionary = {}
var events: Array[Dictionary] = []
var errors: Array[String] = []
var transport: Node
var server: String

func check(ok: bool, description: String) -> void:
	if not ok:
		failures.append(description)
		print("FAIL: ", description)

func until(predicate: Callable) -> bool:
	var deadline := Time.get_ticks_msec() + 2000
	while not predicate.call() and Time.get_ticks_msec() < deadline:
		await process_frame
	return predicate.call()

func session(username: String, token: String = "message-test") -> Dictionary:
	return {"server":server + "/prefix", "username":username, "message_token":token, "login_token":"must-not-send"}

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	server = OS.get_environment("GODOT_TEST_SERVER")
	transport = Transport.new(func(): return now_ms)
	root.add_child(transport)
	transport.delivery_changed.connect(func(id, state, code): states[id] = [state, code])
	transport.event_received.connect(func(event): events.append(event))
	transport.system_error.connect(func(code): errors.append(code))
	check(transport.start({}) == ERR_INVALID_PARAMETER, "invalid session rejected")
	check(transport.start(session("normal")) == OK, "valid session starts")
	check(await until(func(): return transport.get_state().phase == "ready"), "actual auth_ok establishes ready")
	check(await until(func(): return events.any(func(e): return e.type == "heartbeat_seen")), "heartbeat sent immediately after auth")
	var id: String = transport.send_event("user_text", {"message":"你好", "llm_mode":{"types":[]}}, true)
	check(not id.is_empty(), "send returns stable ID")
	check(await until(func(): return states.get(id) == ["sent", "OK"]), "real socket ACK settles message")
	check(await until(func(): return events.any(func(e): return e.type == "agent_message" and e.payload.text == "收到")), "business reply delivered")
	check(not events.any(func(e): return e.type in ["auth_ok", "hb_pong", "server_ack"]), "protocol control events do not escape as business messages")
	events.clear()
	now_ms += 10000
	check(await until(func(): return events.any(func(e): return e.type == "heartbeat_seen" and e.payload.ping_id == 2)), "heartbeat repeats after ten seconds")
	transport.stop()
	check(transport.get_state().phase == "idle" and transport.send_event("user_text", {}, true).is_empty(), "stop closes and rejects work")
	check(transport.start(session("drop")) == OK, "reconnect scenario starts")
	await until(func(): return transport.get_state().phase == "ready")
	id = transport.send_event("user_text", {"message":"drop once"}, true)
	check(await until(func(): return transport.get_state().phase == "reconnecting"), "network loss schedules reconnect")
	now_ms += 2000
	check(await until(func(): return states.get(id) == ["sent", "OK"]), "durable ID survives real socket reconnect")
	transport.start(session("reject"))
	check(await until(func(): return transport.get_state().phase == "auth_rejected"), "explicit auth failure is terminal")
	now_ms += 100000
	await process_frame
	check(transport.get_state().phase == "auth_rejected", "rejected credentials never auto reconnect")
	transport.stop()
	check(transport.start(session("reject")) == ERR_UNAUTHORIZED, "same rejected credentials blocked after stop")
	check(transport.start(session("reject", "rotated-message")) == OK, "new message token unblocks authentication")
	check(await until(func(): return transport.get_state().phase == "ready"), "rotated token connects")
	transport.start(session("slow"))
	check(await until(func(): return transport.get_state().phase == "authenticating"), "socket opened before authentication deadline")
	now_ms += 5000
	check(await until(func(): return transport.get_state().phase == "reconnecting"), "silent auth cannot wait forever")
	transport.start(session("bad"))
	check(await until(func(): return errors.has("INVALID_RESPONSE")), "malformed wire input reports safe system error")
	transport.start(session("policy"))
	check(await until(func(): return transport.get_state().phase == "auth_rejected"), "authentication policy close is terminal even with coalesced close frame")
	transport.stop()
	transport.stop()
	transport.queue_free()
	await process_frame
	print("WebSocket transport: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
