extends RefCounted
## 应用级外观偏好：只改内存里的共享主题实例，场景原有主题引用与磁盘主题资源保持不变。
signal style_changed

const SECTION := "ui"
const THEME_PATH := "res://theme/app_theme.tres"
## 清透模式的气泡与时间条底色；扁平模式直接用主题里的语义色，不再各写一份。
const CRYSTAL_OWN_BUBBLE := Color(0.863, 0.949, 1, 0.74)
const CRYSTAL_OTHER_BUBBLE := Color(1, 1, 1, 0.75)
const CRYSTAL_TIME_CHIP := Color(0.91, 0.95, 0.98, 0.72)
## 全客户端布局间距阶梯：场景只使用这些值，避免 10/14/18 之类的漂移。
const SPACE_XS := 4.0
const SPACE_SM := 8.0
const SPACE_MD := 12.0
const SPACE_LG := 16.0
const SPACE_XL := 24.0
const SPACE_XXL := 40.0
const TOAST_COLORS := {
	"success": {"bg": Color(0.94, 1.0, 0.96, 1), "border": Color(0.18, 0.64, 0.40, 0.9)},
	"error": {"bg": Color(1.0, 0.95, 0.95, 1), "border": Color(0.78, 0.24, 0.24, 0.9)},
	"progress": {"bg": Color(0.95, 0.98, 1.0, 1), "border": Color(0.20, 0.52, 0.86, 0.9)},
	"info": {"bg": Color(1, 1, 1, 1), "border": Color(0.18, 0.48, 0.80, 0.9)},
}
var ui_style := "flat"
var icon_style := "svg"
var _store: Resource
var _icon_registry: Array[Dictionary] = []
var _theme: Theme = preload(THEME_PATH)

func configure(store: Resource) -> void:
	_store = store
	if _store != null:
		_store.load_settings()
		var style: String = str(_store.get_value(SECTION, "style", "flat"))
		var icons: String = str(_store.get_value(SECTION, "icons", "svg"))
		ui_style = style if style in ["flat", "crystal"] else "flat"
		icon_style = icons if icons in ["svg", "emoji"] else "svg"
	_apply_theme()

func save_preferences(style: String, icons: String) -> Error:
	if style not in ["flat", "crystal"] or icons not in ["svg", "emoji"]:
		return ERR_INVALID_PARAMETER
	if style == ui_style and icons == icon_style:
		return OK
	if _store == null:
		return ERR_UNCONFIGURED
	var old_style: Variant = _store.get_value(SECTION, "style", "flat")
	var old_icons: Variant = _store.get_value(SECTION, "icons", "svg")
	var theme_changed := ui_style != style
	_store.set_value(SECTION, "style", style)
	_store.set_value(SECTION, "icons", icons)
	var error: Error = _store.save_settings()
	if error != OK:
		_store.set_value(SECTION, "style", old_style)
		_store.set_value(SECTION, "icons", old_icons)
		return error
	ui_style = style
	icon_style = icons
	if theme_changed: _apply_theme()
	_refresh_icons()
	style_changed.emit()
	return OK

func is_crystal() -> bool:
	return ui_style == "crystal"

func uses_emoji() -> bool:
	return icon_style == "emoji"

## 入树前即可调用：所有场景已共用应用主题。
func apply_view(view: Node, icons: Dictionary = {}) -> void:
	for name in icons:
		register_icon(view.get_node("%" + name), icons[name])

func _apply_theme() -> void:
	_theme.set_block_signals(true)
	for state in ["normal", "hover", "pressed"]:
		var navigation := _theme.get_stylebox(state, "NavigationButton") as StyleBoxFlat
		navigation.content_margin_left = SPACE_SM
		navigation.content_margin_right = SPACE_SM
		navigation.content_margin_top = SPACE_XS
		navigation.content_margin_bottom = SPACE_XS
		navigation.set_corner_radius_all(12 if is_crystal() else 8)
		navigation.bg_color = {"normal": Color(0, 0, 0, 0), "hover": Color(0.87, 0.95, 0.99, 0.72 if is_crystal() else 1.0), "pressed": Color(0.87, 0.945, 0.992, 0.82 if is_crystal() else 1.0)}[state]
	_theme.set_font_size("font_size", "NavigationButton", 12)
	_theme.set_constant("h_separation", "NavigationButton", 8)
	_apply_panel_themes()
	_apply_dropdown_styles()
	_apply_action_styles()
	_apply_chat_icon_styles()
	_theme.set_block_signals(false)
	_theme.emit_changed()

