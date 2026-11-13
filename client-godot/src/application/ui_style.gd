extends RefCounted
## Central theme & appearance state engine backed by DesignTokens.
signal style_changed

const Tokens = preload("res://src/ui/design_tokens.gd")
const SECTION := "ui"
const THEME_PATH := "res://theme/app_theme.tres"

const CRYSTAL_OWN_BUBBLE := Tokens.BUBBLE_OWN_CRYSTAL
const CRYSTAL_OTHER_BUBBLE := Tokens.BUBBLE_OTHER_CRYSTAL
const CRYSTAL_TIME_CHIP := Tokens.TIME_CHIP_CRYSTAL

const SPACE_XS := Tokens.SPACE_XS
const SPACE_SM := Tokens.SPACE_SM
const SPACE_MD := Tokens.SPACE_MD
const SPACE_LG := Tokens.SPACE_LG
const SPACE_XL := Tokens.SPACE_XL
const SPACE_XXL := Tokens.SPACE_XXL

const TOAST_COLORS := Tokens.TOAST_COLORS
const STATUS_PALETTES := Tokens.STATUS_PALETTES

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
	if theme_changed:
		_apply_theme()
	_refresh_icons()
	style_changed.emit()
	return OK


func is_crystal() -> bool:
	return ui_style == "crystal"


func uses_emoji() -> bool:
	return icon_style == "emoji"


func apply_view(view: Node, icons: Dictionary = {}) -> void:
	for key in icons:
		register_icon(view.get_node("%" + key), icons[key])


func register_icon(button: Button, icon_name: String) -> void:
	var alive: Array[Dictionary] = []
	for entry in _icon_registry:
		var target = entry.button.get_ref()
		if target != null and target != button:
			alive.append(entry)
	alive.append({"button": weakref(button), "name": icon_name})
	_icon_registry = alive
	_apply_icon(button, icon_name)


func _refresh_icons() -> void:
	var alive: Array[Dictionary] = []
	for entry in _icon_registry:
		var button = entry.button.get_ref()
		if button == null:
			continue
		_apply_icon(button, entry.name)
		alive.append(entry)
	_icon_registry = alive


func _apply_icon(button: Button, icon_name: String) -> void:
	button.icon = load(Tokens.icon_path(icon_name, uses_emoji()))
	button.expand_icon = false
	button.add_theme_constant_override("icon_max_width", Tokens.ICON_SIZE)
	button.add_theme_color_override("icon_disabled_color", Color(0.43, 0.51, 0.55, 0.68))


static func status_palette(kind: String) -> Dictionary:
	return Tokens.STATUS_PALETTES.get(kind, Tokens.STATUS_PALETTES.muted)


static func apply_banner_box(stylebox: StyleBoxFlat, kind: String, crystal: bool = false) -> void:
	if stylebox == null:
		return
	var palette := status_palette(kind)
	var bg: Color = palette.bg
	bg.a = 0.92 if crystal else 1.0
	stylebox.bg_color = bg
	stylebox.border_color = palette.border
	stylebox.set_border_width_all(1)
	stylebox.set_corner_radius_all(Tokens.surface_radius(crystal))
	stylebox.content_margin_left = SPACE_MD
	stylebox.content_margin_right = SPACE_MD
	stylebox.content_margin_top = SPACE_SM
	stylebox.content_margin_bottom = SPACE_SM


func bubble_color(own: bool, base: Color) -> Color:
	if not is_crystal():
		return base
	return Tokens.BUBBLE_OWN_CRYSTAL if own else Tokens.BUBBLE_OTHER_CRYSTAL


func time_chip_color(base: Color) -> Color:
	return Tokens.TIME_CHIP_CRYSTAL if is_crystal() else base


func apply_bubble_style(stylebox: StyleBoxFlat) -> void:
	stylebox.set_corner_radius_all(Tokens.surface_radius(is_crystal()))
	stylebox.set_border_width_all(1)
	stylebox.border_color = Tokens.BORDER_CRYSTAL_SOFT if is_crystal() else Tokens.BORDER_FLAT
	var color := stylebox.bg_color
	color.a = minf(color.a, 0.94) if is_crystal() else 1.0
	stylebox.bg_color = color
	if is_crystal():
		stylebox.shadow_color = Tokens.SHADOW_BUBBLE
		stylebox.shadow_size = 8
		stylebox.shadow_offset = Vector2(0, 3)
	else:
		_clear_shadow(stylebox)


