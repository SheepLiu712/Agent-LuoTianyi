extends PanelContainer
signal log_requested
signal feedback_requested
signal exit_requested
const Session = preload("res://src/session/account_session.gd")
const HistoryRow = preload("res://scenes/ui/login_account_row.tscn")
var _session: Node
var _fields: Dictionary = {}
var _initialized := false
var _mode := "login"
var _busy := false
var _syncing := false
var _manual_password := false
var _removing := ""
@onready var _form: VBoxContainer = %Form
@onready var _remember: CheckBox = %Remember
@onready var _automatic: CheckBox = %AutoLogin
@onready var _submit: Button = %Submit
@onready var _status: Label = %Status

func setup(session: Node) -> void:
	_session = session
	if is_node_ready(): _initialize()

func _ready() -> void:
	%CloseLogin.pressed.connect(func(): exit_requested.emit())
	%DragArea.gui_input.connect(_drag_window)
	%MenuButton.pressed.connect(_open_menu)
	%MenuPopup.visibility_changed.connect(func(): %MenuButton.set_pressed_no_signal(%MenuPopup.visible))
	%Logs.pressed.connect(func(): %MenuPopup.hide(); log_requested.emit())
	%Feedback.pressed.connect(func(): %MenuPopup.hide(); feedback_requested.emit())
	for button in [%Submit,%Remember,%AutoLogin,%RegisterLink,%ResetLink,%SetServer,%HistoryButton]: button.disabled = true
	if _session != null: _initialize()

func _initialize() -> void:
	if _initialized: return
	_initialized = true
	_fields = {"server":%Server,"username":%Username,"password":%Password,"confirm":%Confirm,"invite":%Invite}
	for name in ["username","password","confirm","invite"]:
		_fields[name].text_submitted.connect(func(_text): _send())
	_fields.username.text_changed.connect(_username_changed)
	_submit.pressed.connect(_send)
	%Cancel.pressed.connect(_session.cancel)
	%SetServer.pressed.connect(_open_server)
	%RegisterLink.pressed.connect(func(): select_mode("register"))
	%ResetLink.pressed.connect(func(): select_mode("reset"))
	%BackToLogin.pressed.connect(func(): select_mode("login"))
	%UsePassword.pressed.connect(func(): _manual_password = true; _apply_mode(); %Password.grab_focus())
	%HistoryButton.pressed.connect(_open_history)
	_remember.toggled.connect(func(_pressed): _options_changed(false))
	_automatic.toggled.connect(func(_pressed): _options_changed(true))
	%ServerSave.pressed.connect(_save_server)
	%Server.text_submitted.connect(func(_text): _save_server())
	%ServerDefault.pressed.connect(func(): %Server.text = Session.DEFAULT_SERVER)
	%ServerCancel.pressed.connect(_cancel_server)
	%ServerClose.pressed.connect(_cancel_server)
	%ServerDialog.close_requested.connect(_cancel_server)
	%RemoveAccountDialog.confirmed.connect(_remove_record)
	resized.connect(_layout_form)
	_layout_form()
	_session.changed.connect(_update_state)
	for button in [%Submit,%Remember,%AutoLogin,%RegisterLink,%ResetLink,%SetServer,%HistoryButton]: button.disabled = false
	_sync_selected()
	if _session.get_login_defaults().storage_error: _status.text = _error_text("STORAGE_ERROR")

func select_mode(mode: String) -> void:
	if _busy or mode not in ["login","register","reset"]: return
	_mode = mode
	_clear_secrets()
	_status.text = ""
	%FeedbackAddress.hide()
	_manual_password = false
	_apply_mode()

func _apply_mode() -> void:
	var login := _mode == "login"
	var signed_in: bool = not _session.get_session().is_empty()
	var saved: bool = login and not _manual_password and _remembered().get("remember", false)
	%AvatarBlock.visible = login
	%AvatarGap.visible = login
	%BackToLogin.visible = not login
	%ModeTitle.visible = not login
	%ModeTitle.text = "注册账号" if _mode == "register" else "忘记密码"
	%ModeHelp.visible = _mode == "reset"
	%Username.placeholder_text = "新用户名" if _mode == "reset" else "用户名"
	%Password.placeholder_text = "新密码" if _mode == "reset" else "密码"
	%Confirm.placeholder_text = "确认新密码" if _mode == "reset" else "确认密码"
	%Confirm.visible = not login
	%Invite.visible = not login
	%Invite.placeholder_text = "已使用的邀请码" if _mode == "reset" else "邀请码"
	%Password.visible = not saved
	%SavedLogin.visible = saved
	%HistoryButton.visible = login
	%Options.visible = login
	%Footer.visible = login and not signed_in
	%Footer.get_parent().visible = login and not signed_in
	_form.visible = not signed_in
	_submit.text = {"login":"登录","register":"注册","reset":"重置账号"}[_mode]

