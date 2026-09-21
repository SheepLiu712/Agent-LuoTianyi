extends Control
const StorageService = preload("res://src/storage/storage_service.gd")
var _storage_service: StorageService
var _audio_cache: RefCounted
## Composition root: owns account services and keeps the offline preview separate.
const Api = preload("res://src/network/account_api.gd")
const Store = preload("res://src/storage/credential_store.gd")
const Session = preload("res://src/session/account_session.gd")
const Avatar = preload("res://scenes/avatar/avatar_panel.tscn")
const Chat = preload("res://src/session/chat_session.gd")
const Transport = preload("res://src/network/websocket_transport.gd")
const ChatView = preload("res://scenes/ui/chat_view.tscn")
const Log = preload("res://src/storage/client_log.gd")
const Cache = preload("res://src/storage/audio_cache.gd")
const Audio = preload("res://src/media/reply_audio.gd")
var _session: Node
var _chat: Node
var _chat_view: Control
@onready var _chrome = %Chrome
@onready var _split: HSplitContainer = %Split
@onready var _center: MarginContainer = %Center
@onready var _account_form = %AccountForm
@onready var _nav_dynamics: Button = %NavDynamics
var _avatar: Control
var _ratio := 0.45
var _layout_ready := false
var _layout_path := "user://window_layout.cfg"
var _expanded := false
var _expanded_size := Vector2i(1200, 800)
var _log: RefCounted
var _log_window: Window
var _engine_log: Logger
@onready var _log_problem: Label = %LogProblem
var _windows: Dictionary = {}
@onready var _exit_dialog: Window = %ExitDialog
var _exit_action := ""
var _waiting_save := false
var _models: Node
var _images_presenter: Node
var _executor: Node
var _dynamics: Node

func setup(account_session: Node = null, layout_path: String = "user://window_layout.cfg") -> void:
	_session = account_session
	_layout_path = layout_path