## 重复注册用于播放/暂停这类需要切换图标的按钮。
func register_icon(button: Button, name: String) -> void:
	var alive: Array[Dictionary] = []
	for entry in _icon_registry:
		var target = entry.button.get_ref()
		if target != null and target != button: alive.append(entry)
	alive.append({"button":weakref(button), "name":name})
	_icon_registry = alive
	_apply_icon(button, name)

func _refresh_icons() -> void:
	var alive: Array[Dictionary] = []
	for entry in _icon_registry:
		var button = entry.button.get_ref()
		if button == null: continue
		_apply_icon(button, entry.name)
		alive.append(entry)
	_icon_registry = alive

func _apply_icon(button: Button, name: String) -> void:
	var suffix := "_emoji.png" if uses_emoji() else ".svg"
	button.icon = load("res://assets/ui/icons/" + name + suffix)
	button.expand_icon = false
	button.add_theme_constant_override("icon_max_width", 20)
	button.add_theme_color_override("icon_disabled_color", Color(1, 1, 1, 0.4))

## 气泡底色：扁平模式沿用主题语义色，清透模式换成半透明冰蓝。
func bubble_color(own: bool, base: Color) -> Color:
	if not is_crystal():
		return base
	return CRYSTAL_OWN_BUBBLE if own else CRYSTAL_OTHER_BUBBLE

func time_chip_color(base: Color) -> Color:
	return CRYSTAL_TIME_CHIP if is_crystal() else base

func apply_bubble_style(stylebox: StyleBoxFlat) -> void:
	if is_crystal():
		stylebox.set_corner_radius_all(12)
		stylebox.border_width_left = 1
		stylebox.border_width_top = 1
		stylebox.border_width_right = 1
		stylebox.border_width_bottom = 1
		stylebox.border_color = Color(0.72, 0.88, 1.0, 0.45)
		stylebox.shadow_color = Color(0.12, 0.28, 0.42, 0.08)
		stylebox.shadow_size = 8
		stylebox.shadow_offset = Vector2(0, 3)
		var crystal_color := stylebox.bg_color
		crystal_color.a = minf(crystal_color.a, 0.94)
		stylebox.bg_color = crystal_color
	else:
		stylebox.set_corner_radius_all(8)
		stylebox.border_width_left = 1
		stylebox.border_width_top = 1
		stylebox.border_width_right = 1
		stylebox.border_width_bottom = 1
		stylebox.border_color = Color(0.84, 0.90, 0.95, 0.9)
		var flat_color := stylebox.bg_color
		flat_color.a = 1.0
		stylebox.bg_color = flat_color
		_apply_shadow(stylebox)

func apply_surface_style(stylebox: StyleBoxFlat) -> void:
	stylebox.set_corner_radius_all(12 if is_crystal() else 8)
	stylebox.border_width_left = 1
	stylebox.border_width_top = 1
	stylebox.border_width_right = 1
	stylebox.border_width_bottom = 1
	stylebox.border_color = Color(0.72, 0.88, 1.0, 0.58) if is_crystal() else Color(0.84, 0.90, 0.95, 0.9)
	var surface_color := stylebox.bg_color
	surface_color.a = 0.92 if is_crystal() else 1.0
	stylebox.bg_color = surface_color
	_apply_shadow(stylebox)

func apply_post_style(stylebox: StyleBoxFlat, selected: bool) -> void:
	stylebox.set_corner_radius_all(12 if is_crystal() else 8)
	stylebox.border_width_left = 3 if selected else 1
	stylebox.border_width_top = 1
	stylebox.border_width_right = 1
	stylebox.border_width_bottom = 1
	stylebox.border_color = Color(0.4, 0.8, 1.0, 0.9) if selected else (Color(0.72, 0.88, 1.0, 0.5) if is_crystal() else Color(0.84, 0.90, 0.95, 0.9))
	var post_color := stylebox.bg_color
	post_color.a = 0.94 if is_crystal() else 1.0
	stylebox.bg_color = post_color
	_apply_shadow(stylebox)

func apply_input_style(stylebox: StyleBoxFlat) -> void:
	stylebox.set_corner_radius_all(12 if is_crystal() else 8)
	stylebox.border_width_left = 1
	stylebox.border_width_top = 1
	stylebox.border_width_right = 1
	stylebox.border_width_bottom = 1
	stylebox.border_color = Color(0.72, 0.88, 1.0, 0.62) if is_crystal() else Color(0.84, 0.90, 0.95, 0.9)
	var input_color := stylebox.bg_color
	input_color.a = 0.9 if is_crystal() else 1.0
	stylebox.bg_color = input_color
	_apply_shadow(stylebox)
	stylebox.shadow_size = 3 if is_crystal() else 0
	stylebox.shadow_offset = Vector2(0, 1) if is_crystal() else Vector2.ZERO

