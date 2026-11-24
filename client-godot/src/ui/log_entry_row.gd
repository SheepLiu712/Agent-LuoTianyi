extends VBoxContainer
## 结构化日志单行组件：表格摘要行 + 点击懒加载展开的双列 JSON 详情抽屉。

const ROW_NORMAL_BG := Color("ffffff")
const ROW_WARN_BG := Color("fffaf0")
const ROW_ERROR_BG := Color("fff5f5")
const ROW_OPEN_BG := Color("eaf6ff")
const ROW_HOVER_BG := Color("f3f9fd")
const BORDER_ROW := Color("f0f4f7")
const DRAWER_BG := Color("f4f9fd")
const DRAWER_BORDER := Color("e1ebf2")

const CATEGORY_SHORT := {
	"business": "业务流",
	"network": "网络通信",
	"storage": "存储",
	"system": "系统诊断",
}

const LEVEL_STYLES := {
	"INFO": {"bg": Color("e3f3fc"), "fg": Color("126091")},
	"WARN": {"bg": Color("fff1d9"), "fg": Color("8f4f00")},
	"ERROR": {"bg": Color("fde6e6"), "fg": Color("b42f2f")},
	"DEBUG": {"bg": Color("eef1f3"), "fg": Color("526069")},
}

var _entry: Dictionary = {}
var _mono_font: Font
var _expanded := false
var _row_btn: Button
var _drawer: PanelContainer
var _normal_style: StyleBoxFlat
var _hover_style: StyleBoxFlat
var _open_style: StyleBoxFlat


func setup(entry: Dictionary, mono_font: Font) -> void:
	_entry = entry.duplicate(true)
	_mono_font = mono_font
	if is_node_ready():
		_build_summary()


func _ready() -> void:
	add_theme_constant_override("separation", 0)
	size_flags_horizontal = Control.SIZE_EXPAND_FILL
	if not _entry.is_empty():
		_build_summary()


func set_expanded(open: bool) -> void:
	if _expanded == open:
		return
	_expanded = open
	if _expanded and _drawer == null:
		_build_drawer()
	if _drawer != null:
		_drawer.visible = _expanded
	_sync_row_style()


func _toggle_expanded() -> void:
	set_expanded(not _expanded)


func _build_summary() -> void:
	if _row_btn != null:
		return
	_init_row_styles()
	_row_btn = Button.new()
	_row_btn.custom_minimum_size = Vector2(0, 34)
	_row_btn.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_row_btn.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	_row_btn.focus_mode = Control.FOCUS_NONE
	_row_btn.pressed.connect(_toggle_expanded)
	_sync_row_style()

	var cols := HBoxContainer.new()
	cols.set_anchors_preset(Control.PRESET_FULL_RECT)
	cols.offset_left = 14.0
	cols.offset_right = -14.0
	cols.mouse_filter = Control.MOUSE_FILTER_IGNORE
	cols.add_theme_constant_override("separation", 8)
	_row_btn.add_child(cols)

	cols.add_child(_make_time_label())
	cols.add_child(_make_level_cell())
	cols.add_child(_make_text_cell(_category_text(), 72.0, Color("1f3340")))
	cols.add_child(_make_text_cell(str(_entry.get("module", "")), 78.0, Color("1f3340")))
	cols.add_child(_make_event_rich_label())
	add_child(_row_btn)


func _init_row_styles() -> void:
	var level := str(_entry.get("level", "INFO"))
	var base_bg := ROW_WARN_BG if level == "WARN" else (ROW_ERROR_BG if level == "ERROR" else ROW_NORMAL_BG)
	_normal_style = _make_row_box(base_bg, BORDER_ROW)
	_hover_style = _make_row_box(ROW_HOVER_BG, BORDER_ROW)
	_open_style = _make_row_box(ROW_OPEN_BG, BORDER_ROW)


func _make_row_box(bg: Color, border: Color) -> StyleBoxFlat:
	var box := StyleBoxFlat.new()
	box.bg_color = bg
	box.border_width_bottom = 1
	box.border_color = border
	return box


func _sync_row_style() -> void:
	if _row_btn == null:
		return
	_row_btn.add_theme_stylebox_override("normal", _open_style if _expanded else _normal_style)
	_row_btn.add_theme_stylebox_override("hover", _open_style if _expanded else _hover_style)
	_row_btn.add_theme_stylebox_override("pressed", _open_style)


func _make_time_label() -> Label:
	var lbl := Label.new()
	lbl.custom_minimum_size = Vector2(104, 0)
	lbl.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	lbl.mouse_filter = Control.MOUSE_FILTER_IGNORE
	lbl.text = _format_time(_entry)
	lbl.add_theme_font_override("font", _mono_font)
	lbl.add_theme_font_size_override("font_size", 12)
	lbl.add_theme_color_override("font_color", Color("526470"))
	return lbl


func _make_level_cell() -> Control:
	var wrap := HBoxContainer.new()
	wrap.custom_minimum_size = Vector2(64, 0)
	wrap.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	wrap.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var level := str(_entry.get("level", "INFO"))
	var palette: Dictionary = LEVEL_STYLES.get(level, LEVEL_STYLES["INFO"])
	var badge := PanelContainer.new()
	badge.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var box := StyleBoxFlat.new()
	box.bg_color = palette.bg
	box.set_corner_radius_all(4)
	box.content_margin_left = 6.0
	box.content_margin_right = 6.0
	box.content_margin_top = 1.0
	box.content_margin_bottom = 1.0
	badge.add_theme_stylebox_override("panel", box)
	var lbl := Label.new()
	lbl.mouse_filter = Control.MOUSE_FILTER_IGNORE
	lbl.text = level
	lbl.add_theme_font_override("font", _mono_font)
	lbl.add_theme_font_size_override("font_size", 11)
	lbl.add_theme_color_override("font_color", palette.fg)
	badge.add_child(lbl)
	wrap.add_child(badge)
	return wrap


