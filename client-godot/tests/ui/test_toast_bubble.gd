extends SceneTree
## 提示气泡的呈现契约：画面正中的横向矩形、出现淡入、到点淡出，且永远不挡输入。
const SCENE := "res://scenes/ui/toast_overlay.tscn"
const TEXT := "相处偏好加载失败，重新打开设置可重试。"
var failures: Array[String] = []

func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)

func _initialize() -> void:
	run.call_deferred()

func run() -> void:
	root.size = Vector2i(720, 400)
	root.content_scale_size = Vector2i.ZERO
	var toast: Control = load(SCENE).instantiate()
	root.add_child(toast)
	await process_frame
	var panel: Control = toast.get_node("%Panel")
	check(not toast.visible, "the toast starts hidden")
	toast.show_message(TEXT, -1.0)
	check(toast.visible and toast.mouse_filter == Control.MOUSE_FILTER_IGNORE, "the toast never blocks input")
	check(panel.modulate.a < 0.5, "the toast fades in instead of popping")
	await create_timer(0.4).timeout
	check(is_equal_approx(panel.modulate.a, 1.0), "the fade-in settles at full opacity")
	_check_shape(toast, panel)
	toast.show_message("已保存", 0.05)
	await create_timer(0.9).timeout
	check(not toast.visible, "the toast fades out on its own")
	toast.show_message(TEXT, -1.0)
	toast.clear()
	check(not toast.visible and toast.last_text().is_empty(), "clear removes the toast at once")
	toast.queue_free()
	await process_frame
	await _check_resize_keeps_center()
	await _check_hidden_stage_recovers()
	await _check_zero_stage_recovers()
	print("Toast bubble: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

## 逐字换行的竖条是这里要钉死的退化形态：宽度必须撑开，高度必须是一行。
func _check_shape(toast: Control, panel: Control) -> void:
	var rect := panel.get_global_rect()
	var frame := toast.get_global_rect()
	check(rect.size.x > 200.0 and rect.size.y < 60.0, "the bubble is a horizontal rectangle: " + str(rect.size))
	check(absf(rect.get_center().x - frame.get_center().x) < 1.0, "the bubble is horizontally centred")
	check(absf(rect.get_center().y - frame.get_center().y) < 1.0, "the bubble is vertically centred")


## 换屏幕尺寸（窗口被拉大或压小）之后仍然要落在正中，不能跟着父级漂。
func _check_resize_keeps_center() -> void:
	var stage := Control.new()
	stage.size = Vector2i(600, 320)
	root.add_child(stage)
	var toast: Control = load(SCENE).instantiate()
	stage.add_child(toast)
	await process_frame
	toast.show_message(TEXT, -1.0)
	await process_frame
	_check_centred(toast, stage, "600x320")
	stage.size = Vector2i(980, 720)
	await process_frame
	_check_centred(toast, stage, "980x720")
	toast.queue_free()
	stage.queue_free()
	await process_frame


## 页面隐藏时建好的气泡，内层锚点会停在 0：重新显示时必须自己补回整块舞台。
func _check_hidden_stage_recovers() -> void:
	var stage := Control.new()
	stage.size = Vector2i(600, 320)
	root.add_child(stage)
	stage.hide()
	var toast: Control = load(SCENE).instantiate()
	stage.add_child(toast)
	await process_frame
	stage.size = Vector2i(900, 600)
	stage.show()
	toast.show_message(TEXT, -1.0)
	await process_frame
	_check_centred(toast, stage, "hidden then shown")


func _check_centred(toast: Control, stage: Control, label: String) -> void:
	var rect: Rect2 = toast.get_node("%Panel").get_global_rect()
	var offset: Vector2 = rect.get_center() - stage.get_global_rect().get_center()
	check(offset.length() < 1.5, "%s keeps the bubble centred (offset %s)" % [label, offset])


## 设置页常在窗口 open 之前就报加载失败：那会儿舞台还是 0 尺寸，显示时必须补回来。
func _check_zero_stage_recovers() -> void:
	var stage := Control.new()
	root.add_child(stage)
	stage.hide()
	var toast: Control = load(SCENE).instantiate()
	stage.add_child(toast)
	await process_frame
	toast.show_message(TEXT, -1.0)
	await process_frame
	stage.size = Vector2i(900, 600)
	stage.show()
	await process_frame
	_check_centred(toast, stage, "triggered before the stage had a size")
	toast.queue_free()
	stage.queue_free()
	await process_frame