func apply_surface_style(stylebox: StyleBoxFlat) -> void:
	stylebox.set_corner_radius_all(Tokens.surface_radius(is_crystal()))
	stylebox.set_border_width_all(1)
	stylebox.border_color = Tokens.BORDER_CRYSTAL if is_crystal() else Tokens.BORDER_FLAT
	var color := stylebox.bg_color
	color.a = 0.92 if is_crystal() else 1.0
	stylebox.bg_color = color
	_apply_shadow(stylebox)


func apply_post_style(stylebox: StyleBoxFlat, selected: bool) -> void:
	stylebox.set_corner_radius_all(Tokens.surface_radius(is_crystal()))
	stylebox.set_border_width_all(2 if selected else 1)
	if selected:
		stylebox.border_color = Color(0.4, 0.8, 1.0, 0.9)
	else:
		stylebox.border_color = Color(0.72, 0.88, 1.0, 0.5) if is_crystal() else Tokens.BORDER_FLAT
	var color := stylebox.bg_color
	color.a = 0.94 if is_crystal() else 1.0
	stylebox.bg_color = color
	_apply_shadow(stylebox)


func apply_input_style(stylebox: StyleBoxFlat) -> void:
	stylebox.set_corner_radius_all(Tokens.surface_radius(is_crystal()))
	stylebox.set_border_width_all(1)
	stylebox.border_color = Color(0.72, 0.88, 1.0, 0.62) if is_crystal() else Tokens.BORDER_FLAT
	var color := stylebox.bg_color
	color.a = 0.90 if is_crystal() else 1.0
	stylebox.bg_color = color
	stylebox.shadow_color = Tokens.SHADOW_CARD if is_crystal() else Tokens.SHADOW_CLEAR
	stylebox.shadow_size = 3 if is_crystal() else 0
	stylebox.shadow_offset = Vector2(0, 1) if is_crystal() else Vector2.ZERO


func apply_toast_style(stylebox: StyleBoxFlat, kind: String) -> void:
	if stylebox == null:
		return
	apply_surface_style(stylebox)
	stylebox.content_margin_left = SPACE_LG
	stylebox.content_margin_right = SPACE_LG
	stylebox.content_margin_top = SPACE_SM
	stylebox.content_margin_bottom = SPACE_SM
	var palette: Dictionary = Tokens.TOAST_COLORS.get(kind, Tokens.TOAST_COLORS.info)
	var background: Color = palette.get("bg", Color.WHITE)
	background.a = 0.94 if is_crystal() else 1.0
	stylebox.bg_color = background
	stylebox.border_color = palette.get("border", Color(0.18, 0.48, 0.80, 0.9))
	stylebox.set_border_width_all(1)


func apply_action_style(stylebox: StyleBoxFlat, state: String) -> void:
	stylebox.set_corner_radius_all(Tokens.surface_radius(is_crystal()))
	if state != "focus":
		var color := stylebox.bg_color
		color.a = minf(color.a, 0.94) if is_crystal() else 1.0
		stylebox.bg_color = color
	if is_crystal() and state in ["normal", "hover", "pressed"]:
		stylebox.shadow_color = Tokens.SHADOW_ACTION
		stylebox.shadow_size = 6
		stylebox.shadow_offset = Vector2(0, 2)
	else:
		_clear_shadow(stylebox)


func apply_navigation_rail_style(stylebox: StyleBoxFlat) -> void:
	if stylebox == null:
		return
	stylebox.bg_color = Tokens.NAV_RAIL_BG_CRYSTAL if is_crystal() else Tokens.NAV_RAIL_BG_FLAT
	stylebox.border_color = Tokens.NAV_RAIL_BORDER_CRYSTAL if is_crystal() else Tokens.NAV_RAIL_BORDER_FLAT


func backdrop_gradient_colors() -> PackedColorArray:
	if is_crystal():
		return PackedColorArray([Tokens.BACKDROP_START_CRYSTAL, Tokens.BACKDROP_END_CRYSTAL])
	return PackedColorArray([Tokens.BACKDROP_START_FLAT, Tokens.BACKDROP_END_FLAT])


func apply_chat_card_style(stylebox: StyleBoxFlat) -> void:
	if stylebox == null:
		return
	apply_surface_style(stylebox)
	stylebox.bg_color = Tokens.CHAT_SURFACE_CRYSTAL if is_crystal() else Tokens.SURFACE_WHITE
	if is_crystal():
		stylebox.set_corner_radius_all(0)
		stylebox.set_border_width_all(0)
		_clear_shadow(stylebox)


