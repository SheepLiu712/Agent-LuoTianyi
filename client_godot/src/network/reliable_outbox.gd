extends RefCounted
signal delivery_changed(id: String, state: String, code: String)

const MAX_AGE_MS := 240000
const RETRY_DELAYS := [1000, 2000, 4000, 8000, 16000, 30000, 30000, 30000]
var _pending: Dictionary = {}

func enqueue(type: String, payload: Dictionary, durable: bool, now_ms: int) -> String:
	if _pending.size() >= 128:
		return ""
	var id := "c-" + Crypto.new().generate_random_bytes(16).hex_encode()
	var packet := {"type":type, "payload":payload.duplicate(true), "client_msg_id":id,
		"ts":int(Time.get_unix_time_from_system() * 1000), "reply_to":null}
	if JSON.stringify(packet).to_utf8_buffer().size() > 8 * 1024 * 1024:
		return ""
	_pending[id] = {"packet":packet, "durable":durable, "created":now_ms,
		"ready":now_ms, "deadline":0, "attempts":0, "waiting":false}
	delivery_changed.emit(id, "queued", "")
	return id

func take_ready(now_ms: int, connected: bool) -> Array[Dictionary]:
	# Expiry runs even without a connection, so queued work cannot live forever.
	for id in _pending.keys():
		var entry: Dictionary = _pending[id]
		if entry.durable and now_ms - entry.created >= MAX_AGE_MS:
			_finish(id, "uncertain", "DELIVERY_UNCERTAIN")
		elif not connected and not entry.durable:
			_finish(id, "failed", "DISCONNECTED")
		elif entry.waiting and now_ms >= entry.deadline:
			_retry_or_finish(id, now_ms, "ACK_TIMEOUT")
	var packets: Array[Dictionary] = []
	if not connected:
		return packets
	var durable_blocked := false
	for id in _pending.keys():
		var entry: Dictionary = _pending[id]
		if entry.durable:
			if durable_blocked:
				continue
			durable_blocked = true
		if entry.waiting or now_ms < entry.ready:
			continue
		entry.waiting = true
		entry.attempts += 1
		var timeout := 5000 if entry.packet.type in ["user_image_selecting", "user_image_selecting_cancel"] else 10000
		entry.deadline = now_ms + timeout
		packets.append(entry.packet.duplicate(true))
		delivery_changed.emit(id, "sending", "")
	return packets

func acknowledge(reply_to: String, payload: Dictionary, now_ms: int) -> void:
	if not _pending.has(reply_to) or _pending[reply_to].attempts == 0:
		return
	if _pending[reply_to].durable and now_ms - _pending[reply_to].created >= MAX_AGE_MS:
		_finish(reply_to, "uncertain", "DELIVERY_UNCERTAIN")
		return
	# Legacy ACKs omit ok. Only a JSON boolean false is a negative ACK.
	if typeof(payload.get("ok")) != TYPE_BOOL or payload.ok:
		_finish(reply_to, "sent", "OK")
		return
	var code: String = payload.code if payload.get("code") is String else "REJECTED"
	if code.is_empty():
		code = "REJECTED"
	if typeof(payload.get("retryable")) == TYPE_BOOL and payload.retryable:
		# Duplicate NACKs during backoff must not consume retry attempts.
		if _pending[reply_to].waiting:
			_retry_or_finish(reply_to, now_ms, code)
	else:
		_finish(reply_to, "failed", code)

func disconnected(now_ms: int) -> void:
	for id in _pending.keys():
		var entry: Dictionary = _pending[id]
		if not entry.durable:
			_finish(id, "failed", "DISCONNECTED")
		elif entry.waiting:
			_retry_or_finish(id, now_ms, "DISCONNECTED")

func stop(code: String = "TRANSPORT_STOPPED") -> void:
	var ids := _pending.keys()
	_pending.clear()
	for id in ids:
		delivery_changed.emit(id, "failed", code)

func _retry_or_finish(id: String, now_ms: int, code: String) -> void:
	var entry: Dictionary = _pending[id]
	if not entry.durable:
		_finish(id, "failed", code)
		return
	var retry_index: int = entry.attempts - 1
	if retry_index >= RETRY_DELAYS.size():
		_finish(id, "uncertain", "DELIVERY_UNCERTAIN")
		return
	var ready: int = now_ms + RETRY_DELAYS[retry_index]
	if ready - entry.created >= MAX_AGE_MS:
		_finish(id, "uncertain", "DELIVERY_UNCERTAIN")
		return
	entry.waiting = false
	entry.ready = ready
	delivery_changed.emit(id, "queued", code)

func _finish(id: String, state: String, code: String) -> void:
	_pending.erase(id)
	delivery_changed.emit(id, state, code)
