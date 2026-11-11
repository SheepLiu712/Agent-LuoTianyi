extends Control
## 应用根视图：持有账户会话与窗口协调器，负责登录/展开两种窗口形态与子窗口装配。

@export var appearance: Resource = preload("res://src/extensions/appearance_service.gd").new()
@export var world: Resource = preload("res://src/extensions/world_service.gd").new()
@export var devices: Resource = preload("res://src/extensions/device_service.gd").new()
@export var decoder_factory: Resource = preload("res://src/media/decoder_factory.gd").new()
@export var secret_protection: Resource = preload("res://src/platform/secret_protection.gd").new()
@export var password_encryption: Resource = preload("res://src/platform/password_encryption.gd").new()
@export var window_system: Resource = preload("res://src/platform/window_system.gd").new()
@export var runtime: Resource = preload("res://src/platform/runtime_environment.gd").new()

const Services = preload("res://src/composition/application_services.gd")
const AccountScope = preload("res://src/domain/account_scope.gd")
const LogSchema = preload("res://src/storage/log_schema.gd")
const LogEvents = preload("res://src/storage/log_events.gd")
const ErrorDialog = preload("res://src/ui/error_dialog.gd")
## 导航节点 → 图标名。按图标语义而非节点名映射：NavDynamics 用 @（动态/提及），NavLogs 用卷宗（日志归档）。
const NAV_ICONS := {"NavChat":"nav_chat", "NavDynamics":"nav_at", "NavSettings":"nav_settings", "NavLogs":"nav_scroll"}
const Avatar = preload("res://scenes/avatar/avatar_panel.tscn")
const ChatView = preload("res://scenes/ui/chat_view.tscn")

var _services: RefCounted
var _lifecycle: RefCounted
var _coordinator: RefCounted
var _session: Node
var _chat: Node
var _chat_view: Control

@onready var _chrome = %Chrome
@onready var _split: HSplitContainer = %Split
@onready var _center: MarginContainer = %Center
@onready var _account_form = %AccountForm
@onready var _nav_dynamics: Button = %NavDynamics
@onready var _dynamics_unread: Control = %DynamicsUnread

var _avatar: Control

var _closing := false
var _ratio := 1.0 / 3.0
var _layout_ready := false
var _geometry: Resource
var _layout_path := "user://window_layout.cfg"
var _expanded := false
var _expanded_size := Vector2i(1280, 800)

var _log: RefCounted
var _log_window: Window
var _engine_log: Logger
var _started_usec := Time.get_ticks_usec()
var _started_msec := Time.get_ticks_msec()
var _perf_timer: Timer
var _last_summary_seq := 0

@onready var _log_problem: Label = %LogProblem
@onready var _exit_dialog: Window = %ExitDialog

var _models: Node
var _images_presenter: Node
var _dynamics: Node
var _external_links: RefCounted

## 注入外部依赖：账户会话、布局保存路径、外部链接服务。
## 由上层在实例化后调用。
func setup(account_session: Node = null, layout_path: String = "user://window_layout.cfg", external_links: RefCounted = null) -> void:
	_session = account_session
	_layout_path = layout_path
	_external_links = external_links


