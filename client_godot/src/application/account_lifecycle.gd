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
var _context: Dictionary = {}

func _init(chat: Node, models: Node, dynamics: Node, appearance: Resource = null, world: Resource = null, devices: Resource = null) -> void:
	_chat = chat
	_models = models
	_dynamics = dynamics
	_appearance = appearance
	_world = world
	_devices = devices

func start(session: Dictionary) -> void:
	stop()
	_generation += 1
	_context = {"scope_id":Scope.key(session.server,session.username),"generation":_generation,"character_id":"luotianyi"}
	_active = true
	_chat.start(session)
	_models.start(session)
	_dynamics.start(session)
	for capability in [_appearance,_world,_devices]:
		if capability != null: capability.start(get_context())

func get_context() -> Dictionary:
	return _context.duplicate(true)

func stop() -> void:
	if not _active: return
	_active = false
	_context.clear()
	for capability in [_appearance,_world,_devices]:
		if capability != null: capability.stop()
	for controller in [_models,_dynamics,_chat]:
		if is_instance_valid(controller): controller.stop()
