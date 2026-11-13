extends Control
## 主聊天工作区页面：组合左侧导航栏、Live2D 角色区与聊天区，负责分栏布局与样式协调。

const AccountScope = preload("res://src/domain/account_scope.gd")
## 导航节点 → 图标名。按图标语义而非节点名映射：NavDynamics 用 @（动态/提及），NavLogs 用卷宗（日志归档）。
const NAV_ICONS := {"NavChat":"nav_chat", "NavDynamics":"nav_at", "NavSettings":"nav_settings", "NavLogs":"nav_scroll"}

signal chat_requested
signal dynamics_requested
signal settings_requested
signal logs_requested
signal dynamic_post_requested(post: Dictionary)
signal image_requested(provider: Callable)
signal attachment_requested(provider: Callable, confirm: Callable)
signal attachment_cleared

@onready var _background: TextureRect = %Background
@onready var _navigation: PanelContainer = %Navigation
@onready var _nav_chat: Button = %NavChat
@onready var _nav_dynamics: Button = %NavDynamics
@onready var _dynamics_unread: Control = %DynamicsUnread
@onready var _nav_settings: Button = %NavSettings
@onready var _nav_logs: Button = %NavLogs
@onready var _split: HSplitContainer = %Split
@onready var _avatar: Control = %AvatarPanel
@onready var _chat_view: Control = %ChatView

var _chat: Node
var _dynamics: Node
var _settings: Resource
var _scope: Dictionary = {}
var _ui_style: RefCounted
var _log: RefCounted
var _rail_style: StyleBoxFlat
var _ratio := 1.0 / 3.0
var _initialized := false


func setup(chat: Node, dynamics: Node, settings_store: Resource, scope: Dictionary, ui_style: RefCounted, log_sink: RefCounted = null) -> void:
	_chat = chat
	_dynamics = dynamics
	_settings = settings_store
	_scope = scope.duplicate(true)
	_ui_style = ui_style
	_log = log_sink
	if is_node_ready():
		_initialize()


func get_chat_view() -> Control:
	return _chat_view


func get_avatar_panel() -> Control:
	return _avatar


func get_split_ratio() -> float:
	return _ratio


func is_dirty() -> bool:
	return is_instance_valid(_chat_view) and _chat_view.is_dirty()


func focus_chat_nav() -> void:
	_nav_chat.button_pressed = true


func _ready() -> void:
	_bind_navigation()
	if _chat == null:
		return
	_initialize()


func _exit_tree() -> void:
	if _ui_style != null and _ui_style.style_changed.is_connected(_apply_workspace_style):
		_ui_style.style_changed.disconnect(_apply_workspace_style)
	if _dynamics != null:
		if _dynamics.unread_changed.is_connected(_on_unread_changed):
			_dynamics.unread_changed.disconnect(_on_unread_changed)
		if _dynamics.latest_unread_changed.is_connected(_on_latest_unread_changed):
			_dynamics.latest_unread_changed.disconnect(_on_latest_unread_changed)
	if _chat != null:
		if _chat.expression_requested.is_connected(_on_expression_requested):
			_chat.expression_requested.disconnect(_on_expression_requested)
		if _chat.mouth_changed.is_connected(_on_mouth_changed):
			_chat.mouth_changed.disconnect(_on_mouth_changed)


func _initialize() -> void:
	if _initialized:
		return
	_initialized = true
	_restore_ratio()
	_apply_style()
	_bind_session()
	_split.resized.connect(_resize_split)
	_split.dragged.connect(_on_split_dragged)
	_resize_split.call_deferred()


func _bind_navigation() -> void:
	_nav_chat.pressed.connect(func():
		_nav_chat.button_pressed = true
		chat_requested.emit())
	_nav_dynamics.pressed.connect(func(): dynamics_requested.emit())
	_nav_settings.pressed.connect(func(): settings_requested.emit())
	_nav_logs.pressed.connect(func(): logs_requested.emit())


func _bind_session() -> void:
	_avatar.touched.connect(_chat.record_touch)
	_avatar.dynamic_requested.connect(func(post): dynamic_post_requested.emit(post))
	_chat_view.setup(_chat)
	_chat_view.image_requested.connect(func(provider): image_requested.emit(provider))
	_chat_view.attachment_requested.connect(func(provider, confirm): attachment_requested.emit(provider, confirm))
	_chat_view.attachment_cleared.connect(func(): attachment_cleared.emit())
	_bind_composer_height(_chat_view)
	_chat.expression_requested.connect(_on_expression_requested)
	_chat.mouth_changed.connect(_on_mouth_changed)
	if _dynamics != null:
		_dynamics.unread_changed.connect(_on_unread_changed)
		_dynamics.latest_unread_changed.connect(_on_latest_unread_changed)
		_on_unread_changed(int(_dynamics.get_state().get("unread", 0)))
		_on_latest_unread_changed(_dynamics.get_latest_unread())