## 应用视图初始化入口。
## 负责窗口标题、几何、预览模式、服务组装、日志、协调器、账户表单、设置恢复、截图与恢复会话。
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
	_services.ui_style.apply_view(self, NAV_ICONS)
	_services.ui_style.style_changed.connect(_apply_workspace_style)
	_apply_workspace_style()
	_images_presenter.set_ui_style(_services.ui_style)
	_log = _services.log
	ErrorDialog.set_logger(_log)
	_log.write_failed.connect(func(error): push_warning("Client log write failed: %s" % error))
	_log.ensure_ready()
	_log.record("runtime_app_started", {"phase":"starting", "reason":"normal", "uptime_ms":0, "pid":runtime.process_id()})
	_log_previous_incomplete()
	_record_startup_phase("services_ready")

	_engine_log = preload("res://src/storage/engine_log_sink.gd").new(_log)
	runtime.register_logger(_engine_log)

	_log_window = preload("res://scenes/ui/log_window.tscn").instantiate() as Window
	_log_window.setup(_log)
	_services.ui_style.apply_view(_log_window, {"CopyButton":"action_copy", "ExportButton":"action_export"})
	add_child(_log_window)
	_log_window.get_node("%Chrome").configure(_geometry,"logs")
	_record_startup_phase("log_window_ready")

	get_tree().auto_accept_quit = false
	get_window().close_requested.connect(func(): _request_close("exit"))

	_coordinator = preload("res://src/application/window_coordinator.gd").new(self,_exit_dialog,_images_presenter,_geometry,_services.create_settings,_services.create_dynamics,func(): return is_instance_valid(_chat_view) and _chat_view.is_dirty(),_log)
	_coordinator.exit_requested.connect(func(): _request_persisted_close("exit"))
	_coordinator.logout_requested.connect(func(): _request_persisted_close("logout"))

	_account_form.log_requested.connect(func(): _log_ui("logs", _log_window.open))

	if _external_links == null: _external_links = Services.external_links()
	_account_form.feedback_requested.connect(func(): _account_form.report_feedback_result(_external_links.open_project()))

	if not password_encryption.is_available():
		_log.log_security("security_component", {"action":"check", "outcome":"failure", "reason_code":"SECURITY_UNAVAILABLE",
			"subject":LogSchema.hash_subject("", "system"), "channel":"app", "detail":"认证加密组件不可用"})
		%SecurityError.show()
		%SecurityError.text = "账号与聊天功能暂不可用"
		call_deferred("_present_security_error")
		return

	_services.mount(self,_session,_layout_path,password_encryption,secret_protection,decoder_factory)
	_record_startup_phase("account_mounted")
	_session = _services.account
	_models = _services.models
	_dynamics = _services.dynamics
	_chat = _services.chat

	_lifecycle = preload("res://src/application/account_lifecycle.gd").new(_chat,_models,_dynamics,appearance,world,devices,_services.avatar,_log)

	_dynamics.unread_changed.connect(func(count):
		if is_instance_valid(_nav_dynamics) and is_instance_valid(_dynamics_unread):
			_dynamics_unread.visible = count > 0
			_nav_dynamics.tooltip_text = "动态" if count <= 0 else "动态 · %s 条未读" % count)
	_dynamics.latest_unread_changed.connect(func(post):
		if is_instance_valid(_avatar): _avatar.set_unread_dynamic(post))

	%NavChat.pressed.connect(func(): _log_ui("chat", func(): %NavChat.button_pressed = true; _chrome.open_window()))
	%NavDynamics.pressed.connect(func(): _open_settings("dynamics"))
	%NavSettings.pressed.connect(func(): _open_settings("settings"))
	%NavLogs.pressed.connect(func(): _log_ui("logs", _log_window.open))

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
	_restore_settings(settings)
	_chat.state_changed.connect(func(_state):
		var volume: float = _chat.get_audio_state().volume
		if settings.get_value("audio", "volume", 1.0) != volume:
			settings.set_value("audio", "volume", volume)
			if settings.save_settings() != OK:
				_log.log_warning("warning_settings_save", {"code":"SETTINGS_SAVE_FAILED", "detail":"音频音量保存失败", "phase":"failed"}))

	_split.dragged.connect(func(_offset):
		if not _expanded:
			return
		_ratio = _avatar.size.x / maxf(_split.size.x, 1)
		settings.set_value("layout", "ratio", _ratio)
		if settings.save_settings() != OK:
			_log.log_warning("warning_settings_save", {"code":"SETTINGS_SAVE_FAILED", "detail":"窗口布局保存失败", "phase":"failed"}))

	_split.resized.connect(_resize_split)

	await get_tree().process_frame
	_record_startup_phase("first_frame")
	_layout_ready = true
	_resize_split()
	_start_performance_sampling()

	await _capture_or_resume()


