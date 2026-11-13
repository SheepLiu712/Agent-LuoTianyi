extends Control
## 常驻应用壳：持有服务装配、日志、窗口几何、协调器与全局提示，按账号会话在 PageSlot 中切换页面场景。

@export var appearance: Resource = preload("res://src/extensions/appearance_service.gd").new()
@export var world: Resource = preload("res://src/extensions/world_service.gd").new()
@export var devices: Resource = preload("res://src/extensions/device_service.gd").new()
@export var decoder_factory: Resource = preload("res://src/media/decoder_factory.gd").new()
@export var secret_protection: Resource = preload("res://src/platform/secret_protection.gd").new()
@export var password_encryption: Resource = preload("res://src/platform/password_encryption.gd").new()
@export var window_system: Resource = preload("res://src/platform/window_system.gd").new()
@export var runtime: Resource = preload("res://src/platform/runtime_environment.gd").new()

const Services = preload("res://src/composition/application_services.gd")
const LogSchema = preload("res://src/storage/log_schema.gd")
const LogEvents = preload("res://src/storage/log_events.gd")
const ErrorDialog = preload("res://src/ui/error_dialog.gd")
const LoginPage = preload("res://scenes/ui/pages/account_view.tscn")
const Workspace = preload("res://scenes/ui/pages/chat_workspace.tscn")

var _services: RefCounted
var _lifecycle: RefCounted
var _coordinator: RefCounted
var _session: Node
var _chat: Node
var _login_page: Control
var _workspace: Control

@onready var _chrome = %Chrome
@onready var _page_slot: Control = %PageSlot

var _closing := false
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


func get_login_page() -> Control:
	return _login_page


func get_workspace() -> Control:
	return _workspace


## 应用壳初始化入口：装配服务与页面宿主。
func _ready() -> void:
	get_window().title = preload("res://src/storage/release_info.gd").title()
	_geometry = Services.create_geometry(_layout_path)
	_chrome.configure(_geometry, "login")

	if "--preview" in runtime.arguments():
		_enter_preview_mode()
		return

	_resize_window(Vector2i(480, 690), Vector2i(360, 480))
	_init_services_and_logging()
	_init_window_coordinator()
	_mount_login_page()

	if not password_encryption.is_available():
		_handle_security_unavailable()
		return

	_mount_account_session()

	await get_tree().process_frame
	_record_startup_phase("first_frame")
	_start_performance_sampling()
	await _capture_or_resume()


func _enter_preview_mode() -> void:
	_log_problem.queue_free()
	_exit_dialog.queue_free()
	_resize_window(Vector2i(1200, 800), Vector2i(960, 640))
	var preview = load("res://scenes/preview/chat_preview.tscn").instantiate()
	_page_slot.add_child(preview)
	preview.offset_top = 0
	move_child(_chrome, get_child_count() - 1)


func _init_services_and_logging() -> void:
	_images_presenter = preload("res://src/ui/image_presenter.gd").new(_geometry, window_system)
	add_child(_images_presenter)

	_services = Services.new(_layout_path, runtime)
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

	_log_window = preload("res://scenes/ui/windows/log_window.tscn").instantiate() as Window
	_log_window.setup(_log)
	_services.ui_style.apply_view(_log_window, {"CopyButton":"action_copy", "ExportButton":"action_export"})
	add_child(_log_window)
	_log_window.get_node("%Chrome").configure(_geometry, "logs")
	_record_startup_phase("log_window_ready")


func _init_window_coordinator() -> void:
	get_tree().auto_accept_quit = false
	get_window().close_requested.connect(func(): _request_close("exit"))

	_coordinator = preload("res://src/application/window_coordinator.gd").new(
		self,
		_exit_dialog,
		_images_presenter,
		_geometry,
		_services.create_settings,
		_services.create_dynamics,
		func(): return is_instance_valid(_workspace) and _workspace.is_dirty(),
		_log)
	_coordinator.exit_requested.connect(func(): _request_persisted_close("exit"))
	_coordinator.logout_requested.connect(func(): _request_persisted_close("logout"))


func _mount_login_page() -> void:
	_login_page = LoginPage.instantiate() as Control
	_page_slot.add_child(_login_page)
	_login_page.log_requested.connect(func(): _log_ui("logs", _log_window.open))
	if _external_links == null:
		_external_links = Services.external_links()
	_login_page.feedback_requested.connect(func(): _login_page.report_feedback_result(_external_links.open_project()))


func _handle_security_unavailable() -> void:
	_log.log_security("security_component", {
		"action":"check", "outcome":"failure", "reason_code":"SECURITY_UNAVAILABLE",
		"subject":LogSchema.hash_subject("", "system"), "channel":"app", "detail":"认证加密组件不可用"})
	%SecurityError.show()
	%SecurityError.text = "账号与聊天功能暂不可用"
	call_deferred("_present_security_error")


func _mount_account_session() -> void:
	_services.mount(self, _session, _layout_path, password_encryption, secret_protection, decoder_factory)
	_record_startup_phase("account_mounted")
	_session = _services.account
	_models = _services.models
	_dynamics = _services.dynamics
	_chat = _services.chat
	_lifecycle = preload("res://src/application/account_lifecycle.gd").new(_chat, _models, _dynamics, appearance, world, devices, _services.avatar, _log)

	_login_page.setup(_session)
	_session.changed.connect(_account_changed)
	var settings: Resource = _services.settings
	_restore_settings(settings)
	_chat.state_changed.connect(func(_state): _save_volume_setting(settings))


