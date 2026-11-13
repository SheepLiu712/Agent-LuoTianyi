extends Control
## 浮层提示：可见区域顶部安全区的一条横向矩形，出现时淡入、到点后淡出，鼠标事件一律穿透。
## seconds 传负数表示常驻，直到被下一条替换或显式 clear()。

const SCENE_PATH := "res://scenes/ui/components/toast_overlay.tscn"
const DEFAULT_SECONDS := 2.0
const FADE_IN := 0.15
const FADE_OUT := 0.25
## 自动折行要先拿到宽度才能算高度，所以排版走两轮。
const LAYOUT_PASSES := 2
const TOP_MARGIN := 16.0

@onready var _panel: PanelContainer = %Panel
@onready var _text: Label = %Text
var _last := ""
var _tween: Tween
var _kind := "info"
var _ui_style: RefCounted


static func present_in(
	source: Node,
	text: String,
	kind: String = "info",
	seconds: float = DEFAULT_SECONDS,
	ui_style: RefCounted = null
) -> Control:
	if source == null or text.strip_edges().is_empty() or not source.is_inside_tree():
		return null
	var host := _resolve_toast_host(source)
	if host == null:
		return null
	var toast := _find_host_toast(host)
	if toast == null:
		toast = (load(SCENE_PATH) as PackedScene).instantiate()
		host.add_child(toast)
	if ui_style != null and toast.has_method("set_ui_style"):
		toast.set_ui_style(ui_style)
	toast.show_kind(text, kind, seconds)
	return toast


static func _resolve_toast_host(source: Node) -> Node:
	if source is Window or (source is Control and not source is Container):
		return source
	return source.get_window()


static func _find_host_toast(host: Node) -> Control:
	for child in host.get_children():
		if child.is_in_group("toast_overlay") and child.has_method("show_kind"):
			return child
	return null


func _ready() -> void:
	add_to_group("toast_overlay")
	set_notify_transform(true)
	hide()
	_watch_parent()
	_layout()


## 与卡片/弹窗共用 UiStyle；未注入时仍使用主题里对齐后的 SettingsToast 兜底。
func set_ui_style(style: RefCounted) -> void:
	if _ui_style != null and _ui_style.style_changed.is_connected(_on_style_changed):
		_ui_style.style_changed.disconnect(_on_style_changed)
	_ui_style = style
	if _ui_style != null:
		_ui_style.style_changed.connect(_on_style_changed)
	if is_node_ready() and visible:
		_apply_kind_style(_kind)
		_layout()


func _on_style_changed() -> void:
	if is_node_ready() and visible:
		_apply_kind_style(_kind)
		_layout()


## 舞台尺寸直接问父级要：窗口和页面在隐藏期间不重排，读自己的 rect 会拿到上一轮的旧值。
func _stage_size() -> Vector2:
	var parent := get_parent()
	if parent is Control and not parent is Container:
		return (parent as Control).size
	if parent is Window:
		return Vector2((parent as Window).size)
	return size


func _visible_stage_rect() -> Rect2:
	var parent := get_parent()
	if parent is Container and is_inside_tree():
		var scroll := _enclosing_scroll()
		if scroll != null and scroll.size.x > 0.0 and scroll.size.y > 0.0:
			var offset := scroll.get_global_position() - get_global_position()
			return Rect2(offset, scroll.size)
	return Rect2(Vector2.ZERO, _stage_size())


func _enclosing_scroll() -> ScrollContainer:
	var current := get_parent()
	while current != null:
		if current is ScrollContainer:
			return current
		if current is Window:
			break
		current = current.get_parent()
	return null


## 铺满舞台，再把气泡摆在可见区顶部居中；不压正中表单内容，容器内也能落在可视窗口顶端。
func _layout() -> void:
	if not is_node_ready():
		return
	_fill_stage()
	for _pass in LAYOUT_PASSES:
		_panel.size = _panel.get_combined_minimum_size()
	var area := _visible_stage_rect()
	var x := area.position.x + (area.size.x - _panel.size.x) * 0.5
	var max_offset_y := maxf(0.0, area.size.y - _panel.size.y)
	var y := area.position.y + minf(TOP_MARGIN, max_offset_y)
	_panel.position = Vector2(x, y).round()