## 账户状态变化回调。
## 登录成功后创建头像与聊天视图、展开窗口并启动账户生命周期；
## 登出后关闭子窗口、释放视图并恢复登录态窗口。
func _present_security_error() -> void:
	ErrorDialog.present(self, "程序文件不完整，无法启动账号与聊天功能。请重新解压或重新安装；日志和问题反馈仍可使用。")

func _account_changed(state: Dictionary) -> void:
	_log.record("runtime_account_state", {"phase":state.phase,"code":"STORAGE_ERROR" if state.storage_error else state.code,
		"reason":"account", "uptime_ms":Time.get_ticks_msec() - _started_msec, "pid":runtime.process_id()})
	# 本地登录状态写入失败时保留页内警告；下一个没有 storage_error 的状态再收起。
	%AccountStorageWarning.visible = bool(state.get("storage_error", false))

	if state.phase == "signed_in":
		_center.hide()
		%Navigation.show()

		if _avatar == null:
			_avatar = Avatar.instantiate() as Control
			_avatar.set_ui_style(_services.ui_style)
			_avatar.touched.connect(_chat.record_touch)
			_avatar.dynamic_requested.connect(_open_dynamic_post)
			_avatar.custom_minimum_size.x = 290
			_split.add_child(_avatar)
			_split.move_child(_avatar, 0)
		_avatar.show()
		_avatar.set_unread_dynamic(_dynamics.get_latest_unread())
		_avatar.process_mode = Node.PROCESS_MODE_INHERIT

		if _chat_view == null:
			_chat_view = ChatView.instantiate() as Control
			_chat_view.set_ui_style(_services.ui_style)
			_chat_view.setup(_chat)
			_chat_view.custom_minimum_size.x = 440
			_chat_view.size_flags_horizontal = Control.SIZE_EXPAND_FILL
			_split.add_child(_chat_view)
			_chat_view.image_requested.connect(func(provider): _images_presenter.open_image(get_window(),provider))
			_chat_view.attachment_requested.connect(func(provider,confirm): _images_presenter.open_image(get_window(),provider,confirm))
			_chat_view.attachment_cleared.connect(func(): _images_presenter.close_confirmation(get_window()))
			_bind_composer_height(_chat_view)

		if not _expanded:
			_expanded = true
			_split.dragger_visibility = SplitContainer.DRAGGER_VISIBLE
			_resize_window(_expanded_size, Vector2i(960, 640))

		var lifecycle_result: Error = _lifecycle.start(_session.get_session())
		if lifecycle_result != OK:
			_log.record("runtime_account_state", {"phase":"signed_out", "code":"ACCOUNT_START_FAILED", "reason":"account_start_failed",
				"uptime_ms":Time.get_ticks_msec() - _started_msec, "pid":runtime.process_id()})
			_session.logout()
			return

	else:
		_show_signed_out()
	_resize_split()


## 按当前比例调整左右分栏偏移。
func _resize_split() -> void:
	if not _layout_ready or not _expanded or not is_instance_valid(_avatar) or not is_instance_valid(_chat_view):
		return
	var available := _split.size.x
	if available <= 1:
		return
	var separation := float(_split.get_theme_constant("separation"))
	var left_min := _avatar.get_combined_minimum_size().x
	var right_min := _chat_view.get_combined_minimum_size().x
	var max_left := maxf(left_min, available - right_min - separation)
	_split.split_offset = roundi(clampf(available * _ratio, left_min, max_left))

func _apply_workspace_style() -> void:
	var style: RefCounted = _services.ui_style
	var rail := %Navigation.get_theme_stylebox("panel") as StyleBoxFlat
	rail.bg_color = Color(0.94, 0.975, 1, 0.65) if style.is_crystal() else Color(0.941, 0.965, 0.98, 1)
	rail.border_color = Color(1, 1, 1, 0.7) if style.is_crystal() else Color(0.878, 0.914, 0.941, 1)
	var backdrop := %Background.texture as GradientTexture2D
	backdrop.gradient.colors = PackedColorArray([Color(0.86, 0.94, 0.98, 1), Color(0.94, 0.925, 0.98, 1)]) if style.is_crystal() else PackedColorArray([Color(0.965, 0.976, 0.988, 1), Color(0.965, 0.976, 0.988, 1)])


