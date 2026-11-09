extends Control
## 浮层提示：画面正中的一条横向矩形，出现时淡入、到点后淡出，鼠标事件一律穿透。
## seconds 传负数表示常驻，直到被下一条替换或显式 clear()。

const DEFAULT_SECONDS := 2.0
const FADE_IN := 0.15
const FADE_OUT := 0.25
## 自动折行要先拿到宽度才能算高度，所以排版走两轮。
const LAYOUT_PASSES := 2

@onready var _panel: PanelContainer = %Panel
@onready var _text: Label = %Text
var _last := ""
var _tween: Tween


func _ready() -> void:
	hide()
	_watch_parent()
	_layout()


## 舞台尺寸直接问父级要：窗口和页面在隐藏期间不重排，读自己的 rect 会拿到上一轮的旧值。
func _stage_size() -> Vector2:
	var parent := get_parent()
	if parent is Control and not parent is Container:
		return (parent as Control).size
	if parent is Window:
		return Vector2((parent as Window).size)
	return size


## 铺满舞台，再把气泡摆到正中；位置算出来而不是交给容器，舞台是 0 的时候也不会贴角。
func _layout() -> void:
	if not is_node_ready():
		return
	_fill_stage()
	for _pass in LAYOUT_PASSES:
		_panel.size = _panel.get_combined_minimum_size()
	_panel.position = ((_stage_size() - _panel.size) * 0.5).round()


## 父级是普通 Control 或窗口时气泡自己铺满；父级是容器时尺寸交给容器。
func _fill_stage() -> void:
	var parent := get_parent()
	if (parent is Control and not parent is Container) or parent is Window:
		set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)


## 窗口缩放、页面换尺寸都要重排，否则居中会跟着父级一起漂。
func _watch_parent() -> void:
	var parent := get_parent()
	if parent is Control:
		parent.resized.connect(_layout)
	elif parent is Window:
		parent.size_changed.connect(_layout)


## 父级从隐藏变显示时子节点也会收到这条通知，趁机把还没有尺寸的舞台补上。
func _notification(what: int) -> void:
	if what == NOTIFICATION_VISIBILITY_CHANGED and is_visible_in_tree():
		_layout()


func show_message(text: String, seconds: float = DEFAULT_SECONDS) -> void:
	if text.is_empty():
		return
	_last = text
	_text.text = text
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
	hide()


## 文案在淡出后仍可读，测试与诊断不必和动画赛跑。
func last_text() -> String:
	return _last


func _kill_tween() -> void:
	if _tween != null and _tween.is_valid():
		_tween.kill()
	_tween = null