## Toast 的语义色只在这里维护；调用方只传 kind，不再各自复制一套 StyleBox。
func apply_toast_style(stylebox: StyleBoxFlat, kind: String) -> void:
	if stylebox == null:
		return
	apply_surface_style(stylebox)
	stylebox.content_margin_left = SPACE_LG
	stylebox.content_margin_right = SPACE_LG
	stylebox.content_margin_top = SPACE_SM
	stylebox.content_margin_bottom = SPACE_SM
	var palette: Dictionary = TOAST_COLORS.get(kind, TOAST_COLORS.info)
	var background: Color = palette.get("bg", Color.WHITE)
	background.a = 0.94 if is_crystal() else 1.0
	stylebox.bg_color = background
	stylebox.border_color = palette.get("border", Color(0.18, 0.48, 0.80, 0.9))
	stylebox.set_border_width_all(1)

func _apply_shadow(stylebox: StyleBoxFlat) -> void:
	if is_crystal():
		stylebox.shadow_color = Color(0.1, 0.25, 0.4, 0.08)
		stylebox.shadow_size = 12
		stylebox.shadow_offset = Vector2(0, 4)
	else:
		stylebox.shadow_color = Color(0, 0, 0, 0)
		stylebox.shadow_size = 0
		stylebox.shadow_offset = Vector2.ZERO

func _apply_panel_themes() -> void:
	_apply_surface_group("panel", ["AppSurface", "PanelContainer", "DialogSurface", "DropdownPopup",
		"PopupPanel", "PopupMenu", "LoginSurface", "LoginDialog", "ModelCard", "SettingsCard"])
	_apply_modal_surface()
	_apply_chat_surface()
	_apply_surface_group("panel", ["DynamicsSurface", "DynamicsDetailSurface"])
	_apply_toast_surface()
	_apply_surface_padding()
	_apply_surface_group("normal", ["TerminalSurface"])
	_apply_post_group()


func _apply_toast_surface() -> void:
	if not _theme.has_stylebox("panel", "SettingsToast"):
		return
	var toast := _theme.get_stylebox("panel", "SettingsToast") as StyleBoxFlat
	if toast != null:
		apply_toast_style(toast, "info")


## 布局间距按角色统一：卡片 16、弹窗 24、Toast 16×8。
func _apply_surface_padding() -> void:
	for kind in ["AppSurface", "PanelContainer", "ModelCard", "SettingsCard"]:
		_set_panel_padding(kind, SPACE_LG, SPACE_LG)
	_set_panel_padding("DialogSurface", SPACE_XL, SPACE_XL)
	_set_panel_padding("SettingsDialogSurface", SPACE_XL, SPACE_XL)


func _set_panel_padding(kind: String, horizontal: float, vertical: float) -> void:
	if not _theme.has_stylebox("panel", kind):
		return
	var panel := _theme.get_stylebox("panel", kind) as StyleBoxFlat
	if panel == null:
		return
	panel.content_margin_left = horizontal
	panel.content_margin_right = horizontal
	panel.content_margin_top = vertical
	panel.content_margin_bottom = vertical


func _apply_surface_group(property: String, kinds: Array) -> void:
	for kind in kinds:
		if not _theme.has_stylebox(property, kind):
			continue
		var panel := _theme.get_stylebox(property, kind) as StyleBoxFlat
		if panel != null:
			apply_surface_style(panel)


## 下拉是跨页面的选择语义，统一使用同一套触发器、弹层与选项状态。
func _apply_dropdown_styles() -> void:
	_apply_dropdown_trigger_styles()
	_apply_dropdown_popup_style()
	_apply_dropdown_item_styles()


func _apply_dropdown_trigger_styles() -> void:
	var trigger_radius := 12 if is_crystal() else 8
	for state in ["normal", "hover", "pressed", "disabled", "focus"]:
		if not _theme.has_stylebox(state, "DropdownTrigger"):
			continue
		var trigger := _theme.get_stylebox(state, "DropdownTrigger") as StyleBoxFlat
		if trigger != null:
			trigger.set_corner_radius_all(trigger_radius)


func _apply_dropdown_popup_style() -> void:
	if _theme.has_stylebox("panel", "DropdownPopup"):
		var popup := _theme.get_stylebox("panel", "DropdownPopup") as StyleBoxFlat
		if popup != null:
			popup.set_corner_radius_all(12 if is_crystal() else 8)
			popup.border_color = Color(0.72, 0.88, 1.0, 0.58) if is_crystal() else Color(0.776, 0.827, 0.867, 1)
			popup.shadow_color = Color(0.06, 0.16, 0.23, 0.16)
			popup.shadow_size = 12 if is_crystal() else 8
			popup.shadow_offset = Vector2(0, 4) if is_crystal() else Vector2(0, 3)