## 根据登录/展开状态切换窗口尺寸、Chrome 布局与背景显示。
func _resize_window(target: Vector2i, minimum: Vector2i) -> void:
	var expanded: bool = _expanded or "--preview" in runtime.arguments()
	_chrome.set_login_mode(not expanded)
	%Background.visible = expanded
	_chrome.select_layout("expanded" if expanded else "login",target,minimum)


## 节点退出时释放协调器、账户生命周期、日志注册与日志资源。
func _exit_tree() -> void:
	if _perf_timer != null:
		_perf_timer.stop()
	if _coordinator != null: _coordinator.dispose()
	if _lifecycle != null: _lifecycle.stop()
	if _engine_log != null:
		runtime.unregister_logger(_engine_log)
		_engine_log.stop()
	if _log != null:
		_log.drain()
		_log.finish()

func _process(_delta: float) -> void:
	if _log != null:
		_log.drain()


## 打开设置类窗口（如 dynamics/settings）。
func _open_settings(kind: String) -> void:
	_coordinator.open(kind)

## 角色未读卡片只负责发起请求；窗口打开与选中由协调器统一处理。
func _open_dynamic_post(post: Dictionary) -> void:
	if post.is_empty():
		return
	var opened: bool = await _coordinator.open_post(post)
	_dynamics.dismiss_preview(str(post.get("id", "")))
	if not opened and is_inside_tree():
		ErrorDialog.present(self, "暂时无法打开这条动态，可能已被删除。")


## 将关闭请求转交给窗口协调器统一处理。
func _request_close(action: String) -> void:
	if _log != null:
		_log.log_runtime("runtime_window", {"phase":"close", "reason":action, "action":"close", "route":"main",
			"uptime_ms":Time.get_ticks_msec() - _started_msec, "pid":runtime.process_id()})
	if _coordinator != null: _coordinator.request_close(action)


## 退出或登出前先把本地记录收口：写不进去就静默忽略，不提示、不拦截、不改变退出流程。
func _request_persisted_close(action: String) -> void:
	if _closing or not is_instance_valid(_chat):
		_finish_close(action)
		return
	_closing = true
	_chat.prepare_close()
	await _chat.close_persistence()
	_closing = false
	_finish_close(action)


func _finish_close(action: String) -> void:
	if action == "logout":
		if is_instance_valid(_session):
			_session.logout()
		return
	if is_instance_valid(_session):
		_session.cancel()
	get_tree().quit()


func _restore_settings(settings: Resource) -> void:
	if settings.load_settings() != OK:
		return
	_restore_ratio(settings)
	_restore_volume(settings)
	if _log != null:
		_log.log_debug("debug_state", {"data":{"ratio":_ratio, "volume":_chat.get_audio_state().volume}})

func _restore_ratio(settings: Resource) -> void:
	var ratio: Variant = settings.get_value("layout", "ratio", 1.0 / 3.0)
	if _is_number(ratio):
		_ratio = clampf(float(ratio), 0.3, 0.6)

func _restore_volume(settings: Resource) -> void:
	var volume: Variant = settings.get_value("audio", "volume", 1.0)
	if _is_number(volume) and volume >= 0 and volume <= 1:
		_chat.set_volume(float(volume))

func _is_number(value: Variant) -> bool:
	return (value is float or value is int) and is_finite(float(value))

## 输入框高度按账号记：设置文件是全局的，用账号散列做 key 才互不干扰。
func _bind_composer_height(view: Control) -> void:
	var key := _composer_height_key(_session.get_session())
	_restore_composer_height(view, key)
	view.composer_height_changed.connect(func(height): _persist_composer_height(height, key))

func _composer_height_key(scope: Dictionary) -> String:
	var scope_key := AccountScope.key(str(scope.get("server", "")), str(scope.get("username", "")))
	return "composer_height" if scope_key.is_empty() else "composer_height." + scope_key