func _make_text_cell(text_value: String, width: float, color: Color) -> Label:
	var lbl := Label.new()
	lbl.custom_minimum_size = Vector2(width, 0)
	lbl.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	lbl.clip_text = true
	lbl.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	lbl.mouse_filter = Control.MOUSE_FILTER_IGNORE
	lbl.text = text_value
	lbl.add_theme_font_size_override("font_size", 12)
	lbl.add_theme_color_override("font_color", color)
	return lbl


func _make_event_rich_label() -> RichTextLabel:
	var rtl := RichTextLabel.new()
	rtl.bbcode_enabled = true
	rtl.fit_content = true
	rtl.scroll_active = false
	rtl.autowrap_mode = TextServer.AUTOWRAP_OFF
	rtl.clip_contents = true
	rtl.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	rtl.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	rtl.mouse_filter = Control.MOUSE_FILTER_IGNORE
	rtl.add_theme_font_size_override("normal_font_size", 12)
	rtl.add_theme_font_override("mono_font", _mono_font)
	rtl.add_theme_font_size_override("mono_font_size", 11)
	rtl.text = _format_event_bbcode()
	return rtl


func _format_event_bbcode() -> String:
	var msg := _esc(str(_entry.get("message", "")))
	var tag := _event_tag()
	var metric := _event_metric()
	var out := "[color=#1f3340]%s[/color]" % msg
	if not tag.is_empty():
		out += " [color=#526470]·[/color] [bgcolor=#f1f5f8][color=#3f5563][code] %s [/code][/color][/bgcolor]" % _esc(tag)
	if not metric.is_empty():
		out += "  [color=#526470]%s[/color]" % _esc(metric)
	return out


func _event_tag() -> String:
	var code := str(_entry.get("code", ""))
	if not code.is_empty() and code != "OK":
		return code
	var method := str(_entry.get("method", ""))
	if not method.is_empty():
		return method
	return str(_entry.get("event", ""))


func _event_metric() -> String:
	if _entry.has("duration_ms"):
		return "%d ms" % int(_entry.get("duration_ms", 0))
	if _entry.has("bytes"):
		return "%d B" % int(_entry.get("bytes", 0))
	if _entry.has("count"):
		return "%d" % int(_entry.get("count", 0))
	var route := str(_entry.get("route", ""))
	if not route.is_empty():
		return route
	var phase := str(_entry.get("phase", ""))
	return phase if not phase.is_empty() and phase != "unknown" else ""


func _category_text() -> String:
	var cat := str(_entry.get("category", "system"))
	return CATEGORY_SHORT.get(cat, cat)


func _build_drawer() -> void:
	_drawer = PanelContainer.new()
	var box := StyleBoxFlat.new()
	box.bg_color = DRAWER_BG
	box.border_width_bottom = 1
	box.border_color = DRAWER_BORDER
	box.content_margin_left = 240.0
	box.content_margin_top = 10.0
	box.content_margin_right = 14.0
	box.content_margin_bottom = 10.0
	_drawer.add_theme_stylebox_override("panel", box)

	var grid := GridContainer.new()
	grid.columns = 2
	grid.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	grid.add_theme_constant_override("h_separation", 24)
	grid.add_theme_constant_override("v_separation", 3)
	for pair in _drawer_fields():
		grid.add_child(_make_kv_label(pair[0], pair[1]))
	_drawer.add_child(grid)
	add_child(_drawer)


func _drawer_fields() -> Array:
	var fields := {}
	for key in _entry:
		if key in ["message", "level", "category", "module"]:
			continue
		if key == "data" and _entry[key] is Dictionary:
			for sub_key in _entry[key]:
				fields[str(sub_key)] = _entry[key][sub_key]
		else:
			fields[str(key)] = _entry[key]
	var keys := fields.keys()
	keys.sort()
	var pairs: Array = []
	for k in keys:
		var val: Variant = fields[k]
		if val is String and str(val).is_empty():
			continue
		pairs.append([str(k), val])
	return pairs


func _make_kv_label(key_name: String, value: Variant) -> RichTextLabel:
	var rtl := RichTextLabel.new()
	rtl.bbcode_enabled = true
	rtl.fit_content = true
	rtl.scroll_active = false
	rtl.selection_enabled = true
	rtl.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	rtl.add_theme_font_override("normal_font", _mono_font)
	rtl.add_theme_font_size_override("normal_font_size", 12)
	var val_str := ""
	var val_color := "#2b7a3d"
	if value is int or value is float or value is bool:
		val_str = str(value)
		val_color = "#9c5700"
	else:
		val_str = "\"%s\"" % _esc(str(value))
	rtl.text = "[color=#1e6899]%s[/color]  [color=%s]%s[/color]" % [_esc(key_name), val_color, val_str]
	return rtl


static func _format_time(entry: Dictionary) -> String:
	var raw := str(entry.get("time", ""))
	var hms := raw.substr(11, 8) if raw.length() >= 19 else raw
	if entry.has("elapsed_ms"):
		return "%s.%03d" % [hms, posmod(int(entry.get("elapsed_ms", 0)), 1000)]
	return hms


static func _esc(raw: String) -> String:
	return raw.replace("[", "[lb]")