func _remembered() -> Dictionary:
	for entry in _session.get_history():
		if entry.username == _fields.username.text: return entry
	return {}

func _sync_selected() -> void:
	_syncing = true
	var defaults: Dictionary = _session.get_login_defaults()
	_fields.username.text = defaults.username
	_fields.server.text = defaults.server
	_remember.set_pressed_no_signal(defaults.remember)
	_automatic.set_pressed_no_signal(defaults.auto_login)
	_clear_secrets()
	_manual_password = false
	_syncing = false
	_apply_mode()

func _username_changed(_text: String) -> void:
	if _syncing or _busy or _mode != "login": return
	var entry := _remembered()
	_remember.set_pressed_no_signal(entry.get("remember",false))
	_automatic.set_pressed_no_signal(entry.get("auto_login",false))
	_fields.password.clear()
	_manual_password = false
	_apply_mode()

func _options_changed(automatic_source: bool) -> void:
	if _syncing or _busy: return
	if automatic_source and _automatic.button_pressed: _remember.set_pressed_no_signal(true)
	if not automatic_source and not _remember.button_pressed: _automatic.set_pressed_no_signal(false)
	var entry := _remembered()
	if entry.get("remember",false):
		var result: Dictionary = _session.set_login_options(entry.username, _remember.button_pressed, _automatic.button_pressed)
		if not result.ok:
			_remember.set_pressed_no_signal(entry.remember)
			_automatic.set_pressed_no_signal(entry.auto_login)
			_status.text = _error_text(result.code)
	_apply_mode()

func _send() -> void:
	if _busy: return
	var operation := _mode
	if operation != "login" and _fields.password.text != _fields.confirm.text:
		_status.text = "两次输入的密码不一致。"
		return
	%FeedbackAddress.hide()
	var response: Dictionary
	if operation == "login" and %SavedLogin.visible:
		response = await _session.login_saved(_fields.username.text)
	else:
		var fields := {"username":_fields.username.text,"password":_fields.password.text}
		if operation == "register": fields.invite_code = _fields.invite.text
		elif operation == "reset": fields = {"new_username":_fields.username.text,"new_password":_fields.password.text,"invite_code":_fields.invite.text}
		response = await _session.perform(operation, _session.get_login_defaults().server, fields, _remember.button_pressed if operation == "login" else false, _automatic.button_pressed if operation == "login" else false)
	if response.ok:
		_clear_secrets()
		if operation != "login":
			select_mode("login")
			_status.text = "注册成功，请登录。" if operation == "register" else "账号重置成功，请使用新账号登录。"
	elif not response.storage_error:
		_status.text = _error_text(response.code, response.get("status",0))
	_apply_mode()

func _update_state(state: Dictionary) -> void:
	_busy = state.phase == "busy"
	for name in ["username","password","confirm","invite","server"]: _fields[name].editable = not _busy
	for button in [_submit,_remember,_automatic,%BackToLogin,%RegisterLink,%ResetLink,%HistoryButton,%UsePassword,%SetServer,%ServerSave,%ServerDefault]: button.disabled = _busy
	%Cancel.visible = _busy and not %ServerDialog.visible
	if state.code in ["SERVER_CHANGED","ACCOUNT_SELECTED","ACCOUNT_REMOVED","LOGGED_OUT"]: _sync_selected()
	if state.phase == "signed_in": _clear_secrets()
	_status.text = _error_text(state.code)
	if state.storage_error: _status.text = _error_text("STORAGE_ERROR")
	_apply_mode()

func _open_menu() -> void:
	if %MenuPopup.visible: %MenuPopup.hide(); return
	%HistoryPopup.hide()
	var available := get_window().get_visible_rect().size
	var bottom: Vector2 = %MenuButton.get_global_transform_with_canvas() * Vector2(0,%MenuButton.size.y)
	_popup(%MenuPopup, Vector2(available.x-192,bottom.y+6), Vector2i(168,152))
	(%Logs if %SetServer.disabled else %SetServer).grab_focus.call_deferred()

func _popup(window: Window, position: Vector2, requested: Vector2i) -> void:
	var available := get_window().get_visible_rect().size
	var extent := Vector2i(mini(requested.x,int(available.x)-16),mini(requested.y,int(available.y)-16))
	position = position.clamp(Vector2(8,8), (available-Vector2(extent)-Vector2(8,8)).max(Vector2(8,8)))
	window.content_scale_mode = Window.CONTENT_SCALE_MODE_CANVAS_ITEMS
	window.content_scale_size = Vector2i.ZERO
	window.content_scale_factor = 1
	window.popup(Rect2i(Vector2i(position),extent))

