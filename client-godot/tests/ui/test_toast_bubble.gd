extends SceneTree
## 提示气泡的呈现契约：可见区域顶部安全区居中的横向矩形、出现淡入、到点淡出，且永远不挡输入。
const SCENE := "res://scenes/ui/components/toast_overlay.tscn"
const TEXT := "相处偏好加载失败，重新打开设置可重试。"
const TOP_MARGIN := 16.0
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
	if DisplayServer.get_name() != "headless":
		await RenderingServer.frame_post_draw
		root.get_texture().get_image().save_png("res://artifacts/toast-bubble.png")
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
	await _check_scroll_container_stays_top_safe()
	print("Toast bubble: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

## 逐字换行的竖条是这里要钉死的退化形态：宽度必须撑开，高度必须是一行，且落在顶部安全区不压正文。
func _check_shape(toast: Control, panel: Control) -> void:
	var rect := panel.get_global_rect()
	var frame := toast.get_global_rect()
	check(rect.size.x > 200.0 and rect.size.y < 60.0, "the bubble is a horizontal rectangle: " + str(rect.size))
	check(absf(rect.get_center().x - frame.get_center().x) < 1.5, "the bubble is horizontally centred")
	check(absf(rect.position.y - (frame.position.y + TOP_MARGIN)) < 2.0, "the bubble sits in the top safe margin: " + str(rect.position.y))
	var style := panel.get_theme_stylebox("panel") as StyleBoxFlat
	check(style != null and style.corner_radius_top_left == 8, "the bubble uses the shared 8px surface radius")
	check(style != null and style.content_margin_left == 16 and style.content_margin_top == 8, "the bubble uses the 16x8 spacing step")
	check(style != null and style.border_width_left == 1 and style.border_width_top == 1, "the bubble uses the shared one-pixel border")


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
	toast.queue_free()
	stage.queue_free()
	await process_frame


func _check_centred(toast: Control, stage: Control, label: String) -> void:
	var rect: Rect2 = toast.get_node("%Panel").get_global_rect()
	var area := stage.get_global_rect()
	var dx := absf(rect.get_center().x - area.get_center().x)
	var dy := absf(rect.position.y - (area.position.y + TOP_MARGIN))
	check(dx < 1.5 and dy < 2.0, "%s keeps the bubble in top-center safe zone (dx=%s, dy=%s)" % [label, dx, dy])


## 设置页等放在 ScrollContainer 里的容器宿主：滚屏时仍落在可视区顶端，不遮挡中下方表单。
func _check_scroll_container_stays_top_safe() -> void:
	var scroll := ScrollContainer.new()
	scroll.size = Vector2(680, 360)
	root.add_child(scroll)
	var container := MarginContainer.new()
	container.custom_minimum_size = Vector2(660, 720)
	scroll.add_child(container)
	var toast: Control = load(SCENE).instantiate()
	container.add_child(toast)
	await process_frame
	scroll.scroll_vertical = 140
	toast.show_message(TEXT, -1.0)
	await process_frame
	_check_centred(toast, scroll, "scroll container host")
	toast.queue_free()
	scroll.queue_free()
	await process_frame


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
