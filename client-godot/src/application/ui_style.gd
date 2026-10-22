extends RefCounted
## Application-owned preferences. Update the shared theme in memory only;
## keep every scene's original theme reference and the theme asset on disk.
signal style_changed

const SECTION := "ui"
const THEME_PATH := "res://theme/app_theme.tres"
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

## Safe before entering the tree; all scenes already share the app theme.
func apply_view(view: Node, icons: Dictionary = {}) -> void:
	for name in icons:
		register_icon(view.get_node("%" + name), icons[name])

func _apply_theme() -> void:
	_theme.set_block_signals(true)
	for state in ["normal", "hover", "pressed"]:
		var navigation := _theme.get_stylebox(state, "NavigationButton") as StyleBoxFlat
		navigation.content_margin_left = 6
		navigation.content_margin_right = 6
		navigation.content_margin_top = 5
		navigation.content_margin_bottom = 5
		navigation.set_corner_radius_all(12 if is_crystal() else 8)
		navigation.bg_color = {"normal": Color(0, 0, 0, 0), "hover": Color(0.87, 0.95, 0.99, 0.72 if is_crystal() else 1.0), "pressed": Color(0.87, 0.945, 0.992, 0.82 if is_crystal() else 1.0)}[state]
	_theme.set_font_size("font_size", "NavigationButton", 12)
	_theme.set_constant("h_separation", "NavigationButton", 8)
	_apply_panel_themes()
	_theme.set_block_signals(false)
	_theme.emit_changed()

## Updating a registration is used by the play/pause button.
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
	for kind in ["AppSurface", "PanelContainer", "DialogSurface", "DropdownPopup", "PopupPanel", "PopupMenu", "LoginSurface", "LoginDialog", "ModelCard"]:
		if _theme.has_stylebox("panel", kind):
			var panel := _theme.get_stylebox("panel", kind) as StyleBoxFlat
			if panel != null: apply_surface_style(panel)
	for kind in ['normal', 'selected']:
		if _theme.has_stylebox(kind, 'DynamicsPost'):
			var post := _theme.get_stylebox(kind, 'DynamicsPost') as StyleBoxFlat
			if post != null: apply_post_style(post, kind == 'selected')
