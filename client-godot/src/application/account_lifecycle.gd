extends RefCounted
const Scope = preload("res://src/domain/account_scope.gd")
var _chat: Node
var _models: Node
var _dynamics: Node
var _appearance: Resource
var _world: Resource
var _devices: Resource
var _generation := 0
var _active := false
var _has_resources := false
var _identity := ""
var _context: Dictionary = {}

func _init(chat: Node, models: Node, dynamics: Node, appearance: Resource = null, world: Resource = null, devices: Resource = null) -> void:
	_chat = chat
	_models = models
	_dynamics = dynamics
	_appearance = appearance
	_world = world
	_devices = devices

func start(session: Dictionary) -> Error:
	var scope := Scope.key(session.server,session.username)
	var identity := JSON.stringify([scope,session.get("message_token","")]).sha256_text()
	if _active and _identity == identity: return OK
	stop()
	_identity = identity
	_generation += 1
	_context = {"scope_id":scope,"generation":_generation,"character_id":"luotianyi"}
	_has_resources = true
	# Chat owns the transport boundary.  It must be ready before controllers
	# that advertise models, history or dynamics can observe the new account.
	var result: Error = _chat.start(session)
	if result != OK:
		stop()
		return result
	_models.start(session)
	_dynamics.start(session)
	for capability in [_appearance,_world,_devices]:
		if capability == null:
			continue
		var capability_result: Error = capability.start(get_context())
		# Optional future capabilities are allowed to be unavailable without
		# preventing text chat. Any other startup error rolls the account back.
		if capability_result != OK and capability_result != ERR_UNAVAILABLE:
			stop()
			return capability_result
	_active = true
	return OK

func get_context() -> Dictionary:
	return _context.duplicate(true)

func stop() -> void:
	if not _has_resources and not _active and _context.is_empty() and _identity.is_empty():
		return
	_active = false
	_identity = ""
	_context.clear()
	for capability in [_appearance,_world,_devices]:
		if capability != null: capability.stop()
	for controller in [_models,_dynamics,_chat]:
		if is_instance_valid(controller): controller.stop()
	_has_resources = false