func _apply_style() -> void:
	if _ui_style == null:
		return
	_ui_style.apply_view(self, NAV_ICONS)
	if not _ui_style.style_changed.is_connected(_apply_workspace_style):
		_ui_style.style_changed.connect(_apply_workspace_style)
	_apply_workspace_style()
	_avatar.set_ui_style(_ui_style)
	_chat_view.set_ui_style(_ui_style)


func _apply_workspace_style() -> void:
	if _ui_style == null or not is_node_ready():
		return
	if _rail_style == null:
		_rail_style = _navigation.get_theme_stylebox("panel").duplicate() as StyleBoxFlat
		_navigation.add_theme_stylebox_override("panel", _rail_style)
	_ui_style.apply_navigation_rail_style(_rail_style)
	var backdrop := _background.texture as GradientTexture2D
	if backdrop != null and backdrop.gradient != null:
		backdrop.gradient.colors = _ui_style.backdrop_gradient_colors()


func _restore_ratio() -> void:
	if _settings == null:
		return
	var ratio: Variant = _settings.get_value("layout", "ratio", 1.0 / 3.0)
	if _is_number(ratio):
		_ratio = clampf(float(ratio), 0.3, 0.6)


func _on_split_dragged(_offset: int) -> void:
	_ratio = _avatar.size.x / maxf(_split.size.x, 1.0)
	if _settings == null:
		return
	_settings.set_value("layout", "ratio", _ratio)
	if _settings.save_settings() != OK and _log != null:
		_log.log_warning("warning_settings_save", {"code":"SETTINGS_SAVE_FAILED", "detail":"窗口布局保存失败", "phase":"failed"})


func _resize_split() -> void:
	if not is_node_ready() or not is_instance_valid(_avatar) or not is_instance_valid(_chat_view):
		return
	var available := _split.size.x
	if available <= 1.0:
		return
	var separation := float(_split.get_theme_constant("separation"))
	var left_min := _avatar.get_combined_minimum_size().x
	var right_min := _chat_view.get_combined_minimum_size().x
	var max_left := maxf(left_min, available - right_min - separation)
	_split.split_offset = roundi(clampf(available * _ratio, left_min, max_left))


func _bind_composer_height(view: Control) -> void:
	var key := _composer_height_key(_scope)
	_restore_composer_height(view, key)
	view.composer_height_changed.connect(func(height): _persist_composer_height(height, key))


func _composer_height_key(scope: Dictionary) -> String:
	var scope_key := AccountScope.key(str(scope.get("server", "")), str(scope.get("username", "")))
	return "composer_height" if scope_key.is_empty() else "composer_height." + scope_key


func _restore_composer_height(view: Control, key: String) -> void:
	if _settings == null:
		return
	var stored: Variant = _settings.get_value("layout", key, 0.0)
	if _is_number(stored):
		view.set_composer_height(float(stored))


func _persist_composer_height(height: float, key: String) -> void:
	if height <= 0.0 or _settings == null:
		return
	_settings.set_value("layout", key, height)
	if _settings.save_settings() != OK and _log != null:
		_log.log_warning("warning_settings_save", {"code":"SETTINGS_SAVE_FAILED", "detail":"输入框高度保存失败", "phase":"failed"})


func _is_number(value: Variant) -> bool:
	return (value is float or value is int) and is_finite(float(value))


func _on_unread_changed(count: int) -> void:
	if is_instance_valid(_dynamics_unread):
		_dynamics_unread.visible = count > 0
	if is_instance_valid(_nav_dynamics):
		_nav_dynamics.tooltip_text = "动态" if count <= 0 else "动态 · %s 条未读" % count


func _on_latest_unread_changed(post: Dictionary) -> void:
	if is_instance_valid(_avatar):
		_avatar.set_unread_dynamic(post)


func _on_expression_requested(command: String) -> void:
	if is_instance_valid(_avatar):
		_avatar.avatar.apply_expression(command)


func _on_mouth_changed(value: float) -> void:
	if is_instance_valid(_avatar):
		_avatar.avatar.set_mouth_openness(value)
