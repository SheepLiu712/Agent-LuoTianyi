extends Control
@export var appearance: Resource = preload("res://src/extensions/appearance_service.gd").new()
@export var world: Resource = preload("res://src/extensions/world_service.gd").new()
@export var devices: Resource = preload("res://src/extensions/device_service.gd").new()
@export var decoder_factory: Resource = preload("res://src/media/decoder_factory.gd").new()
@export var secret_protection: Resource = preload("res://src/platform/secret_protection.gd").new()
@export var password_encryption: Resource = preload("res://src/platform/password_encryption.gd").new()
@export var window_system: Resource = preload("res://src/platform/window_system.gd").new()
@export var runtime: Resource = preload("res://src/platform/runtime_environment.gd").new()
const Services = preload("res://src/composition/application_services.gd")
var _services: RefCounted
var _lifecycle: RefCounted
var _coordinator: RefCounted
## Application view: owns account services and keeps the offline preview separate.
const Avatar = preload("res://scenes/avatar/avatar_panel.tscn")
const ChatView = preload("res://scenes/ui/chat_view.tscn")
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
var _geometry: Resource
var _layout_path := "user://window_layout.cfg"
var _expanded := false
var _expanded_size := Vector2i(1200, 800)
var _log: RefCounted
var _log_window: Window
var _engine_log: Logger
@onready var _log_problem: Label = %LogProblem
@onready var _exit_dialog: Window = %ExitDialog
var _models: Node
var _images_presenter: Node
var _dynamics: Node
var _external_links: RefCounted

func setup(account_session: Node = null, layout_path: String = "user://window_layout.cfg", external_links: RefCounted = null) -> void:
	_session = account_session
	_layout_path = layout_path
	_external_links = external_links


