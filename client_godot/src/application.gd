extends Control
## Composition root: owns account services and keeps the offline preview separate.
const Api = preload("res://src/network/account_api.gd")
const Store = preload("res://src/storage/credential_store.gd")
const Session = preload("res://src/session/account_session.gd")
const Avatar = preload("res://src/avatar/avatar_panel.gd")
const Chat = preload("res://src/session/chat_session.gd")
const Transport = preload("res://src/network/websocket_transport.gd")
const ChatView = preload("res://src/ui/chat_view.gd")
const Log = preload("res://src/storage/client_log.gd")
const Cache = preload("res://src/storage/audio_cache.gd")
const Audio = preload("res://src/media/reply_audio.gd")
var _session: Node
var _chat: Node
var _chat_view: Control
@onready var _split: HSplitContainer = %Split
@onready var _center: CenterContainer = %Center
@onready var _account_form = %AccountForm
var _avatar: Control
var _ratio := 0.45
var _layout_ready := false
var _layout_path: String
var _expanded := false
var _expanded_size := Vector2i(1200, 800)
var _log: RefCounted
var _log_window: Window
var _engine_log: Logger
@onready var _log_problem: Label = %LogProblem
var _windows: Dictionary = {}
@onready var _exit_dialog: ConfirmationDialog = %ExitDialog
var _exit_action := ""
var _models: Node
var _executor: Node
var _dynamics: Node

func setup(account_session: Node = null, layout_path: String = "user://window_layout.cfg") -> void:
	_session = account_session
	_layout_path = layout_path


func _ready() -> void:
	get_window().title = preload("res://src/release_info.gd").title()
	if "--preview" in OS.get_cmdline_user_args():
		_log_problem.queue_free()
		_exit_dialog.queue_free()
		_resize_window(Vector2i(1200, 800), Vector2i(960, 640))
		add_child(load("res://scenes/chat_preview.tscn").instantiate())
		return
	_resize_window(Vector2i(660, 800), Vector2i(480, 640))
	_log = Log.new("user://logs" if _layout_path == "user://window_layout.cfg" else _layout_path.get_base_dir().path_join("logs"))
	_log.write_failed.connect(func(_error): _log_problem.text = "日志保存失败，打开日志可查看本次内存记录；磁盘归档可能不完整。")
	_log.record("client_started")
	_engine_log = preload("res://src/storage/engine_log_sink.gd").new(_log)
	OS.add_logger(_engine_log)
	_log_window = preload("res://src/ui/log_window.gd").new(_log)
	add_child(_log_window)
	get_tree().auto_accept_quit = false
	get_window().close_requested.connect(func(): _request_close("exit"))
	_exit_dialog.confirmed.connect(func(): _finish_close(_exit_action))
	_exit_dialog.canceled.connect(func(): _exit_action = "")
	if not ClassDB.class_exists("WindowsSecurity"):
		var error := Label.new()
		error.text = "凭据保护组件缺失，请重新解压完整程序。"
		add_child(error)
		push_error("WindowsSecurity extension missing")
		return
	if _session == null:
		var security = ClassDB.instantiate("WindowsSecurity")
		_session = Session.new(Api.new(security), Store.new(security))
	add_child(_session)
	_models = preload("res://src/session/model_settings.gd").new(preload("res://src/network/json_request.gd").new(),preload("res://src/storage/model_store.gd").new(ClassDB.instantiate("WindowsSecurity"),_layout_path.get_base_dir().path_join("models")),_log)
	add_child(_models)
	_dynamics = preload("res://src/session/dynamics_controller.gd").new(_log)
	add_child(_dynamics)
	_dynamics.unread_changed.connect(func(count):
		if _chat_view != null:
			_chat_view.set_dynamics_unread(count))
	var cache = Cache.new(_layout_path.get_base_dir().path_join("audio"),_log)
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
		_ratio = _avatar.size.x / maxf(size.x, 1)
		settings.set_value("layout", "ratio", _ratio)
		if settings.save(_layout_path) != OK:
			push_warning("Window layout save failed"))
	resized.connect(_resize_split)
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
		if _avatar == null:
			_avatar = Avatar.new()
			_avatar.custom_minimum_size.x = 290
			_split.add_child(_avatar)
			_split.move_child(_avatar, 0)
		_avatar.show()
		_avatar.process_mode = Node.PROCESS_MODE_INHERIT
		if _chat_view == null:
			_chat_view = ChatView.new(_chat)
			_chat_view.custom_minimum_size.x = 440
			_chat_view.size_flags_horizontal = Control.SIZE_EXPAND_FILL
			_split.add_child(_chat_view)
			_chat_view.logout_requested.connect(func(): _request_close("logout"))
			_chat_view.log_requested.connect(_log_window.open)
			_chat_view.settings_requested.connect(_open_settings)
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
		if _expanded:
			if get_window().mode == Window.MODE_WINDOWED:
				_expanded_size = get_window().size
			_expanded = false
			_split.dragger_visibility = SplitContainer.DRAGGER_HIDDEN_COLLAPSED
			_resize_window(Vector2i(660, 800), Vector2i(480, 640))
	_resize_split()

func _resize_split() -> void:
	if _layout_ready and _expanded:
		_split.split_offset = roundi(size.x * _ratio)

func _resize_window(target: Vector2i, minimum: Vector2i) -> void:
	var window := get_window()
	var center := window.position + window.size / 2
	window.mode = Window.MODE_WINDOWED
	window.min_size = minimum
	window.size = target
	if DisplayServer.get_name() != "headless":
		var usable := DisplayServer.screen_get_usable_rect(window.current_screen)
		var origin := center - window.size / 2
		origin.x = clampi(origin.x, usable.position.x, maxi(usable.position.x, usable.end.x - window.size.x))
		origin.y = clampi(origin.y, usable.position.y, maxi(usable.position.y, usable.end.y - window.size.y))
		window.position = origin

func _exit_tree() -> void:
	if _engine_log != null:
		OS.remove_logger(_engine_log)
		_engine_log.stop()
	if _log != null:
		_log.finish()

func _open_settings(kind: String) -> void:
	if _windows.has(kind) and is_instance_valid(_windows[kind]):
		_windows[kind].open()
		return
	if kind not in ["preferences","models","dynamics"]:
		return
	var controller: Node
	var window: Window
	if kind == "preferences":
		controller = preload("res://src/session/preferences_controller.gd").new(preload("res://src/network/json_request.gd").new(),_log)
		window = load("res://scenes/ui/preferences_window.tscn").instantiate() as Window
		window.setup(controller)
	elif kind == "models":
		window = load("res://scenes/ui/model_window.tscn").instantiate() as Window
		window.setup(_models,_executor)
		if _models.get_state().phase == "error":
			_models.start(_session.get_session())
	else:
		window = preload("res://src/ui/dynamics_window.gd").new(_dynamics,_layout_path.get_base_dir().path_join("dynamics-window.cfg"))
	_windows[kind] = window
	add_child(window)
	window.tree_exited.connect(func():
		if _windows.get(kind) == window:
			_windows.erase(kind))
	window.open()
	if controller != null:
		controller.start(_session.get_session())

func _request_close(action: String) -> void:
	for window in _windows.values():
		if is_instance_valid(window) and window.is_dirty():
			_exit_action = action
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
	for window in _windows.values():
		if is_instance_valid(window):
			window.hide()
			window.queue_free()
	_windows.clear()
