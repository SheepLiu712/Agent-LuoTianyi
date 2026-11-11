extends ColorRect
@export var runtime: Resource = preload("res://src/platform/runtime_environment.gd").new()
@export var blur_enabled := true
func _ready() -> void:
	if not blur_enabled or not runtime.supports_blur():
		material = null
