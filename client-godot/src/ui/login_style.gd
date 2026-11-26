extends RefCounted
## Login-only visual overrides ported from the backup client.

const Tokens = preload("res://src/ui/design_tokens.gd")
const THEME := preload("res://theme/app_theme.tres")
const STATES := ["normal", "hover", "pressed", "disabled", "focus"]

const SURFACE_COLOR := Tokens.LOGIN_SURFACE_COLOR
const AVATAR_BORDER := Tokens.LOGIN_AVATAR_BORDER
const AVATAR_SHADOW := Tokens.LOGIN_AVATAR_SHADOW
const DIALOG_SHADOW := Tokens.LOGIN_DIALOG_SHADOW
const ACTION_SHADOW := Tokens.LOGIN_ACTION_SHADOW
const POPUP_BORDER_FLAT := Tokens.LOGIN_POPUP_BORDER_FLAT
const POPUP_BORDER_CRYSTAL := Tokens.LOGIN_POPUP_BORDER_CRYSTAL
const RADIUS_FLAT := Tokens.RADIUS_LOGIN_FLAT
const RADIUS_CRYSTAL := Tokens.RADIUS_LOGIN_CRYSTAL


static func apply_account_view(page: Control, crystal: bool = false) -> void:
	_apply_page(page)
	_apply_popup(page.get_node_or_null("%MenuPopup"), crystal)
	_apply_popup(page.get_node_or_null("%HistoryPopup"), crystal)
	_apply_dialog_window(page.get_node_or_null("%ServerDialog"),
		["ServerProbe", "ServerDefault", "ServerCancel", "ServerSave"], crystal)
	_apply_dialog_window(page.get_node_or_null("%RemoveAccountDialog"),
		["Confirm", "Cancel", "SaveAndClose"], crystal)


static func apply_dialog(panel: PanelContainer, buttons: Array, crystal: bool = false) -> void:
	if panel != null:
		var box := _copy("panel", "SettingsDialogSurface")
		if box != null:
			box.bg_color = Color(1, 1, 1, 1)
			box.set_border_width_all(0)
			box.set_corner_radius_all(RADIUS_CRYSTAL if crystal else RADIUS_FLAT)
			box.content_margin_left = 24
			box.content_margin_top = 24
			box.content_margin_right = 24
			box.content_margin_bottom = 24
			box.shadow_color = DIALOG_SHADOW
			box.shadow_size = 14
			box.shadow_offset = Vector2(0, 6)
			panel.add_theme_stylebox_override("panel", box)
	for button in buttons:
		if button is Button:
			apply_button(button as Button, crystal)


static func clear_dialog(panel: PanelContainer, buttons: Array) -> void:
	if panel != null:
		panel.remove_theme_stylebox_override("panel")
	for button in buttons:
		if button is Button:
			for state in STATES:
				(button as Button).remove_theme_stylebox_override(state)


static func apply_button(button: Button, crystal: bool = false) -> void:
	var variation := String(button.theme_type_variation)
	if variation.is_empty():
		variation = button.get_class()
	for state in STATES:
		var box := _copy(state, variation)
		if box == null:
			continue
		box.set_corner_radius_all(RADIUS_CRYSTAL if crystal else RADIUS_FLAT)
		if crystal and state in ["normal", "hover", "pressed"]:
			box.shadow_color = ACTION_SHADOW
			box.shadow_size = 6
			box.shadow_offset = Vector2(0, 2)
		button.add_theme_stylebox_override(state, box)


static func _apply_page(page: Control) -> void:
	var surface := _copy("panel", "LoginSurface")
	if surface != null:
		surface.bg_color = SURFACE_COLOR
		page.add_theme_stylebox_override("panel", surface)
	var avatar_ring := page.find_child("AvatarRing", true, false) as Control
	if avatar_ring != null:
		var ring := StyleBoxFlat.new()
		ring.bg_color = Color("e1f3fe")
		ring.set_corner_radius_all(64)
		ring.content_margin_left = 6
		ring.content_margin_top = 6
		ring.content_margin_right = 6
		ring.content_margin_bottom = 6
		avatar_ring.add_theme_stylebox_override("panel", ring)
	var avatar_frame := page.find_child("AvatarFrame", true, false) as Control
	if avatar_frame == null:
		return
	var avatar := _copy("panel", "LoginAvatar")
	if avatar == null:
		return
	avatar.set_border_width_all(3)
	avatar.border_color = Tokens.ACCENT
	avatar.set_corner_radius_all(56)
	avatar.shadow_size = 0
	avatar_frame.add_theme_stylebox_override("panel", avatar)


static func _apply_popup(popup: Node, crystal: bool) -> void:
	if popup == null:
		return
	var box := _copy("panel", "DropdownPopup")
	if box == null:
		return
	box.set_corner_radius_all(RADIUS_CRYSTAL if crystal else RADIUS_FLAT)
	box.border_color = POPUP_BORDER_CRYSTAL if crystal else POPUP_BORDER_FLAT
	box.shadow_color = DIALOG_SHADOW
	box.shadow_size = 12 if crystal else 8
	box.shadow_offset = Vector2(0, 4) if crystal else Vector2(0, 3)
	popup.call("add_theme_stylebox_override", "panel", box)


static func _apply_dialog_window(dialog: Node, button_names: Array, crystal: bool) -> void:
	if dialog == null:
		return
	var panel := dialog.find_child("Panel", true, false) as PanelContainer
	var buttons: Array[Button] = []
	for name in button_names:
		var button := dialog.find_child(str(name), true, false) as Button
		if button != null:
			buttons.append(button)
	if panel != null:
		apply_dialog(panel, buttons, crystal)


static func _copy(property: String, type: String) -> StyleBoxFlat:
	var source := THEME.get_stylebox(property, type)
	if source is StyleBoxFlat:
		return (source as StyleBoxFlat).duplicate() as StyleBoxFlat
	return null
