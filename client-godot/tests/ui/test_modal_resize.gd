extends SceneTree
## 复用同一个确认框：取消后再打开必须回到同样高度，正文不能被裁掉。

const TEXT := "把 Python 客户端保存的语音与历史图片复制到当前账号？\n\n只新增、不覆盖：已有缓存保持不变，源文件保留。\n\n注意：Python 客户端记录的是 幻想源灵 @ http://127.0.0.1:60030，与当前登录不同；媒体仍会写入当前账号。"
var failures: Array[String] = []


func _initialize() -> void:
	run.call_deferred()


func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)


func settle(frames: int = 20) -> void:
	for _frame in frames:
		await process_frame


func _check_content_visible(dialog: Window, label: String) -> void:
	var message: Label = dialog.get_node("%Message")
	var scroll: ScrollContainer = dialog.get_node("Panel/Column/MessageScroll")
	check(message.size.y + 1.0 >= message.get_combined_minimum_size().y, label + ": message height is not clipped")
	check(not scroll.get_v_scroll_bar().visible, label + ": no scrollbar for standard confirmation")
	check(dialog.get_node("%Panel").size.x <= dialog.size.x - 40, label + ": panel leaves room for its shadow gutter")


func run() -> void:
	root.size = Vector2i(880, 760)
	root.gui_embed_subwindows = true
	var host := Window.new()
	host.size = Vector2i(880, 760)
	root.add_child(host)
	host.show()
	var dialog = load("res://scenes/ui/components/decision_dialog.tscn").instantiate()
	dialog.title = "导入媒体"
	dialog.dialog_text = TEXT
	dialog.ok_button_text = "开始导入"
	host.add_child(dialog)
	dialog.popup_centered()
	await settle()
	var first_height: int = dialog.size.y
	_check_content_visible(dialog, "first open")
	dialog.get_cancel_button().pressed.emit()
	await process_frame
	check(not dialog.visible, "cancel closes the dialog")
	dialog.popup_centered()
	await settle()
	check(dialog.size.y == first_height, "reopen keeps the settled height: %s -> %s" % [first_height, dialog.size.y])
	_check_content_visible(dialog, "reopen")
	host.queue_free()
	await process_frame
	print("Modal resize: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