func _save_volume_setting(settings: Resource) -> void:
	var volume: float = _chat.get_audio_state().volume
	if settings.get_value("audio", "volume", 1.0) == volume:
		return
	settings.set_value("audio", "volume", volume)
	if settings.save_settings() != OK:
		_log.log_warning("warning_settings_save", {"code":"SETTINGS_SAVE_FAILED", "detail":"音频音量保存失败", "phase":"failed"})


## 账户状态变化回调：登录后在 PageSlot 实例化聊天工作区，登出后销毁工作区并显示登录页。
func _present_security_error() -> void:
	ErrorDialog.present(self, "程序文件不完整，无法启动账号与聊天功能。请重新解压或重新安装；日志和问题反馈仍可使用。")


func _account_changed(state: Dictionary) -> void:
	_log.record("runtime_account_state", {
		"phase":state.phase,
		"code":"STORAGE_ERROR" if state.storage_error else state.code,
		"reason":"account",
		"uptime_ms":Time.get_ticks_msec() - _started_msec,
		"pid":runtime.process_id()})
	# 本地登录状态写入失败时保留页内警告；下一个没有 storage_error 的状态再收起。
	%AccountStorageWarning.visible = bool(state.get("storage_error", false))

	if state.phase == "signed_in":
		_show_signed_in()
	else:
		_show_signed_out()


func _show_signed_in() -> void:
	if is_instance_valid(_login_page):
		_login_page.hide()
	_mount_workspace()

	if not _expanded:
		_expanded = true
		_resize_window(_expanded_size, Vector2i(960, 640))

	var lifecycle_result: Error = _lifecycle.start(_session.get_session())
	if lifecycle_result != OK:
		_log.record("runtime_account_state", {
			"phase":"signed_out", "code":"ACCOUNT_START_FAILED", "reason":"account_start_failed",
			"uptime_ms":Time.get_ticks_msec() - _started_msec, "pid":runtime.process_id()})
		_session.logout()
		return
	_coordinator.prewarm("settings")


func _mount_workspace() -> void:
	if is_instance_valid(_workspace):
		_workspace.show()
		return
	_workspace = Workspace.instantiate() as Control
	_page_slot.add_child(_workspace)
	_workspace.setup(_chat, _dynamics, _services.settings, _session.get_session(), _services.ui_style, _log)
	_workspace.chat_requested.connect(func(): _log_ui("chat", func(): _chrome.open_window()))
	_workspace.dynamics_requested.connect(func(): _open_settings("dynamics"))
	_workspace.settings_requested.connect(func(): _open_settings("settings"))
	_workspace.logs_requested.connect(func(): _log_ui("logs", _log_window.open))
	_workspace.dynamic_post_requested.connect(_open_dynamic_post)
	_workspace.image_requested.connect(func(provider): _images_presenter.open_image(get_window(), provider))
	_workspace.attachment_requested.connect(func(provider, confirm): _images_presenter.open_image(get_window(), provider, confirm))
	_workspace.attachment_cleared.connect(func(): _images_presenter.close_confirmation(get_window()))


## 根据登录/展开状态切换窗口尺寸与 Chrome 布局。
func _resize_window(target: Vector2i, minimum: Vector2i) -> void:
	var expanded: bool = _expanded or "--preview" in runtime.arguments()
	_chrome.set_login_mode(not expanded)
	_chrome.select_layout("expanded" if expanded else "login", target, minimum)


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
		_log.log_runtime("runtime_window", {
			"phase":"close", "reason":action, "action":"close", "route":"main",
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
	_restore_volume(settings)
	if _log != null:
		var ratio: Variant = settings.get_value("layout", "ratio", 1.0 / 3.0)
		_log.log_debug("debug_state", {"data":{"ratio":ratio, "volume":_chat.get_audio_state().volume}})


func _restore_volume(settings: Resource) -> void:
	var volume: Variant = settings.get_value("audio", "volume", 1.0)
	if (volume is float or volume is int) and is_finite(float(volume)) and volume >= 0 and volume <= 1:
		_chat.set_volume(float(volume))


func _record_startup_phase(phase: String) -> void:
	if _log == null:
		return
	_log.log_performance("performance_startup", {
		"operation":phase, "outcome":"success",
		"duration_ms":int((Time.get_ticks_usec() - _started_usec) / 1000), "phase":"complete"})


func _log_previous_incomplete() -> void:
	if _log == null:
		return
	for run in _log.list_runs():
		if run.id == _log.get_run_id() or run.get("active", false) or run.get("closed", false):
			continue
		_log.log_runtime("runtime_previous_incomplete", {
			"phase":"abnormal", "reason":"abnormal", "uptime_ms":0,
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
	_log.log_performance("performance_sample", {
		"operation":"resource_sample", "outcome":"success", "duration_ms":0,
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
	_log.log_performance("performance_queue", {
		"operation":"queue_depth", "outcome":"success", "duration_ms":0,
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
		_log.log_performance("performance_http_summary", {
			"operation":"http_summary", "outcome":"success",
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
		var saved: Error = runtime.capture(get_viewport(), capture)
		get_tree().quit(0 if saved == OK else 1)
	elif not runtime.is_headless():
		_session.resume()


func _show_signed_out() -> void:
	_coordinator.close_all()
	_lifecycle.stop()

	if is_instance_valid(_workspace):
		_workspace.hide()
		_workspace.queue_free()
		_workspace = null

	if is_instance_valid(_login_page):
		_login_page.show()

	if _expanded:
		if window_system.windowed(get_window()):
			_expanded_size = window_system.geometry(get_window()).size
		_expanded = false
		_resize_window(Vector2i(480, 690), Vector2i(360, 480))
