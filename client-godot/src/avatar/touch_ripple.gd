extends Panel

const APP_THEME := preload("res://theme/app_theme.tres")


func _init() -> void:
	name = "TouchRipple"
	theme = APP_THEME
	theme_type_variation = &"TouchRippleRing"
	z_index = 1000
	offset_right = 120.0
	offset_bottom = 120.0
	pivot_offset = Vector2(60, 60)
	scale = Vector2(0.35, 0.35)
	mouse_filter = MOUSE_FILTER_IGNORE


func _ready() -> void:
	var tween := create_tween().set_parallel()
	tween.set_trans(Tween.TRANS_QUART).set_ease(Tween.EASE_OUT)
	tween.tween_property(self, "scale", Vector2.ONE, 0.26)
	tween.tween_property(self, "modulate:a", 0.0, 0.26)
	tween.finished.connect(queue_free)
