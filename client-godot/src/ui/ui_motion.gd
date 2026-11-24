extends RefCounted
## 统一动效原语：遵循强缓出（EASE_OUT）、<300ms 时长预算、中心对齐与可中断原则。

const PRESS_DOWN_DURATION := 0.09
const PRESS_UP_DURATION := 0.14
const OVERLAY_OPEN_DURATION := 0.18
const OVERLAY_CLOSE_DURATION := 0.13


static func bind_interactive_cursors(node: Node) -> void:
	if node == null:
		return
	if node is BaseButton:
		(node as BaseButton).mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	for child in node.get_children():
		bind_interactive_cursors(child)


static func should_reduce_motion(ui_style: Variant = null) -> bool:
	var style = ui_style.call() if ui_style is Callable else ui_style
	if style != null and style.has_method("prefers_reduced_motion"):
		return bool(style.prefers_reduced_motion())
	return false


static func kill_tween(node: Node, key: StringName = &"_ui_motion_tween") -> void:
	if node == null or not node.has_meta(key):
		return
	var active: Variant = node.get_meta(key)
	if active is Tween and active.is_valid():
		active.kill()
	node.remove_meta(key)


static func bind_tactile_press(
	button: BaseButton,
	ui_style_provider: Variant = null,
	press_scale: float = 0.97
) -> void:
	if button == null or button.has_meta(&"_tactile_bound"):
		return
	button.set_meta(&"_tactile_bound", true)
	button.resized.connect(func(): _sync_center_pivot(button))
	button.button_down.connect(func(): _animate_press(button, press_scale, PRESS_DOWN_DURATION, Tween.TRANS_QUAD, ui_style_provider))
	var release := func(): _animate_press(button, 1.0, PRESS_UP_DURATION, Tween.TRANS_QUART, ui_style_provider)
	button.button_up.connect(release)
	button.mouse_exited.connect(release)


static func _sync_center_pivot(control: Control) -> void:
	if is_instance_valid(control):
		control.pivot_offset = control.size * 0.5


static func _animate_press(
	button: BaseButton,
	target_scale: float,
	duration: float,
	transition: Tween.TransitionType,
	ui_style_provider: Variant
) -> void:
	if not is_instance_valid(button):
		return
	kill_tween(button, &"_press_tween")
	_sync_center_pivot(button)
	var target := Vector2.ONE * target_scale
	if should_reduce_motion(ui_style_provider) or (button.disabled and target_scale < 1.0):
		button.scale = Vector2.ONE
		return
	var tween := button.create_tween()
	tween.set_trans(transition).set_ease(Tween.EASE_OUT)
	tween.tween_property(button, "scale", target, duration)
	button.set_meta(&"_press_tween", tween)


static func reveal_overlay(
	panel: Control,
	origin_ratio: Vector2 = Vector2(0.5, 0.5),
	travel_y: float = -6.0,
	duration: float = OVERLAY_OPEN_DURATION,
	ui_style: Variant = null
) -> void:
	if panel == null:
		return
	kill_tween(panel)
	panel.visible = true
	var extent := Vector2(maxf(panel.size.x, panel.get_combined_minimum_size().x), maxf(panel.size.y, panel.get_combined_minimum_size().y))
	panel.pivot_offset = extent * origin_ratio
	if should_reduce_motion(ui_style):
		panel.scale = Vector2.ONE
		panel.modulate.a = 1.0
		return
	var move_position := travel_y != 0.0 and not (panel.get_parent() is Container)
	var rest_pos := panel.position
	panel.scale = Vector2(0.95, 0.95)
	panel.modulate.a = 0.0
	if move_position:
		panel.position = rest_pos + Vector2(0.0, travel_y)
	var tween := panel.create_tween().set_parallel(true)
	tween.set_trans(Tween.TRANS_QUART).set_ease(Tween.EASE_OUT)
	tween.tween_property(panel, "scale", Vector2.ONE, duration)
	tween.tween_property(panel, "modulate:a", 1.0, minf(duration, 0.15))
	if move_position:
		tween.tween_property(panel, "position", rest_pos, duration)
	panel.set_meta(&"_ui_motion_tween", tween)


static func dismiss_overlay(
	panel: Control,
	on_done: Callable = Callable(),
	origin_ratio: Vector2 = Vector2(0.5, 0.5),
	duration: float = OVERLAY_CLOSE_DURATION,
	ui_style: Variant = null
) -> void:
	if panel == null:
		if on_done.is_valid():
			on_done.call()
		return
	kill_tween(panel)
	if should_reduce_motion(ui_style) or not panel.visible:
		_finish_dismiss(panel, on_done)
		return
	var extent := Vector2(maxf(panel.size.x, panel.get_combined_minimum_size().x), maxf(panel.size.y, panel.get_combined_minimum_size().y))
	panel.pivot_offset = extent * origin_ratio
	var tween := panel.create_tween().set_parallel(true)
	tween.set_trans(Tween.TRANS_QUART).set_ease(Tween.EASE_OUT)
	tween.tween_property(panel, "scale", Vector2(0.96, 0.96), duration)
	tween.tween_property(panel, "modulate:a", 0.0, duration)
	tween.chain().tween_callback(func(): _finish_dismiss(panel, on_done))
	panel.set_meta(&"_ui_motion_tween", tween)


static func _finish_dismiss(panel: Control, on_done: Callable) -> void:
	if is_instance_valid(panel):
		panel.visible = false
		panel.scale = Vector2.ONE
		panel.modulate.a = 1.0
	if on_done.is_valid():
		on_done.call()
