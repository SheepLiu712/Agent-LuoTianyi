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
	scale = Vector2(0.01, 0.01)
	mouse_filter = MOUSE_FILTER_IGNORE


func _ready() -> void:
	var tween := create_tween().set_parallel()
	tween.tween_property(self, "scale", Vector2.ONE, 0.5)
	tween.tween_property(self, "modulate:a", 0.0, 0.5)
	tween.finished.connect(queue_free)