func _open_history() -> void:
	if _busy: return
	%MenuPopup.hide()
	for child in %HistoryRows.get_children():
		if child != %HistoryEmpty:
			%HistoryRows.remove_child(child)
			child.queue_free()
	var history: Array = _session.get_history()
	%HistoryEmpty.visible = history.is_empty()
	for entry in history:
		var row := HistoryRow.instantiate()
		row.get_node("%Choose").text = entry.username
		row.get_node("%Choose").pressed.connect(func(): %HistoryPopup.hide(); _session.select_account(entry.username))
		row.get_node("%Remove").pressed.connect(func():
			%HistoryPopup.hide()
			_removing = entry.username
			%RemoveAccountDialog.dialog_text = "移除“%s”的本机账号记录和已记住的登录状态？不会删除服务器账号或聊天、语音缓存。" % entry.username
			%RemoveAccountDialog.popup_centered())
		%HistoryRows.add_child(row)
	var anchor: Control = %Username.get_parent().get_parent()
	_popup(%HistoryPopup, anchor.get_global_transform_with_canvas() * Vector2(0,anchor.size.y+6), Vector2i(int(anchor.size.x),mini(280,maxi(64,history.size()*48+16))))

func _remove_record() -> void:
	var response: Dictionary = _session.remove_account(_removing)
	_removing = ""
	if not response.ok: _status.text = _error_text(response.code)

func _open_server() -> void:
	%MenuPopup.hide()
	if _busy: return
	%Server.text = _session.get_login_defaults().server
	%ServerStatus.text = "验证连接成功后才使用新地址。"
	var available := Vector2i(get_window().get_visible_rect().size)-Vector2i(24,24)
	%ServerDialog.popup_centered(Vector2i(mini(416,available.x),mini(280,available.y)))
	%Server.grab_focus()

func _save_server() -> void:
	if _busy: return
	%ServerStatus.text = "正在验证服务器…"
	var response: Dictionary = await _session.set_server(%Server.text)
	if not %ServerDialog.visible: return
	if response.ok: %ServerDialog.hide()
	else: %ServerStatus.text = _error_text(response.code,response.get("status",0))

func _cancel_server() -> void:
	if _busy and %ServerDialog.visible: _session.cancel()
	%ServerDialog.hide()

func report_feedback_result(error: Error) -> void:
	if error == OK: return
	_status.text = "无法打开浏览器，可复制下方项目地址。"
	%FeedbackAddress.show()

func _drag_window(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT and event.pressed and not event.double_click:
		get_window().start_drag()

func _layout_form() -> void:
	%FormMargin.theme_type_variation = &"LoginCompactMargin" if size.x < 440 else &"LoginFormMargin"

func _clear_secrets() -> void:
	for field in ["password","confirm","invite"]: _fields[field].clear()

static func _error_text(code: String, status: int = 0) -> String:
	return {"OK":"登录成功。", "LOGGED_OUT":"已退出登录。", "PENDING":"正在处理…", "CANCELLED":"请求已取消。",
		"AUTH_REJECTED":"用户名或密码错误，或自动登录凭据已失效。", "INVALID_INPUT":"请填写完整信息并检查服务器地址。",
		"TIMEOUT":"连接超时，请稍后重试。", "NETWORK_ERROR":"无法连接服务器，请检查地址和网络。",
		"PUBLIC_KEY_ERROR":"无法获取服务器公钥，请检查服务器地址。", "ENCRYPTION_ERROR":"密码加密失败，请检查密码长度或服务器公钥。",
		"INVALID_RESPONSE":"服务器返回的数据不完整，请稍后重试。", "CREDENTIAL_UNAVAILABLE":"无法读取自动登录凭据，请重新登录。",
		"HTTP_ERROR":"服务器拒绝了请求（%s），请检查账户信息或邀请码。" % status,
		"NO_SAVED_LOGIN":"请使用密码登录。", "SERVER_CHANGED":"服务器已更新。", "CHECKING_SERVER":"正在验证服务器…", "ACCOUNT_SELECTED":"", "ACCOUNT_REMOVED":"本机账号记录已移除。", "OPTIONS_CHANGED":"", "STORAGE_ERROR":"本地登录资料未能保存或清除，请检查权限后重试。", "BUSY":"正在处理上一次请求。"}.get(code, "账户操作未完成，请重试。")
