extends "res://src/avatar/avatar_panel.gd"
@export var runtime: Resource = preload("res://src/platform/runtime_environment.gd").new()
## Isolated graphical smoke scene, usable from the exported executable.


func _ready() -> void:
	super._ready()
	if not avatar.get_status().loaded:
		push_error("Avatar load failed")
		get_tree().quit(1)
		return
	for argument in runtime.arguments():
		if argument.begins_with("--capture="):
			await get_tree().create_timer(2.0).timeout
			await RenderingServer.frame_post_draw
			var saved: Error = runtime.capture(get_viewport(),argument.trim_prefix("--capture="))
			get_tree().quit(0 if saved == OK else 1)
