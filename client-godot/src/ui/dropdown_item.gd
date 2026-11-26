extends Button
## 共享下拉的一行：基础样式与最小高度在 _init() 声明，setup() 只注入数据。


func _init() -> void:
	custom_minimum_size = Vector2(0, 36)
	alignment = HORIZONTAL_ALIGNMENT_LEFT
	theme_type_variation = &"DropdownItem"


func setup(item: Dictionary) -> void:
	text = item.label
	set_meta("id", item.id)
	disabled = item.get("disabled", false)
