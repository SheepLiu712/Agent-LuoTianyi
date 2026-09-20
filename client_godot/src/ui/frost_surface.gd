extends ColorRect
@export var blur_enabled := true
func _ready() -> void:
	var renderer: String = ProjectSettings.get_setting("rendering/renderer/rendering_method","gl_compatibility")
	if not blur_enabled or DisplayServer.get_name() == "headless" or renderer not in ["gl_compatibility","mobile","forward_plus"]:
		material = null
