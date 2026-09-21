extends "res://src/platform/file_interaction.gd"
const Images = preload("res://src/storage/image_file_reader.gd")
var _dialog: FileDialog
var _pending := ""

func bind(dialog: FileDialog) -> void:
	if _dialog == dialog: return
	cancel()
	if is_instance_valid(_dialog):
		_dialog.file_selected.disconnect(_selected)
		_dialog.canceled.disconnect(_canceled)
	_dialog = dialog
	_dialog.file_selected.connect(_selected)
	_dialog.canceled.connect(_canceled)

func select_image() -> void:
	_pending = "image"
	_dialog.popup_centered_ratio(.7)

func select_export(filename: String) -> void:
	_pending = "export"
	_dialog.current_file = filename
	_dialog.popup_centered_ratio(.7)

func cancel() -> void:
	_pending = ""
	if is_instance_valid(_dialog): _dialog.hide()

func _canceled() -> void:
	_pending = ""
	canceled.emit()

func _selected(path: String) -> void:
	var kind := _pending
	_pending = ""
	if kind == "image": image_selected.emit(Images.read(path))
	elif kind == "export": export_selected.emit(preload("res://src/storage/log_export_target.gd").new(path))