func _apply_dropdown_item_styles() -> void:
	for kind in ["DropdownItem", "DropdownItemSelected"]:
		for state in ["normal", "hover", "pressed", "disabled", "focus"]:
			if not _theme.has_stylebox(state, kind):
				continue
			var item := _theme.get_stylebox(state, kind) as StyleBoxFlat
			if item != null:
				item.set_corner_radius_all(8 if is_crystal() else 6)


## 设置窗与确认/错误弹窗使用独立变体，发布浮层继续沿用原 DialogSurface。
func _apply_modal_surface() -> void:
	if not _theme.has_stylebox("panel", "SettingsDialogSurface"):
		return
	var panel := _theme.get_stylebox("panel", "SettingsDialogSurface") as StyleBoxFlat
	if panel == null:
		return
	apply_surface_style(panel)
	panel.set_border_width_all(0)
	panel.content_margin_left = SPACE_XL
	panel.content_margin_right = SPACE_XL
	panel.content_margin_top = SPACE_XL
	panel.content_margin_bottom = SPACE_XL
	panel.shadow_color = Color(0.063, 0.157, 0.227, 0.16)
	panel.shadow_size = 14
	panel.shadow_offset = Vector2(0, 6)


## 主操作与设置操作使用独立 StyleBox，避免牵动全局 Button/Control 样式。
func _apply_action_styles() -> void:
	for variant in ["PrimaryButton", "SettingsButton", "SettingsPrimaryButton"]:
		for state in ["normal", "hover", "pressed", "disabled", "focus"]:
			if not _theme.has_stylebox(state, variant):
				continue
			var style := _theme.get_stylebox(state, variant) as StyleBoxFlat
			if style != null:
				apply_action_style(style, state)


func apply_action_style(stylebox: StyleBoxFlat, state: String) -> void:
	stylebox.set_corner_radius_all(12 if is_crystal() else 8)
	if state != "focus":
		var color := stylebox.bg_color
		color.a = minf(color.a, 0.94) if is_crystal() else 1.0
		stylebox.bg_color = color
	if is_crystal() and state in ["normal", "hover", "pressed"]:
		stylebox.shadow_color = Color(0.063, 0.157, 0.227, 0.1)
		stylebox.shadow_size = 6
		stylebox.shadow_offset = Vector2(0, 2)
	else:
		stylebox.shadow_color = Color(0, 0, 0, 0)
		stylebox.shadow_size = 0
		stylebox.shadow_offset = Vector2.ZERO


func _apply_chat_icon_styles() -> void:
	if not _theme.has_stylebox("hover", "ChatIconButton"):
		return
	var radius := 12 if is_crystal() else 8
	for state in ["normal", "hover", "pressed", "disabled", "focus"]:
		var style := _theme.get_stylebox(state, "ChatIconButton") as StyleBoxFlat
		if style == null:
			continue
		style.set_corner_radius_all(radius)
		style.content_margin_left = 0
		style.content_margin_top = 0
		style.content_margin_right = 0
		style.content_margin_bottom = 0
		if state in ["hover", "pressed", "focus"]:
			var color := style.bg_color
			color.a = (0.84 if state == "pressed" else 0.72) if is_crystal() else 1.0
			style.bg_color = color
		if is_crystal() and state in ["hover", "pressed"]:
			style.shadow_color = Color(0.063, 0.157, 0.227, 0.06)
			style.shadow_size = 3
			style.shadow_offset = Vector2(0, 1)
		else:
			style.shadow_color = Color(0, 0, 0, 0)
			style.shadow_size = 0
			style.shadow_offset = Vector2.ZERO

## 聊天区保持原有的直角/无边框语义，只让清透模式透出背景，不改几何。
func _apply_chat_surface() -> void:
	if not _theme.has_stylebox("panel", "ChatSurface"):
		return
	var chat := _theme.get_stylebox("panel", "ChatSurface") as StyleBoxFlat
	if chat == null:
		return
	var color := chat.bg_color
	color.a = 0.92 if is_crystal() else 1.0
	chat.bg_color = color

func _apply_post_group() -> void:
	for kind in ["normal", "selected"]:
		if not _theme.has_stylebox(kind, "DynamicsPost"):
			continue
		var post := _theme.get_stylebox(kind, "DynamicsPost") as StyleBoxFlat
		if post != null:
			apply_post_style(post, kind == "selected")
