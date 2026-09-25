extends Node2D
## Rendering capability. Implementations own all native model objects/resources.
func load_character(_descriptor_path: String) -> Error: return ERR_UNAVAILABLE
func load_avatar(_model_path: String, _mapping_path: String = "") -> Error: return ERR_UNAVAILABLE
func apply_expression(_command: String) -> bool: return false
func play_motion(_group: String, _index: int = 0) -> bool: return false
func set_mouth_openness(_value: float) -> void: pass
func set_gaze(_target: Vector2) -> void: pass
func hit_test(_position: Vector2) -> Array[String]: return []
func get_status() -> Dictionary:
	return {"loaded":false,"canvas_size":Vector2.ZERO,"character_id":"","resource_id":"",
		"expression":"","motion_groups":[],"mouth_openness":0.0,"eye_openness":Vector2.ZERO,"gaze":Vector2.ZERO}
