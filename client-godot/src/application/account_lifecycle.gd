extends RefCounted
const Scope = preload("res://src/domain/account_scope.gd")
var _chat: Node
var _models: Node
var _dynamics: Node
var _appearance: Resource
var _world: Resource
var _devices: Resource
var _avatar: Node
var _generation := 0
var _active := false
var _has_resources := false
var _identity := ""
var _context: Dictionary = {}
var _logger: RefCounted

func _init(chat: Node, models: Node, dynamics: Node, appearance: Resource = null, world: Resource = null, devices: Resource = null, avatar: Node = null, logger: RefCounted = null) -> void:
	_chat = chat
	_models = models
	_dynamics = dynamics
	_appearance = appearance
	_world = world
	_devices = devices
	_avatar = avatar
	_logger = logger

func start(session: Dictionary) -> Error:
	var scope := Scope.key(session.server,session.username)
	var identity := JSON.stringify([scope,session.get("message_token","")]).sha256_text()
	if _active and _identity == identity: return OK
	stop()
	_identity = identity
	_generation += 1
	_context = {"scope_id":scope,"generation":_generation,"character_id":"luotianyi"}
	_has_resources = true
	# 聊天握着 transport 边界：必须先就绪，动态/历史/模型控制器才能观察新账号。
	var result: Error = _chat.start(session)
	if result != OK:
		_log("start", "failure", result)
		stop()
		return result
	_models.start(session)
	_dynamics.start(session)
	# 头像只跟着账号走：换账号时先清空再读新账号的那一张。
	if _avatar != null: _avatar.start(session)
	for capability in [_appearance,_world,_devices]:
		if capability == null:
			continue
		var capability_result: Error = capability.start(get_context())
		# 扩展能力允许缺席（ERR_UNAVAILABLE）而不阻断文字聊天；其它启动错误整体回滚。
		if capability_result != OK and capability_result != ERR_UNAVAILABLE:
			stop()
			return capability_result
	_active = true
	_log("start", "success", OK)
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
	if _avatar != null: _avatar.stop()
	for controller in [_models,_dynamics,_chat]:
		if is_instance_valid(controller): controller.stop()
	_has_resources = false
	_log("stop", "success", OK)

func _log(action: String, outcome: String, result: Error) -> void:
	if _logger == null:
		return
	_logger.log_runtime("runtime_account_lifecycle", {"phase":action, "reason":"account", "outcome":outcome,
		"code":"OK" if result == OK else "ACCOUNT_START_FAILED"})
