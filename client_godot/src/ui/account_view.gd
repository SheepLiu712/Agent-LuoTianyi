extends PanelContainer
signal log_requested
var _session: Node
var _fields: Dictionary = {}
var _initialized := false
@onready var _form: VBoxContainer = %Form
@onready var _mode = %AccountMode
@onready var _remember: CheckBox = %Remember
@onready var _submit: Button = %Submit
@onready var _cancel: Button = %Cancel
@onready var _status: Label = %Status
@onready var _identity: Label = %Identity
@onready var _logout: Button = %Logout
@onready var _logs: Button = %Logs

func setup(session: Node) -> void:
	_session = session
	if is_node_ready():
		_initialize()

func _ready() -> void:
	if _session == null:
		return
	_initialize()

func _initialize() -> void:
	if _initialized:
		return
	_initialized = true
	_fields = {"server":%Server,"username":%Username,"password":%Password,"confirm":%Confirm,"invite":%Invite}
	for field in _fields.values():
		field.text_submitted.connect(func(_text): _send())
	_mode.set_items([{"id":"login","label":"密码登录"},{"id":"register","label":"注册账户"},{"id":"reset","label":"邀请码重置账户"}])
	_mode.activated.connect(func(_index): _apply_mode())
	%BackToLogin.pressed.connect(func(): _mode.set_selected_id("login"); _apply_mode())
	_submit.pressed.connect(_send)
	_cancel.pressed.connect(_session.cancel)
	_logout.pressed.connect(func():
		_clear_secrets()
		_session.logout())
	_logs.pressed.connect(func(): log_requested.emit())
	var defaults: Dictionary = _session.get_login_defaults()
	_fields.server.text = defaults.server
	_fields.username.text = defaults.username
	_remember.button_pressed = defaults.remember
	_session.changed.connect(_update_state)
	_apply_mode()

func _apply_mode() -> void:
	%BackToLogin.visible = _mode.get_selected_id() != "login"
	_fields.confirm.visible = _mode.get_selected_id() != "login"
	_fields.invite.visible = _mode.get_selected_id() != "login"
	_remember.visible = _mode.get_selected_id() == "login"
	_submit.text = {"login":"登录","register":"注册","reset":"重置账户"}[_mode.get_selected_id()]

func _send() -> void:
	if _submit.disabled:
		return
	if _mode.get_selected_id() != "login" and _fields.password.text != _fields.confirm.text:
		_status.text = "两次输入的密码不一致。"
		return
	var operation: String = _mode.get_selected_id()
	var fields := {"username":_fields.username.text, "password":_fields.password.text}
	if operation == "login":
		fields.request_token = _remember.button_pressed
	elif operation == "register":
		fields.invite_code = _fields.invite.text
	else:
		fields = {"new_username":_fields.username.text, "new_password":_fields.password.text, "invite_code":_fields.invite.text}
	var response: Dictionary = await _session.perform(operation, _fields.server.text, fields, _remember.button_pressed, _remember.button_pressed)
	if response.ok:
		_clear_secrets()
		if operation != "login":
			_mode.set_selected_id("login")
			_apply_mode()
			_status.text = "注册成功，请登录。" if operation == "register" else "账户重置成功，请用新账户登录。"
	else:
		_status.text = _error_text(response.code, response.get("status", 0))

func _update_state(state: Dictionary) -> void:
	var busy: bool = state.phase == "busy"
	var signed_in: bool = state.phase == "signed_in"
	_form.visible = not signed_in
	_cancel.visible = busy
	_identity.visible = signed_in
	_logout.visible = signed_in
	_mode.disabled = busy
	%BackToLogin.disabled = busy
	_remember.disabled = busy
	_submit.disabled = busy
	for field in _fields.values():
		field.editable = not busy
	if signed_in:
		_identity.text = "已登录：" + str(_session.get_session().get("username", ""))
		_clear_secrets()
	_status.text = "正在连接账户服务…" if busy else _error_text(state.code)
	if state.storage_error:
		_status.text = "账户操作已结束，但本地凭据无法保存或清除，请检查数据目录权限。"
	_remember.button_pressed = _session.get_login_defaults().remember if not busy else _remember.button_pressed

func _clear_secrets() -> void:
	for field in ["password", "confirm", "invite"]:
		_fields[field].clear()

static func _error_text(code: String, status: int = 0) -> String:
	return {"OK":"登录成功。", "LOGGED_OUT":"已退出登录。", "PENDING":"正在处理…", "CANCELLED":"请求已取消。",
		"AUTH_REJECTED":"用户名或密码错误，或自动登录凭据已失效。", "INVALID_INPUT":"请填写完整信息并检查服务器地址。",
		"TIMEOUT":"连接超时，请稍后重试。", "NETWORK_ERROR":"无法连接服务器，请检查地址和网络。",
		"PUBLIC_KEY_ERROR":"无法获取服务器公钥，请检查服务器地址。", "ENCRYPTION_ERROR":"密码加密失败，请检查密码长度或服务器公钥。",
		"INVALID_RESPONSE":"服务器返回的数据不完整，请稍后重试。", "CREDENTIAL_UNAVAILABLE":"无法读取自动登录凭据，请重新登录。",
		"HTTP_ERROR":"服务器拒绝了请求（%s），请检查账户信息或邀请码。" % status,
		"NO_SAVED_LOGIN":"", "BUSY":"正在处理上一次请求。"}.get(code, "账户操作未完成，请重试。")
