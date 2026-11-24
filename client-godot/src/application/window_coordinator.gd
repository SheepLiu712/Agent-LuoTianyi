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
var _chat_flush: Callable
var _chat_losses: Callable
var _logger: RefCounted
var _windows: Dictionary = {}
var _starters: Dictionary = {}
var _started: Dictionary = {}
var _action := ""
var _waiting_save := false
var _disposed := false

func _init(host: Control, dialog: Window, images: Node, geometry: Resource, settings_factory: Callable, dynamics_factory: Callable, chat_dirty: Callable, logger: RefCounted = null, chat_flush: Callable = Callable(), chat_losses: Callable = Callable()) -> void:
	_host = host
	_dialog = dialog
	_images = images
	_geometry = geometry
	_settings_factory = settings_factory
	_dynamics_factory = dynamics_factory
	_chat_dirty = chat_dirty
	_chat_flush = chat_flush
	_chat_losses = chat_losses
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
	_flush_drafts()
	var drafts := _collect_losses()
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
	_flush_drafts()
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
	_chat_flush = Callable()
	_chat_losses = Callable()

func _flush_drafts() -> void:
	if _chat_flush.is_valid():
		_chat_flush.call()
	for window in _windows.values():
		if is_instance_valid(window) and window.has_method("flush_drafts"):
			window.flush_drafts()


func _collect_losses() -> Array[String]:
	var drafts: Array[String] = []
	_append_chat_losses(drafts)
	for key in _windows:
		var window = _windows[key]
		if is_instance_valid(window):
			_append_window_losses(drafts, key, window)
	return drafts


func _append_chat_losses(drafts: Array[String]) -> void:
	if _chat_losses.is_valid():
		for item in _chat_losses.call():
			drafts.append(str(item))
	elif _chat_dirty.is_valid() and _chat_dirty.call():
		drafts.append("聊天输入中的未发送文字或图片")


func _append_window_losses(drafts: Array[String], key: String, window: Variant) -> void:
	if window.has_method("loss_warnings"):
		for item in window.loss_warnings():
			drafts.append(str(item))
	elif window.is_dirty():
		drafts.append("设置中的未保存修改" if key == "settings" else "动态发布或评论草稿")

func _show_close_dialog(action: String, settings: Variant, drafts: Array[String]) -> void:
	_log("runtime", "main", "close_dialog", "success", 0, action)
	_dialog.hide()
	var owner: Node = settings if action == "logout" and is_instance_valid(settings) else _host
	if _dialog.get_parent() != owner: _dialog.reparent(owner)
	if action == "logout":
		_dialog.title = "退出登录"
		_dialog.ok_button_text = "是"
		_dialog.cancel_button_text = "否"
		_dialog.dialog_text = "是否退出登录？" if drafts.is_empty() else "是否退出登录？\n\n以下内容尚未提交，退出后将丢失：\n• " + "\n• ".join(drafts)
	else:
		_dialog.title = "退出应用前请确认"
		_dialog.ok_button_text = "放弃并继续"
		_dialog.cancel_button_text = "返回继续编辑"
		_dialog.dialog_text = "以下内容尚未提交，退出后将丢失：\n• " + "\n• ".join(drafts)
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
