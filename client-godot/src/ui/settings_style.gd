extends RefCounted

## 设置窗只在自身子树内替换主题变体，避免改变聊天、动态与登录页控件。
const MIN_CONTROL_HEIGHT := 40.0


static func apply(root: Node) -> void:
	if root == null:
		return
	var nodes: Array[Node] = [root]
	nodes.append_array(root.find_children("*", "", true, false))
	for node in nodes:
		if node is Button:
			_apply_button(node as Button)
		elif node is LineEdit:
			_apply_line_edit(node as LineEdit)
		elif node is TextEdit:
			_apply_text_edit(node as TextEdit)
		elif node is CheckBox:
			_apply_check_box(node as CheckBox)
		elif node is SpinBox:
			_apply_spin_box(node as SpinBox)


static func _apply_button(button: Button) -> void:
	var variation := button.theme_type_variation
	if variation in [&"SettingsNavItem", &"DropdownTrigger", &"DropdownItem", &"DropdownItemSelected", &"ChatIconButton"]:
		return
	if variation == &"PrimaryButton":
		button.theme_type_variation = &"SettingsPrimaryButton"
	elif variation != &"SettingsPrimaryButton" and variation != &"SettingsDangerButton":
		button.theme_type_variation = &"SettingsButton"
	button.custom_minimum_size.y = maxf(button.custom_minimum_size.y, MIN_CONTROL_HEIGHT)


static func _apply_line_edit(field: LineEdit) -> void:
	field.theme_type_variation = &"SettingsLineEdit"
	field.custom_minimum_size.y = maxf(field.custom_minimum_size.y, MIN_CONTROL_HEIGHT)


static func _apply_text_edit(field: TextEdit) -> void:
	field.theme_type_variation = &"SettingsTextEdit"


static func _apply_check_box(box: CheckBox) -> void:
	box.theme_type_variation = &"SettingsCheckBox"


static func _apply_spin_box(box: SpinBox) -> void:
	box.custom_minimum_size.y = maxf(box.custom_minimum_size.y, MIN_CONTROL_HEIGHT)
	box.get_line_edit().theme_type_variation = &"SettingsLineEdit"
