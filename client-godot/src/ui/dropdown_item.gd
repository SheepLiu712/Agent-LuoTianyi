extends Button
## 共享下拉的一行：静态外观与尺寸由 dropdown_item.tscn 与共享主题定义，setup() 只注入数据。


func setup(item: Dictionary) -> void:
	text = item.label
	set_meta("id", item.id)
	disabled = item.get("disabled", false)
