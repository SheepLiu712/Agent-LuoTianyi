extends Button
## 共享下拉的一行：静态外观在共享主题里，setup() 只注入数据。
func setup(item: Dictionary) -> void:
	text = item.label
	set_meta("id",item.id)
	disabled = item.get("disabled",false)