func _ready() -> void:
	get_window().title = preload("res://src/storage/release_info.gd").title()
	_geometry = Services.create_geometry(_layout_path)
	_chrome.configure(_geometry,"login")
	if "--preview" in runtime.arguments():
		_log_problem.queue_free()
		_exit_dialog.queue_free()
		_resize_window(Vector2i(1200, 800), Vector2i(960, 640))
		var preview = load("res://scenes/preview/chat_preview.tscn").instantiate()
		add_child(preview)
		preview.offset_top = 0
		move_child(_chrome,get_child_count()-1)
		return
	_resize_window(Vector2i(480, 690), Vector2i(360, 480))
	_images_presenter = preload("res://src/ui/image_presenter.gd").new(_geometry,window_system)
	add_child(_images_presenter)
	_services = Services.new(_layout_path,runtime)
	_log = _services.log
	_log.write_failed.connect(func(_error): _log_problem.text = "日志保存失败，打开日志可查看本次内存记录；磁盘归档可能不完整。")
	_log.record("client_started")
	_engine_log = preload("res://src/storage/engine_log_sink.gd").new(_log)
	runtime.register_logger(_engine_log)
	_log_window = preload("res://scenes/ui/log_window.tscn").instantiate() as Window
	_log_window.setup(_log)
	add_child(_log_window)
	_log_window.get_node("%Chrome").configure(_geometry,"logs")
	get_tree().auto_accept_quit = false
	get_window().close_requested.connect(func(): _request_close("exit"))
	_coordinator = preload("res://src/application/window_coordinator.gd").new(self,_exit_dialog,_images_presenter,_geometry,_services.create_settings,_services.create_dynamics,func(): return is_instance_valid(_chat_view) and _chat_view.is_dirty())
	_coordinator.exit_requested.connect(func():
		if is_instance_valid(_session): _session.cancel()
		get_tree().quit())
	_coordinator.logout_requested.connect(func(): _session.logout())
	_account_form.log_requested.connect(_log_window.open)
	_account_form.exit_requested.connect(func(): _request_close("exit"))
	if _external_links == null: _external_links = Services.external_links()
	_account_form.feedback_requested.connect(func(): _account_form.report_feedback_result(_external_links.open_project()))
	if not password_encryption.is_available():
		%SecurityError.show()
		%SecurityError.text = "认证加密组件不可用，暂时无法登录；日志和问题反馈仍可使用。"
		return
	_services.mount(self,_session,_layout_path,password_encryption,secret_protection,decoder_factory)
	_session = _services.account
	_models = _services.models
	_dynamics = _services.dynamics
	_chat = _services.chat
	_lifecycle = preload("res://src/application/account_lifecycle.gd").new(_chat,_models,_dynamics,appearance,world,devices)
	_dynamics.unread_changed.connect(func(count):
		if is_instance_valid(_nav_dynamics):
			_nav_dynamics.text = "动态" if count <= 0 else "动态 · " + ("99+" if count > 99 else str(count)))
	%NavChat.pressed.connect(func(): %NavChat.button_pressed = true; _chrome.open_window())
	%NavDynamics.pressed.connect(func(): _open_settings("dynamics"))
	%NavSettings.pressed.connect(func(): _open_settings("settings"))
	%NavLogs.pressed.connect(_log_window.open)
	_chat.expression_requested.connect(func(command):
		if _avatar != null:
			_avatar.avatar.apply_expression(command))
	_chat.mouth_changed.connect(func(value):
		if _avatar != null:
			_avatar.avatar.set_mouth_openness(value))
	_split.show()
	_account_form.setup(_session)
	_session.changed.connect(_account_changed)
	var settings: Resource = _services.settings
	if settings.load_settings() == OK:
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
			if settings.save_settings() != OK:
				push_warning("Audio volume save failed"))
	_split.dragged.connect(func(_offset):
		if not _expanded:
			return
		_ratio = _avatar.size.x / maxf(_split.size.x, 1)
		settings.set_value("layout", "ratio", _ratio)
		if settings.save_settings() != OK:
			push_warning("Window layout save failed"))
	_split.resized.connect(_resize_split)
	await get_tree().process_frame
	_layout_ready = true
	_resize_split()
	var capture := ""
	for argument in runtime.arguments():
		if argument.begins_with("--capture="):
			capture = argument.trim_prefix("--capture=")
	if not capture.is_empty():
		await get_tree().create_timer(1.0).timeout
		await RenderingServer.frame_post_draw
		var saved: Error = runtime.capture(get_viewport(),capture)
		get_tree().quit(0 if saved == OK else 1)
	elif not runtime.is_headless():
		_session.resume()

func _account_changed(state: Dictionary) -> void:
	_log.record("account_state", {"phase":state.phase,"code":"STORAGE_ERROR" if state.storage_error else state.code})
	%AccountStorageWarning.visible = state.storage_error and state.phase == "signed_in"
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
		_lifecycle.start(_session.get_session())
	else:
		_coordinator.close_all()
		_lifecycle.stop()
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
			if window_system.windowed(get_window()):
				_expanded_size = window_system.geometry(get_window()).size
			_expanded = false
			_split.dragger_visibility = SplitContainer.DRAGGER_HIDDEN_COLLAPSED
			_resize_window(Vector2i(480, 690), Vector2i(360, 480))
	_resize_split()

func _resize_split() -> void:
	if _layout_ready and _expanded:
		_split.split_offset = roundi(_split.size.x * _ratio)

func _resize_window(target: Vector2i, minimum: Vector2i) -> void:
	var expanded: bool = _expanded or "--preview" in runtime.arguments()
	_chrome.set_login_mode(not expanded)
	%Background.visible = expanded
	_chrome.select_layout("expanded" if expanded else "login",target,minimum)

func _exit_tree() -> void:
	if _coordinator != null: _coordinator.dispose()
	if _lifecycle != null: _lifecycle.stop()
	if _engine_log != null:
		runtime.unregister_logger(_engine_log)
		_engine_log.stop()
	if _log != null:
		_log.finish()

func _open_settings(kind: String) -> void:
	_coordinator.open(kind)

func _request_close(action: String) -> void:
	if _coordinator != null: _coordinator.request_close(action)