func _restore_composer_height(view: Control, key: String) -> void:
	var stored: Variant = _services.settings.get_value("layout", key, 0.0)
	if not (stored is float or stored is int):
		return
	if not is_finite(float(stored)):
		return
	view.set_composer_height(float(stored))

func _persist_composer_height(height: float, key: String) -> void:
	if height <= 0.0:
		return
	_services.settings.set_value("layout", key, height)
	if _services.settings.save_settings() != OK:
		_log.log_warning("warning_settings_save", {"code":"SETTINGS_SAVE_FAILED", "detail":"输入框高度保存失败", "phase":"failed"})

func _record_startup_phase(phase: String) -> void:
	if _log == null:
		return
	_log.log_performance("performance_startup", {"operation":phase, "outcome":"success",
		"duration_ms":int((Time.get_ticks_usec() - _started_usec) / 1000), "phase":"complete"})

func _log_previous_incomplete() -> void:
	if _log == null:
		return
	for run in _log.list_runs():
		if run.id == _log.get_run_id() or run.get("active", false) or run.get("closed", false):
			continue
		_log.log_runtime("runtime_previous_incomplete", {"phase":"abnormal", "reason":"abnormal", "uptime_ms":0,
			"pid":int(run.get("pid", 0)), "previous_run_id":str(run.id), "count":1})
		return

func _log_ui(route: String, action: Callable) -> void:
	var started := Time.get_ticks_usec()
	action.call()
	LogEvents.ui(_log, route, "open", int((Time.get_ticks_usec() - started) / 1000))

func _start_performance_sampling() -> void:
	if runtime.is_headless() or _perf_timer != null:
		return
	_perf_timer = Timer.new()
	_perf_timer.wait_time = 30.0
	_perf_timer.one_shot = false
	_perf_timer.timeout.connect(_sample_performance)
	add_child(_perf_timer)
	_perf_timer.start()

func _sample_performance() -> void:
	if _log == null:
		return
	var uptime := Time.get_ticks_msec() - _started_msec
	_log.log_performance("performance_sample", {"operation":"resource_sample", "outcome":"success", "duration_ms":0,
		"memory_bytes":int(Performance.get_monitor(Performance.MEMORY_STATIC)),
		"objects":int(Performance.get_monitor(Performance.OBJECT_COUNT)),
		"draw_calls":int(Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME)),
		"fps":int(Performance.get_monitor(Performance.TIME_FPS)), "uptime_ms":uptime})
	var queue_depth := 0
	if _services != null and is_instance_valid(_services.storage_worker):
		queue_depth = _services.storage_worker.pending_jobs()
	var unsaved := 0
	if _services != null and _services.persistence != null and _services.persistence.has_method("unsaved_count"):
		unsaved = int(_services.persistence.unsaved_count())
	_log.log_performance("performance_queue", {"operation":"queue_depth", "outcome":"success", "duration_ms":0,
		"queue_depth":queue_depth, "count":unsaved, "uptime_ms":uptime})
	_sample_http_summary()

func _sample_http_summary() -> void:
	var count := 0
	var total := 0
	var maximum := 0
	var bytes := 0
	var failures := 0
	for entry in _log.read_entries():
		if int(entry.get("seq", 0)) <= _last_summary_seq:
			continue
		_last_summary_seq = maxi(_last_summary_seq, int(entry.get("seq", 0)))
		if entry.get("category") != "access" or entry.get("event") != "access_http":
			continue
		count += 1
		var duration := int(entry.get("duration_ms", 0))
		total += duration
		maximum = maxi(maximum, duration)
		bytes += int(entry.get("bytes", 0))
		if entry.get("outcome") == "failure":
			failures += 1
	if count > 0:
		_log.log_performance("performance_http_summary", {"operation":"http_summary", "outcome":"success",
			"duration_ms":maximum, "count":count, "avg_ms":int(total / count), "max_ms":maximum,
			"bytes":bytes, "failures":failures, "window_ms":30000})

func _capture_or_resume() -> void:
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


func _show_signed_out() -> void:
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
