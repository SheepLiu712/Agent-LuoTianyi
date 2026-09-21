extends RefCounted
signal exit_requested
signal logout_requested
var _host: Control
var _dialog: Window
var _images: Node
var _geometry: Resource
var _settings_factory: Callable
var _dynamics_factory: Callable
var _chat_dirty: Callable
var _windows: Dictionary = {}
var _action := ""
var _waiting_save := false
var _disposed := false

func _init(host: Control, dialog: Window, images: Node, geometry: Resource, settings_factory: Callable, dynamics_factory: Callable, chat_dirty: Callable) -> void:
	_host = host
	_dialog = dialog
	_images = images
	_geometry = geometry
	_settings_factory = settings_factory
	_dynamics_factory = dynamics_factory
	_chat_dirty = chat_dirty
	_dialog.confirmed.connect(_confirmed)
	_dialog.canceled.connect(_cancel)

func open(kind: String) -> void:
	if _disposed or kind not in ["settings","dynamics"]: return
	if is_instance_valid(_windows.get(kind)):
		_windows[kind].open()
		return
	var built: Dictionary = (_settings_factory if kind == "settings" else _dynamics_factory).call()
	var window: Window = built.window
	_windows[kind] = window
	if kind == "settings": window.logout_requested.connect(func(): request_close("logout"))
	_host.add_child(window)
	window.get_node("%Chrome").configure(_geometry,kind)
	window.tree_exited.connect(func():
		if _windows.get(kind) == window: _windows.erase(kind))
	window.open()
	if built.start.is_valid(): built.start.call()

func request_close(action: String) -> void:
	if _disposed or action not in ["exit","logout"]: return
	var settings = _windows.get("settings")
	if is_instance_valid(settings) and settings.is_saving():
		_action = action
		if not _waiting_save:
			_waiting_save = true
			settings.saving_finished.connect(func(_ok):
				_waiting_save = false
				request_close(_action),CONNECT_ONE_SHOT)
		return
	var drafts: Array[String] = []
	if _chat_dirty.call(): drafts.append("聊天输入中的未发送文字或图片")
	for key in _windows:
		var window = _windows[key]
		if is_instance_valid(window) and window.is_dirty():
			drafts.append("设置中的未保存修改" if key == "settings" else "动态发布或评论草稿")
	_action = action
	if drafts.is_empty():
		_confirmed()
		return
	_dialog.hide()
	var owner: Node = settings if action == "logout" and is_instance_valid(settings) else _host
	if _dialog.get_parent() != owner: _dialog.reparent(owner)
	_dialog.title = "退出应用前请确认" if action == "exit" else "退出登录前请确认"
	_dialog.dialog_text = "以下内容尚未提交：\n• " + "\n• ".join(drafts) + "\n不会自动保存或发送。"
	_dialog.popup_centered()
	_dialog.get_cancel_button().grab_focus()

func _confirmed() -> void:
	var action := _action
	if _disposed or action not in ["exit","logout"]: return
	var settings = _windows.get("settings")
	if is_instance_valid(settings) and settings.is_saving():
		_return_dialog()
		request_close(action)
		return
	close_all()
	_action = ""
	if action == "exit": exit_requested.emit()
	else: logout_requested.emit()

func _cancel() -> void:
	_action = ""
	_return_dialog()

func close_all() -> void:
	_return_dialog()
	_images.close()
	for window in _windows.values():
		if is_instance_valid(window):
			window.hide()
			window.queue_free()
	_windows.clear()

func _return_dialog() -> void:
	_dialog.hide()
	if _dialog.get_parent() != _host: _dialog.reparent(_host)

func dispose() -> void:
	_disposed = true
	_action = ""
	if is_instance_valid(_dialog):
		_dialog.confirmed.disconnect(_confirmed)
		_dialog.canceled.disconnect(_cancel)
	_settings_factory = Callable()
	_dynamics_factory = Callable()
	_chat_dirty = Callable()