func _ready() -> void:
	get_window().title = preload("res://src/release_info.gd").title()
	get_window().min_size = Vector2i(480,640)
	get_window().size = Vector2i(660,800)
	_chrome.configure(_layout_path.get_base_dir().path_join("window-geometry.cfg"),"compact")
	if "--preview" in OS.get_cmdline_user_args():
		_log_problem.queue_free()
		_exit_dialog.queue_free()
		_resize_window(Vector2i(1200, 800), Vector2i(960, 640))
		var preview = load("res://scenes/preview/chat_preview.tscn").instantiate()
		add_child(preview)
		preview.offset_top = 0
		move_child(_chrome,get_child_count()-1)
		return
	_resize_window(Vector2i(660, 800), Vector2i(480, 640))
	_images_presenter = preload("res://src/ui/image_presenter.gd").new(_layout_path.get_base_dir().path_join("window-geometry.cfg"))
	add_child(_images_presenter)
	_log = Log.new("user://logs" if _layout_path == "user://window_layout.cfg" else _layout_path.get_base_dir().path_join("logs"))
	_log.write_failed.connect(func(_error): _log_problem.text = "日志保存失败，打开日志可查看本次内存记录；磁盘归档可能不完整。")
	_log.record("client_started")
	_engine_log = preload("res://src/storage/engine_log_sink.gd").new(_log)
	OS.add_logger(_engine_log)
	_log_window = preload("res://scenes/ui/log_window.tscn").instantiate() as Window
	_log_window.setup(_log)
	add_child(_log_window)
	_log_window.get_node("%Chrome").configure(_layout_path.get_base_dir().path_join("window-geometry.cfg"),"logs")
	get_tree().auto_accept_quit = false
	get_window().close_requested.connect(func(): _request_close("exit"))
	_exit_dialog.confirmed.connect(func(): _finish_close(_exit_action))
	_exit_dialog.canceled.connect(func():
		_exit_action = ""
		_return_exit_dialog())
	if not ClassDB.class_exists("WindowsSecurity"):
		%SecurityError.show()
		push_error("WindowsSecurity extension missing")
		return
	var security = ClassDB.instantiate("WindowsSecurity")
	var data_root := _layout_path.get_base_dir()
	_storage_service = preload("res://src/storage/godot_storage_service.gd").new(data_root.path_join("account.cfg"), Store.new(security, data_root.path_join("accounts")))
	if _session == null:
		_session = Session.new(Api.new(security), _storage_service)
	add_child(_session)
	_models = preload("res://src/session/model_settings.gd").new(preload("res://src/network/json_request.gd").new(),preload("res://src/storage/model_store.gd").new(ClassDB.instantiate("WindowsSecurity"),_layout_path.get_base_dir().path_join("models")),_log)
	add_child(_models)
	_dynamics = preload("res://src/session/dynamics_controller.gd").new(_log)
	add_child(_dynamics)
	_dynamics.unread_changed.connect(func(count):
		if is_instance_valid(_nav_dynamics):
			_nav_dynamics.text = "动态" if count <= 0 else "动态 · " + ("99+" if count > 99 else str(count)))
	%NavChat.pressed.connect(func(): %NavChat.button_pressed = true; _chrome.open_window())
	%NavDynamics.pressed.connect(func(): _open_settings("dynamics"))
	%NavSettings.pressed.connect(func(): _open_settings("settings"))
	%NavLogs.pressed.connect(_log_window.open)
	var cache = Cache.new(_layout_path.get_base_dir().path_join("audio"),_log)
	_audio_cache = cache
	var history = preload("res://src/session/history_sync.gd").new(preload("res://src/network/history_api.gd").new(),_log)
	var reading = preload("res://src/storage/reading_position.gd").new(_layout_path.get_base_dir().path_join("reading"))
	var images = preload("res://src/storage/history_images.gd").new(_layout_path.get_base_dir().path_join("images"),_log)
	_executor = preload("res://src/session/model_executor.gd").new(_models,_log)
	_chat = Chat.new(Transport.new(), _log, Audio.new(_log,Callable(),cache),history,reading,images,_executor)
	add_child(_chat)
	_chat.expression_requested.connect(func(command):
		if _avatar != null:
			_avatar.avatar.apply_expression(command))
	_chat.mouth_changed.connect(func(value):
		if _avatar != null:
			_avatar.avatar.set_mouth_openness(value))
	_split.show()
	_account_form.setup(_session)
	_account_form.log_requested.connect(_log_window.open)
	_session.changed.connect(_account_changed)
	var settings := ConfigFile.new()
	if settings.load(_layout_path) == OK:
		var ratio: Variant = settings.get_value("layout", "ratio", 0.45)
		if (ratio is float or ratio is int) and is_finite(float(ratio)):
			_ratio = clampf(float(ratio), 0.3, 0.6)
		var volume: Variant = settings.get_value("audio", "volume", 1.0)
		if (volume is float or volume is int) and is_finite(float(volume)) and volume >= 0 and volume <= 1:
			_chat.set_volume(float(volume))
	_chat.state_changed.connect(func(_state):
		var volume: float = _chat.get_audio_state().volume
		if settings.get_value("audio", "volume", 1.0) != volume:
			settings.set_value("audio", "volume", volume)
			if settings.save(_layout_path) != OK:
				push_warning("Audio volume save failed"))
	_split.dragged.connect(func(_offset):
		if not _expanded:
			return
		_ratio = _avatar.size.x / maxf(_split.size.x, 1)
		settings.set_value("layout", "ratio", _ratio)
		if settings.save(_layout_path) != OK:
			push_warning("Window layout save failed"))
	_split.resized.connect(_resize_split)
	await get_tree().process_frame
	_layout_ready = true
	_resize_split()
	var capture := ""
	for argument in OS.get_cmdline_user_args():
		if argument.begins_with("--capture="):
			capture = argument.trim_prefix("--capture=")
	if not capture.is_empty():
		await get_tree().create_timer(1.0).timeout
		await RenderingServer.frame_post_draw
		var saved := get_viewport().get_texture().get_image().save_png(capture)
		get_tree().quit(0 if saved == OK else 1)
	elif DisplayServer.get_name() != "headless":
		_session.resume()

func _account_changed(state: Dictionary) -> void:
	_log.record("account_state", {"phase":state.phase,"code":state.code})
	if state.phase == "signed_in":
		_center.hide()
		%Navigation.show()
		if _avatar == null:
			_avatar = Avatar.instantiate() as Control
			_avatar.touched.connect(_chat.record_touch)
			_avatar.custom_minimum_size.x = 290
			_split.add_child(_avatar)
			_split.move_child(_avatar, 0)
		_avatar.show()
		_avatar.process_mode = Node.PROCESS_MODE_INHERIT
		if _chat_view == null:
			_chat_view = ChatView.instantiate() as Control
			_chat_view.setup(_chat)
			_chat_view.custom_minimum_size.x = 440
			_chat_view.size_flags_horizontal = Control.SIZE_EXPAND_FILL
			_split.add_child(_chat_view)
			_chat_view.image_requested.connect(func(provider): _images_presenter.open_image(get_window(),provider))
			_chat_view.attachment_requested.connect(func(provider,confirm): _images_presenter.open_image(get_window(),provider,confirm))
			_chat_view.attachment_cleared.connect(func(): _images_presenter.close_confirmation(get_window()))
		if not _expanded:
			_expanded = true
			_split.dragger_visibility = SplitContainer.DRAGGER_VISIBLE
			_resize_window(_expanded_size, Vector2i(960, 640))
		_chat.start(_session.get_session())
		_models.start(_session.get_session())
		_dynamics.start(_session.get_session())
	else:
		_close_windows()
		_models.stop()
		_dynamics.stop()
		_chat.stop()
		if _chat_view != null:
			_chat_view.hide()
			_chat_view.queue_free()
			_chat_view = null
		if _avatar != null:
			_avatar.hide()
			_avatar.queue_free()
			_avatar = null
		_center.show()
		%Navigation.hide()
		if _expanded:
			if get_window().mode == Window.MODE_WINDOWED:
				_expanded_size = get_window().size
			_expanded = false
			_split.dragger_visibility = SplitContainer.DRAGGER_HIDDEN_COLLAPSED
			_resize_window(Vector2i(660, 800), Vector2i(480, 640))
	_resize_split()

