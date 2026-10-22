extends Resource
signal image_selected(result: Dictionary)
signal export_selected(target: RefCounted)
signal canceled
func bind(_dialog: FileDialog) -> void:
	pass
func select_image() -> void:
	image_selected.emit({"ok":false,"code":"FILE_PICKER_UNAVAILABLE"})
func select_export(_filename: String) -> void:
	canceled.emit()
func cancel() -> void:
	pass
