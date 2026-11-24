extends BaseButton
## Pill toggle switch (34x20) matching the flat cyan desktop design.

const TRACK_SIZE := Vector2(34.0, 20.0)
const THUMB_SIZE := Vector2(16.0, 16.0)
const TRACK_OFF := Color("cbd8e2")
const TRACK_OFF_HOVER := Color("b8c8d4")
const TRACK_ON := Color("66ccff")
const TRACK_ON_HOVER := Color("4dc2ff")
const TRACK_DISABLED := Color("dde6ed")
const THUMB_COLOR := Color("ffffff")
const FOCUS_RING := Color("1278ad")

var _thumb_t := 0.0
var _animating := false
var _tween: Tween
var _track_box := StyleBoxFlat.new()
var _thumb_box := StyleBoxFlat.new()
var _focus_box := StyleBoxFlat.new()


func _init() -> void:
	toggle_mode = true
	custom_minimum_size = TRACK_SIZE
	size_flags_vertical = Control.SIZE_SHRINK_CENTER
	size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
	mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	focus_mode = Control.FOCUS_ALL
	_track_box.set_corner_radius_all(10)
	_track_box.anti_aliasing = true
	_thumb_box.set_corner_radius_all(8)
	_thumb_box.bg_color = THUMB_COLOR
	_thumb_box.anti_aliasing = true
	_focus_box.draw_center = false
	_focus_box.set_border_width_all(2)
	_focus_box.border_color = FOCUS_RING
	_focus_box.set_corner_radius_all(12)
	_focus_box.anti_aliasing = true


func _ready() -> void:
	_thumb_t = 1.0 if button_pressed else 0.0
	toggled.connect(_on_toggled)


func _on_toggled(pressed_state: bool) -> void:
	var target := 1.0 if pressed_state else 0.0
	if not is_inside_tree():
		_thumb_t = target
		queue_redraw()
		return
	if _tween != null and _tween.is_valid():
		_tween.kill()
	_animating = true
	_tween = create_tween()
	_tween.set_trans(Tween.TRANS_QUART).set_ease(Tween.EASE_OUT)
	_tween.tween_method(_set_thumb_t, _thumb_t, target, 0.16)
	_tween.finished.connect(func(): _animating = false)


func _set_thumb_t(value: float) -> void:
	_thumb_t = value
	queue_redraw()


func _draw() -> void:
	if not _animating:
		_thumb_t = 1.0 if button_pressed else 0.0
	var origin := Vector2(0.0, (size.y - TRACK_SIZE.y) * 0.5)
	_track_box.bg_color = _resolve_track_color()
	draw_style_box(_track_box, Rect2(origin, TRACK_SIZE))
	var thumb_x := origin.x + lerpf(2.0, 16.0, _thumb_t)
	var thumb_y := origin.y + 2.0
	_thumb_box.bg_color = Color(1, 1, 1, 0.88 if disabled else 1.0)
	draw_style_box(_thumb_box, Rect2(Vector2(thumb_x, thumb_y), THUMB_SIZE))
	if has_focus():
		draw_style_box(_focus_box, Rect2(origin - Vector2(2.0, 2.0), TRACK_SIZE + Vector2(4.0, 4.0)))


func _resolve_track_color() -> Color:
	if disabled:
		return TRACK_DISABLED
	if button_pressed:
		return TRACK_ON_HOVER if is_hovered() else TRACK_ON
	return TRACK_OFF_HOVER if is_hovered() else TRACK_OFF
