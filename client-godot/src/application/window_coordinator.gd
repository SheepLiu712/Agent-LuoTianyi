extends RefCounted
const Events = preload("res://src/storage/log_events.gd")
signal exit_requested
signal logout_requested
var _host: Control
var _dialog: Window
var _images: Node
var _geometry: Resource
var _settings_factory: Callable
var _dynamics_factory: Callable
var _chat_dirty: Callable
var _logger: RefCounted
var _windows: Dictionary = {}
var _starters: Dictionary = {}
var _started: Dictionary = {}
var _action := ""
var _waiting_save := false
var _disposed := false

func _init(host: Control, dialog: Window, images: Node, geometry: Resource, settings_factory: Callable, dynamics_factory: Callable, chat_dirty: Callable, logger: RefCounted = null) -> void:
	_host = host
	_dialog = dialog
	_images = images
	_geometry = geometry
	_settings_factory = settings_factory
	_dynamics_factory = dynamics_factory
	_chat_dirty = chat_dirty
	_logger = logger
	_dialog.confirmed.connect(_confirmed)
	_dialog.canceled.connect(_cancel)

func open(kind: String) -> void:
	if _disposed or kind not in ["settings","dynamics"]: return
	var existing = _windows.get(kind)
	if is_instance_valid(existing) and existing.visible:
		existing.open()
		return
	var window := _ensure_window(kind)
	if not is_instance_valid(window): return
	_start_window(kind)
	if kind == "settings" and not window.is_data_settled(): await _wait_for_settings(window)
	if not is_instance_valid(window): return
	window.open()
	_log("access", kind, "open", "success", 0)
	_log("runtime", kind, "open", "success", 0)

## 登录成功后预先构建设置窗并启动偏好加载；用户打开时只负责显示。
func prewarm(kind: String) -> void:
	if _disposed or kind != "settings": return
	if is_instance_valid(_windows.get(kind)): return
	_ensure_window(kind)
	_start_window(kind)

func _ensure_window(kind: String) -> Window:
	var existing = _windows.get(kind)
	if is_instance_valid(existing): return existing
	var built: Dictionary = (_settings_factory if kind == "settings" else _dynamics_factory).call()
	var window: Window = built.window
	_windows[kind] = window
	_starters[kind] = built.get("start", Callable())
	if kind == "settings": window.logout_requested.connect(func(): request_close("logout"))
	_host.add_child(window)
	window.get_node("%Chrome").configure(_geometry,kind)
	window.tree_exited.connect(func():
		if _windows.get(kind) == window:
			_windows.erase(kind)
			_started.erase(kind)
			_starters.erase(kind))
	return window

func _start_window(kind: String) -> void:
	if _started.get(kind,false): return
	_started[kind] = true
	var start: Callable = _starters.get(kind,Callable())
	if start.is_valid(): start.call()

func _wait_for_settings(window: Window) -> void:
	var deadline := Time.get_ticks_msec() + 20000
	while is_instance_valid(window) and not window.is_data_settled() and Time.get_ticks_msec() < deadline:
		await _host.get_tree().process_frame

## 打开或复用动态窗口，并让窗口选中角色卡片对应的动态。
func open_post(post: Dictionary) -> bool:
	if _disposed or post.is_empty() or str(post.get("id", "")).is_empty():
		return false
	open("dynamics")
	var window: Window = _windows.get("dynamics")
	if not is_instance_valid(window) or not window.has_method("open_post"):
		return false
	return await window.open_post(post)

func request_close(action: String) -> void:
	if _disposed or action not in ["exit","logout"]: return
	_log("runtime", "main", "close", "success", 0, action)
	var settings = _windows.get("settings")
	if is_instance_valid(settings) and settings.is_saving():
		_action = action
		if not _waiting_save:
			_waiting_save = true
			settings.saving_finished.connect(func(_ok):
				_waiting_save = false
				request_close(_action),CONNECT_ONE_SHOT)
		return
	var drafts := _collect_drafts()
	_action = action
	if drafts.is_empty() and action != "logout":
		_confirmed()
		return
	_show_close_dialog(action, settings, drafts)
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
	_log("runtime", "all", "close", "success", 0, "close_all")
	for window in _windows.values():
		if is_instance_valid(window):
			window.hide()
			window.queue_free()
	_windows.clear()
	_starters.clear()
	_started.clear()

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

func _collect_drafts() -> Array[String]:
	var drafts: Array[String] = []
	if _chat_dirty.call(): drafts.append("聊天输入中的未发送文字或图片")
	for key in _windows:
		var window = _windows[key]
		if is_instance_valid(window) and window.is_dirty():
			drafts.append("设置中的未保存修改" if key == "settings" else "动态发布或评论草稿")
	return drafts

func _show_close_dialog(action: String, settings: Variant, drafts: Array[String]) -> void:
	_log("runtime", "main", "close_dialog", "success", 0, action)
	_dialog.hide()
	var owner: Node = settings if action == "logout" and is_instance_valid(settings) else _host
	if _dialog.get_parent() != owner: _dialog.reparent(owner)
	_dialog.title = "退出应用前请确认" if action == "exit" else "退出登录前请确认"
	if drafts.is_empty():
		_dialog.dialog_text = "将结束本机登录。聊天记录和已保存的设置不会删除；未提交的内容不会自动保存。"
	else:
		_dialog.dialog_text = "以下内容尚未提交：\n• " + "\n• ".join(drafts) + "\n不会自动保存或发送。"
	_dialog.popup_centered()
	_dialog.get_cancel_button().grab_focus()

func _log(kind: String, route: String, action: String, outcome: String, duration_ms: int, reason: String = "") -> void:
	if _logger == null:
		return
	if kind == "access":
		Events.ui(_logger, route, action, duration_ms, outcome, action.to_upper())
	else:
		_logger.record_as("business", "window_state_changed", {"phase":action,
			"reason":reason if not reason.is_empty() else "window", "outcome":outcome,
			"action":action, "route":route})
