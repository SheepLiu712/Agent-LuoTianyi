extends ColorRect
@export var runtime: Resource = preload("res://src/platform/runtime_environment.gd").new()
@export var blur_enabled := true
func _ready() -> void:
	var renderer: String = ProjectSettings.get_setting("rendering/renderer/rendering_method","gl_compatibility")
	if not blur_enabled or runtime.is_headless() or renderer not in ["gl_compatibility","mobile","forward_plus"]:
		material = null