func apply_composer_style(stylebox: StyleBoxFlat) -> void:
	if stylebox == null:
		return
	stylebox.bg_color = Tokens.CHAT_COMPOSER_CRYSTAL if is_crystal() else Tokens.SURFACE_WHITE
	stylebox.set_corner_radius_all(Tokens.surface_radius(is_crystal()))
	stylebox.corner_radius_top_left = 0
	stylebox.corner_radius_top_right = 0


func _apply_theme() -> void:
	_theme.set_block_signals(true)
	_apply_navigation_styles()
	_apply_panel_themes()
	_apply_dropdown_styles()
	_apply_action_styles()
	_apply_chat_icon_styles()
	_theme.set_block_signals(false)
	_theme.emit_changed()


func _apply_navigation_styles() -> void:
	var colors := {
		"normal": Color(0, 0, 0, 0),
		"hover": Color(0.87, 0.95, 0.99, 0.72 if is_crystal() else 1.0),
		"pressed": Color(0.87, 0.945, 0.992, 0.82 if is_crystal() else 1.0),
	}
	for state in colors:
		var navigation := _theme.get_stylebox(state, "NavigationButton") as StyleBoxFlat
		if navigation == null:
			continue
		navigation.content_margin_left = SPACE_SM
		navigation.content_margin_right = SPACE_SM
		navigation.content_margin_top = SPACE_XS
		navigation.content_margin_bottom = SPACE_XS
		navigation.set_corner_radius_all(Tokens.surface_radius(is_crystal()))
		navigation.bg_color = colors[state]
	_theme.set_font_size("font_size", "NavigationButton", 12)
	_theme.set_constant("h_separation", "NavigationButton", 8)


func _apply_panel_themes() -> void:
	_apply_surface_group("panel", ["AppSurface", "PanelContainer", "DropdownPopup", "PopupPanel", "PopupMenu", "ModelCard", "SettingsCard", "DynamicsSurface", "DynamicsDetailSurface"])
	_apply_dialog_surfaces()
	_apply_chat_surface()
	_apply_window_shell_surface()
	_apply_banner_surface()
	_apply_toast_surface()
	_apply_surface_padding()
	_apply_terminal_surface()
	_apply_post_group()


func _apply_window_shell_surface() -> void:
	var shell := _stylebox_or_null("panel", "WindowShellSurface")
	if shell == null:
		return
	shell.set_corner_radius_all(0)
	shell.set_border_width_all(0)
	_clear_shadow(shell)
	shell.bg_color = Tokens.WINDOW_BG_CRYSTAL if is_crystal() else Tokens.WINDOW_BG_FLAT


func _apply_banner_surface() -> void:
	var banner := _stylebox_or_null("panel", "StatusBannerSurface")
	if banner != null:
		apply_banner_box(banner, "muted", is_crystal())


func _apply_terminal_surface() -> void:
	var terminal := _stylebox_or_null("normal", "TerminalSurface")
	if terminal == null:
		return
	terminal.set_corner_radius_all(Tokens.surface_radius(is_crystal()))
	terminal.set_border_width_all(1)
	terminal.border_color = Color(0.145098, 0.215686, 0.27451, 1)
	terminal.bg_color = Color(0.06666667, 0.09803922, 0.13725491, 1.0)
	_clear_shadow(terminal)


func _apply_dialog_surfaces() -> void:
	for kind in ["DialogSurface", "LoginDialog"]:
		var panel := _stylebox_or_null("panel", kind)
		if panel == null:
			continue
		apply_surface_style(panel)
		panel.bg_color = Color(1, 1, 1, 1)
		if kind == "LoginDialog":
			_clear_shadow(panel)
	_apply_modal_surface()


func _apply_modal_surface() -> void:
	var panel := _stylebox_or_null("panel", "SettingsDialogSurface")
	if panel == null:
		return
	apply_surface_style(panel)
	panel.bg_color = Color(1, 1, 1, 1)
	panel.set_border_width_all(0)
	panel.content_margin_left = SPACE_XL
	panel.content_margin_right = SPACE_XL
	panel.content_margin_top = SPACE_XL
	panel.content_margin_bottom = SPACE_XL
	panel.shadow_color = Tokens.SHADOW_DIALOG
	panel.shadow_size = 14
	panel.shadow_offset = Vector2(0, 6)


func _apply_toast_surface() -> void:
	var toast := _stylebox_or_null("panel", "SettingsToast")
	if toast != null:
		apply_toast_style(toast, "info")


