extends SceneTree
## 统一错误弹窗：按窗口懒加载、串行队列与重复文本去重。

const ErrorDialog = preload("res://src/ui/error_dialog.gd")
var failures: Array[String] = []


func _initialize() -> void:
	run.call_deferred()


func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)


func settle(frames: int = 4) -> void:
	for _frame in frames:
		await process_frame


func run() -> void:
	var source := Control.new()
	root.add_child(source)
	ErrorDialog.present(source, "第一条错误")
	await settle()
	var dialog := _dialog()
	check(dialog != null and dialog.visible, "error dialog is created under the active window")
	if dialog == null:
		quit(1)
		return
	check(dialog.transient, "error dialog stays transient to its owner")
	check(dialog.get_current_text() == "第一条错误", "first error text is shown")
	ErrorDialog.present(source, "第一条错误")
	ErrorDialog.present(source, "第二条错误")
	await settle()
	check(dialog.get_current_text() == "第一条错误", "duplicate while visible does not replace current text")
	dialog.get_node("%ErrorConfirm").pressed.emit()
	await settle()
	check(dialog.get_current_text() == "第二条错误", "queued error follows after confirmation")
	check(dialog.get_node("%ErrorText").text == "第二条错误", "queued text reaches the label")
	dialog.get_node("%ErrorConfirm").pressed.emit()
	await settle()
	check(not dialog.visible, "confirm closes the dialog")
	ErrorDialog.present(source, "第三条错误")
	await settle()
	var escape := InputEventKey.new()
	escape.keycode = KEY_ESCAPE
	escape.pressed = true
	dialog.get_viewport().push_input(escape)
	await settle()
	check(not dialog.visible, "escape closes the error dialog")
	source.queue_free()
	await process_frame
	print("Error dialog: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func _dialog() -> Node:
	for child in root.find_children("*", "", true, false):
		if child.is_in_group("error_dialog"):
			return child
	return null
