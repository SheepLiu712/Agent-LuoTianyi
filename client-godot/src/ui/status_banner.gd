extends PanelContainer
## 通用内联状态横幅 / Snackbar：统一语义色、边框与可选行内操作按钮。

signal action_pressed
const UiStyle = preload("res://src/application/ui_style.gd")

@onready var _message: Label = %Message
@onready var _action: Button = %Action

var _kind := "muted"
var _ui_style: RefCounted


func _ready() -> void:
	_action.pressed.connect(func(): action_pressed.emit())
	_refresh_appearance()


func set_ui_style(style: RefCounted) -> void:
	if _ui_style != null and _ui_style.style_changed.is_connected(_refresh_appearance):
		_ui_style.style_changed.disconnect(_refresh_appearance)
	_ui_style = style
	if _ui_style != null:
		_ui_style.style_changed.connect(_refresh_appearance)
	if is_node_ready():
		_refresh_appearance()


func set_status(text: String, kind: String = "muted", action_text: String = "") -> void:
	var clean := text.strip_edges()
	_kind = kind
	if clean.is_empty():
		clear_status()
		return
	_message.text = clean
	_action.text = action_text
	_action.visible = not action_text.strip_edges().is_empty()
	_refresh_appearance()
	show()


func clear_status() -> void:
	_message.text = ""
	_action.visible = false
	hide()


func _refresh_appearance() -> void:
	if not is_node_ready():
		return
	apply_surface_status(self, _message, _kind, _ui_style)


static func apply_surface_status(
	panel: PanelContainer,
	label: Label,
	kind: String,
	ui_style: RefCounted = null
) -> void:
	var crystal: bool = ui_style != null and bool(ui_style.is_crystal())
	var palette := UiStyle.status_palette(kind)
	if label != null:
		label.add_theme_color_override("font_color", palette.text)
	if panel != null:
		var style := panel.get_theme_stylebox("panel", &"StatusBannerSurface").duplicate() as StyleBoxFlat
		if style != null:
			UiStyle.apply_banner_box(style, kind, crystal)
			panel.add_theme_stylebox_override("panel", style)