func _apply_surface_padding() -> void:
	for kind in ["AppSurface", "PanelContainer", "ModelCard", "SettingsCard"]:
		_set_panel_padding(kind, SPACE_LG, SPACE_LG)
	_set_panel_padding("DialogSurface", SPACE_XL, SPACE_XL)
	_set_panel_padding("SettingsDialogSurface", SPACE_XL, SPACE_XL)


func _set_panel_padding(kind: String, horizontal: float, vertical: float) -> void:
	var panel := _stylebox_or_null("panel", kind)
	if panel == null:
		return
	panel.content_margin_left = horizontal
	panel.content_margin_right = horizontal
	panel.content_margin_top = vertical
	panel.content_margin_bottom = vertical


func _apply_surface_group(property: String, kinds: Array) -> void:
	for kind in kinds:
		var panel := _stylebox_or_null(property, kind)
		if panel != null:
			apply_surface_style(panel)


func _apply_dropdown_styles() -> void:
	var trigger_radius := Tokens.surface_radius(is_crystal())
	for state in ["normal", "hover", "pressed", "disabled", "focus"]:
		var trigger := _stylebox_or_null(state, "DropdownTrigger")
		if trigger != null:
			trigger.set_corner_radius_all(trigger_radius)
	var popup := _stylebox_or_null("panel", "DropdownPopup")
	if popup != null:
		popup.bg_color = Color(1, 1, 1, 1)
		popup.set_corner_radius_all(trigger_radius)
		popup.border_color = Tokens.BORDER_CRYSTAL if is_crystal() else Color(0.776, 0.827, 0.867, 1)
		popup.shadow_color = Tokens.SHADOW_DIALOG
		popup.shadow_size = 12 if is_crystal() else 8
		popup.shadow_offset = Vector2(0, 4) if is_crystal() else Vector2(0, 3)
	var item_radius := Tokens.dropdown_item_radius(is_crystal())
	for kind in ["DropdownItem", "DropdownItemSelected"]:
		for state in ["normal", "hover", "pressed", "disabled", "focus"]:
			var item := _stylebox_or_null(state, kind)
			if item != null:
				item.set_corner_radius_all(item_radius)


func _apply_action_styles() -> void:
	for variant in ["PrimaryButton", "SettingsButton", "SettingsPrimaryButton", "SettingsDangerButton", "ChatPillButton"]:
		for state in ["normal", "hover", "pressed", "disabled", "focus"]:
			var style := _stylebox_or_null(state, variant)
			if style != null:
				apply_action_style(style, state)
	var link_radius := 8 if is_crystal() else 6
	for state in ["normal", "hover", "pressed", "disabled"]:
		var link := _stylebox_or_null(state, "InlineLinkButton")
		if link != null:
			link.set_corner_radius_all(link_radius)


func _apply_chat_icon_styles() -> void:
	if not _theme.has_stylebox("hover", "ChatIconButton"):
		return
	var radius := Tokens.surface_radius(is_crystal())
	for state in ["normal", "hover", "pressed", "disabled", "focus"]:
		var style := _stylebox_or_null(state, "ChatIconButton")
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
			_clear_shadow(style)


func _apply_chat_surface() -> void:
	var chat := _stylebox_or_null("panel", "ChatSurface")
	if chat == null:
		return
	chat.set_corner_radius_all(0 if is_crystal() else Tokens.RADIUS_FLAT)
	chat.set_border_width_all(0 if is_crystal() else 1)
	chat.border_color = Tokens.BORDER_FLAT
	var color := chat.bg_color
	color.a = 0.92 if is_crystal() else 1.0
	chat.bg_color = color
	_clear_shadow(chat)


func _apply_post_group() -> void:
	for kind in ["normal", "selected"]:
		var post := _stylebox_or_null(kind, "DynamicsPost")
		if post != null:
			apply_post_style(post, kind == "selected")


func _apply_shadow(stylebox: StyleBoxFlat) -> void:
	if is_crystal():
		stylebox.shadow_color = Tokens.SHADOW_CARD
		stylebox.shadow_size = 12
		stylebox.shadow_offset = Vector2(0, 4)
	else:
		_clear_shadow(stylebox)


func _clear_shadow(stylebox: StyleBoxFlat) -> void:
	stylebox.shadow_color = Tokens.SHADOW_CLEAR
	stylebox.shadow_size = 0
	stylebox.shadow_offset = Vector2.ZERO


func _stylebox_or_null(state: String, kind: String) -> StyleBoxFlat:
	if not _theme.has_stylebox(state, kind):
		return null
	return _theme.get_stylebox(state, kind) as StyleBoxFlat