func _resize_split() -> void:
	if _layout_ready and _expanded:
		_split.split_offset = roundi(_split.size.x * _ratio)

func _resize_window(target: Vector2i, minimum: Vector2i) -> void:
	_chrome.select_layout("expanded" if _expanded or "--preview" in OS.get_cmdline_user_args() else "compact",target,minimum)

func _exit_tree() -> void:
	if _engine_log != null:
		OS.remove_logger(_engine_log)
		_engine_log.stop()
	if _log != null:
		_log.finish()

func _open_settings(kind: String) -> void:
	if kind not in ["dynamics","settings"]: return
	var key := kind
	if _windows.has(key) and is_instance_valid(_windows[key]):
		_windows[key].open()
		return
	var controller: Node
	var window: Window
	if key == "settings":
		controller = preload("res://src/session/preferences_controller.gd").new(preload("res://src/network/json_request.gd").new(),_log)
		window = preload("res://scenes/ui/settings_window.tscn").instantiate()
		window.setup(controller,_models,_executor,_chat.clear_cache,_storage_service,_audio_cache.get_directory())
		window.logout_requested.connect(func(): _request_close("logout"))
	else:
		window = preload("res://scenes/ui/dynamics_window.tscn").instantiate()
		window.setup(_dynamics,_layout_path.get_base_dir().path_join("dynamics-window.cfg"))
	_windows[key] = window
	add_child(window)
	window.get_node("%Chrome").configure(_layout_path.get_base_dir().path_join("window-geometry.cfg"),key)
	window.tree_exited.connect(func():
		if _windows.get(key) == window: _windows.erase(key))
	window.open()
	if controller != null: controller.start(_session.get_session())

func _request_close(action: String) -> void:
	if action not in ["exit","logout"]: return
	var settings = _windows.get("settings")
	if is_instance_valid(settings) and settings.is_saving():
		_exit_action = action
		if not _waiting_save:
			_waiting_save = true
			settings.saving_finished.connect(func(_ok):
				_waiting_save = false
				_request_close(_exit_action),CONNECT_ONE_SHOT)
		return
	var drafts: Array[String] = []
	if is_instance_valid(_chat_view) and _chat_view.is_dirty(): drafts.append("聊天输入中的未发送文字或图片")
	for key in _windows:
		var window = _windows[key]
		if is_instance_valid(window) and window.is_dirty():
			drafts.append("设置中的未保存修改" if key == "settings" else "动态发布或评论草稿")
	if not drafts.is_empty():
		_exit_action = action
		_exit_dialog.hide()
		var host: Node = settings if action == "logout" and is_instance_valid(settings) else self
		if _exit_dialog.get_parent() != host:
			_exit_dialog.reparent(host)
		_exit_dialog.title = "退出应用前请确认" if action == "exit" else "退出登录前请确认"
		_exit_dialog.dialog_text = "以下内容尚未提交：\n• " + "\n• ".join(drafts) + "\n不会自动保存或发送。"
		_exit_dialog.popup_centered()
		_exit_dialog.get_cancel_button().grab_focus()
		return
	_finish_close(action)

func _finish_close(action: String) -> void:
	if action not in ["exit","logout"]:
		return
	_close_windows()
	_exit_action = ""
	if action == "exit":
		get_tree().quit()
	else:
		_session.logout()

func _close_windows() -> void:
	_return_exit_dialog()
	if _images_presenter != null: _images_presenter.close()
	for window in _windows.values():
		if is_instance_valid(window):
			window.hide()
			window.queue_free()
	_windows.clear()

func _return_exit_dialog() -> void:
	_exit_dialog.hide()
	if _exit_dialog.get_parent() != self:
		_exit_dialog.reparent(self)
