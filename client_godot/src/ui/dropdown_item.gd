extends Button
## One row of the shared dropdown: the static look lives in the scene, setup() injects the row.
func setup(item: Dictionary) -> void:
	text = item.label
	set_meta("id",item.id)
	disabled = item.get("disabled",false)