## 父级是普通 Control 或窗口时气泡自己铺满；父级是容器时尺寸交给容器。
func _fill_stage() -> void:
	var parent := get_parent()
	if (parent is Control and not parent is Container) or parent is Window:
		set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)


## 窗口缩放、页面换尺寸与滚动容器滚屏都要同步顶部安全区。
func _watch_parent() -> void:
	var parent := get_parent()
	if parent is Control:
		parent.resized.connect(_layout)
	elif parent is Window:
		parent.size_changed.connect(_layout)
	var scroll := _enclosing_scroll()
	if scroll != null:
		scroll.resized.connect(_layout)
		scroll.sort_children.connect(_layout)
		scroll.get_v_scroll_bar().value_changed.connect(func(_value): _layout.call_deferred())


## 父级从隐藏变显示或滚动位移更新时，同步补全顶部安全区定位。
func _notification(what: int) -> void:
	if what == NOTIFICATION_TRANSFORM_CHANGED or (what == NOTIFICATION_VISIBILITY_CHANGED and is_visible_in_tree()):
		_layout()


func show_message(text: String, seconds: float = DEFAULT_SECONDS) -> void:
	show_kind(text, "info", seconds)


## 语义化提示：成功/错误/进行中使用不同边框与底色，避免只看停留时长区分。
func show_kind(text: String, kind: String, seconds: float = DEFAULT_SECONDS) -> void:
	if text.is_empty():
		return
	_kind = kind
	_last = text
	_text.text = text
	_apply_kind_style(kind)
	_layout()
	show()
	_kill_tween()
	_panel.modulate.a = 0.0
	_tween = create_tween()
	_tween.tween_property(_panel, "modulate:a", 1.0, FADE_IN)
	if seconds < 0.0:
		return
	_tween.tween_interval(maxf(0.0, seconds))
	_tween.tween_property(_panel, "modulate:a", 0.0, FADE_OUT)
	_tween.tween_callback(hide)


## 立刻抹掉提示；淡出后仍保留的 _last 也一并清空，避免下一次被误读成「还在显示」。
func clear() -> void:
	_kill_tween()
	_last = ""
	_text.text = ""
	_panel.remove_theme_stylebox_override("panel")
	_kind = "info"
	hide()


func _apply_kind_style(kind: String) -> void:
	if not is_node_ready():
		return
	var style := _panel.get_theme_stylebox("panel").duplicate() as StyleBoxFlat
	if style == null:
		return
	if _ui_style != null:
		_ui_style.apply_toast_style(style, kind)
	else:
		_apply_fallback_toast_style(style, kind)
	_panel.add_theme_stylebox_override("panel", style)


func _apply_fallback_toast_style(style: StyleBoxFlat, kind: String) -> void:
	match kind:
		"success":
			style.border_color = Color(0.18, 0.64, 0.40, 0.9)
			style.bg_color = Color(0.94, 1.0, 0.96, 1)
		"error":
			style.border_color = Color(0.78, 0.24, 0.24, 0.9)
			style.bg_color = Color(1.0, 0.95, 0.95, 1)
		"progress":
			style.border_color = Color(0.20, 0.52, 0.86, 0.9)
			style.bg_color = Color(0.95, 0.98, 1.0, 1)
		_:
			style.border_color = Color(0.18, 0.48, 0.80, 0.9)
			style.bg_color = Color(1, 1, 1, 1)
	style.set_border_width_all(1)


## 文案在淡出后仍可读，测试与诊断不必和动画赛跑。
func last_text() -> String:
	return _last


func _kill_tween() -> void:
	if _tween != null and _tween.is_valid():
		_tween.kill()
	_tween = null
