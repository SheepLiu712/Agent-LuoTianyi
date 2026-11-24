extends SceneTree
## Login-scoped styles must not change the shared application theme.

const LoginStyle = preload("res://src/ui/login_style.gd")
const LoginPage = preload("res://scenes/ui/pages/account_view.tscn")
const ErrorDialogScene = preload("res://scenes/ui/components/error_dialog.tscn")
const THEME = preload("res://theme/app_theme.tres")
var failures: Array[String] = []


func _initialize() -> void:
	run.call_deferred()


func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)


func run() -> void:
	var page := LoginPage.instantiate() as Control
	root.add_child(page)
	await process_frame
	LoginStyle.apply_account_view(page, false)
	_check_flat(page)
	LoginStyle.apply_account_view(page, true)
	_check_crystal(page)
	LoginStyle.apply_account_view(page, false)
	_check_flat(page)
	_check_shared_theme_untouched()

	var error := ErrorDialogScene.instantiate()
	root.add_child(error)
	error.call("apply_login_style", true, false)
	var error_panel := (error.get_node("%Panel") as Control).get_theme_stylebox("panel") as StyleBoxFlat
	check(error_panel != null and error_panel.corner_radius_top_left == 16, "error dialog accepts login style")
	error.call("apply_login_style", false, false)
	error_panel = (error.get_node("%Panel") as Control).get_theme_stylebox("panel") as StyleBoxFlat
	check(error_panel != null and error_panel.corner_radius_top_left == 8, "error dialog restores shared style")

	page.queue_free()
	error.queue_free()
	await process_frame
	print("Login style: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func _check_flat(page: Control) -> void:
	var surface := page.get_theme_stylebox("panel") as StyleBoxFlat
	check(surface != null and surface.bg_color.is_equal_approx(LoginStyle.SURFACE_COLOR), "login page uses pale blue")
	var avatar_frame := page.find_child("AvatarFrame", true, false) as Control
	var avatar := avatar_frame.get_theme_stylebox("panel") as StyleBoxFlat if avatar_frame != null else null
	check(avatar != null and avatar.border_width_left == 3 and avatar.shadow_size == 0, "login avatar uses a crisp accent ring")
	check(avatar != null and avatar.corner_radius_top_left == 56, "login avatar keeps its circular mask")
	var menu := _box(page, "MenuPopup", "panel")
	check(menu != null and menu.corner_radius_top_left == 16 and is_equal_approx(menu.shadow_color.a, 0.20), "login menu uses flat login radius")
	var server_dialog := _child(page, "ServerDialog")
	var server_panel := _panel(server_dialog)
	check(server_panel != null and server_panel.corner_radius_top_left == 16, "server dialog uses flat login radius")
	check(_button_radius(_child(server_dialog, "ServerSave")) == 16, "server save uses flat login radius")
	check(_button_radius(_child(server_dialog, "ServerProbe")) == 16, "server probe uses flat login radius")
	var remove_dialog := _child(page, "RemoveAccountDialog")
	var remove_panel := _panel(remove_dialog)
	check(remove_panel != null and remove_panel.corner_radius_top_left == 16, "remove dialog uses flat login radius")
	check(_button_radius(_child(remove_dialog, "Confirm")) == 16, "remove confirm uses flat login radius")


func _check_crystal(page: Control) -> void:
	var menu := _box(page, "MenuPopup", "panel")
	check(menu != null and menu.corner_radius_top_left == 20, "login menu uses crystal login radius")
	var server_dialog := _child(page, "ServerDialog")
	var server_panel := _panel(server_dialog)
	check(server_panel != null and server_panel.corner_radius_top_left == 20, "server dialog uses crystal login radius")
	var save := _box(server_dialog, "ServerSave")
	check(save != null and save.corner_radius_top_left == 20 and save.shadow_color.is_equal_approx(LoginStyle.ACTION_SHADOW), "crystal login buttons use blue shadow")
	var remove_dialog := _child(page, "RemoveAccountDialog")
	var remove_panel := _panel(remove_dialog)
	check(remove_panel != null and remove_panel.corner_radius_top_left == 20, "remove dialog uses crystal login radius")
	var confirm := _child(remove_dialog, "Confirm") as Button
	if confirm != null:
		confirm.theme_type_variation = &"SettingsDangerButton"
		LoginStyle.apply_button(confirm, true)
		check(_button_radius(confirm) == 20, "remove confirm uses crystal login radius")


func _check_shared_theme_untouched() -> void:
	var popup := THEME.get_stylebox("panel", "DropdownPopup") as StyleBoxFlat
	var dialog := THEME.get_stylebox("panel", "SettingsDialogSurface") as StyleBoxFlat
	var button := THEME.get_stylebox("normal", "SettingsButton") as StyleBoxFlat
	check(popup != null and popup.corner_radius_top_left == 8, "shared dropdown keeps its radius")
	check(dialog != null and dialog.corner_radius_top_left == 8, "shared dialog keeps its radius")
	check(button != null and button.corner_radius_top_left == 8, "shared button keeps its radius")


func _panel(dialog: Node) -> StyleBoxFlat:
	if dialog == null:
		return null
	var node := dialog.find_child("Panel", true, false) as Control
	return node.get_theme_stylebox("panel") as StyleBoxFlat if node != null else null


func _child(root: Node, name: String) -> Node:
	return root.find_child(name, true, false) if root != null else null


func _box(root: Node, name: String, property: String = "normal") -> StyleBoxFlat:
	var node := _child(root, name)
	return node.call("get_theme_stylebox", property) as StyleBoxFlat if node != null else null


func _button_radius(node: Node) -> int:
	if not node is Button:
		return -1
	var box := (node as Button).get_theme_stylebox("normal") as StyleBoxFlat
	return box.corner_radius_top_left if box != null else -1
