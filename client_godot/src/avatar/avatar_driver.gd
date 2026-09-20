extends Node2D
## Project-facing Live2D boundary. Call only from the main thread.

const MAPPING_PATH = "res://assets/live2d/live2d_interface_config.json"
var _model: Node2D
var _parameters: Dictionary = {}
var _mapping: Dictionary = {}
var _expression := ""
var _mouth_override := -1.0
var _base_mouth := -1.0
var _elapsed := 0.0
var _character_id := ""
var _resource_id := ""
var _expression_eyes: Dictionary = {}
var _eye_base := Vector2.ONE


func load_character(descriptor_path: String) -> Error:
	if not FileAccess.file_exists(descriptor_path):
		return ERR_FILE_NOT_FOUND
	var descriptor: Variant = JSON.parse_string(FileAccess.get_file_as_string(descriptor_path))
	if not descriptor is Dictionary:
		return ERR_INVALID_DATA
	for key in ["character_id","resource_id","model_path","mapping_path"]:
		if not descriptor.get(key) is String or descriptor[key].is_empty():
			return ERR_INVALID_DATA
	var result := load_avatar(descriptor.model_path,descriptor.mapping_path)
	if result == OK:
		_character_id = descriptor.character_id
		_resource_id = descriptor.resource_id
	return result

func load_avatar(model_path: String,mapping_path: String = MAPPING_PATH) -> Error:
	if not FileAccess.file_exists(model_path):
		return ERR_FILE_NOT_FOUND
	if not FileAccess.file_exists(mapping_path):
		return ERR_FILE_NOT_FOUND
	var mapping: Variant = JSON.parse_string(FileAccess.get_file_as_string(mapping_path))
	if not mapping is Dictionary or not mapping.get("expression_projection") is Dictionary or not mapping.get("mouth_value_projection") is Dictionary:
		return ERR_INVALID_DATA
	if not ClassDB.class_exists("GDCubismUserModel"):
		return ERR_UNAVAILABLE
	var data = JSON.parse_string(FileAccess.get_file_as_string(model_path))
	if not data is Dictionary or not model_path.ends_with(".model3.json"):
		return ERR_INVALID_DATA
	var references: Dictionary = data.get("FileReferences", {})
	if not references.has("Moc") or references.get("Textures", []).is_empty():
		return ERR_INVALID_DATA
	var files: Array = [references.Moc]
	files.append_array(references.Textures)
	for optional in ["Physics", "Pose", "UserData"]:
		if references.has(optional):
			files.append(references[optional])
	for entry in references.get("Expressions", []):
		files.append(entry.File)
	for group in references.get("Motions", {}).values():
		for motion in group:
			files.append(motion.File)
	for file in files:
		var resource_path: String = model_path.get_base_dir().path_join(file)
		# Exported textures are imported resources, not loose PNG files.
		if not FileAccess.file_exists(resource_path) and not ResourceLoader.exists(resource_path):
			return ERR_FILE_NOT_FOUND
	var candidate: Node2D = ClassDB.instantiate("GDCubismUserModel")
	var effects: Node = ClassDB.instantiate("GDCubismEffectCustom")
	candidate.add_child(ClassDB.instantiate("GDCubismEffectBreath"))
	candidate.add_child(effects)
	add_child(candidate)
	candidate.set("assets", model_path)
	var canvas: Dictionary = candidate.call("get_canvas_info")
	if canvas.is_empty():
		candidate.free()
		return ERR_INVALID_DATA
	if is_instance_valid(_model):
		_model.free()
	_model = candidate
	_mapping = mapping
	_character_id = ""
	_resource_id = ""
	_parameters.clear()
	for parameter in _model.call("get_parameters"):
		_parameters[parameter.id] = parameter
	_expression_eyes.clear()
	for expression in references.get("Expressions", []):
		var expression_data: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(model_path.get_base_dir().path_join(expression.File)))
		var eyes := Vector2.ONE
		for parameter in expression_data.get("Parameters", []):
			var index := ["ParamEyeLOpen", "ParamEyeROpen"].find(parameter.get("Id", ""))
			if index < 0: continue
			match parameter.get("Blend", "Add"):
				"Add": eyes[index] += float(parameter.Value)
				"Multiply": eyes[index] *= float(parameter.Value)
				"Overwrite": eyes[index] = float(parameter.Value)
		_expression_eyes[expression.Name] = eyes.clamp(Vector2.ZERO, Vector2.ONE)
	effects.connect("cubism_process", _apply_parameters)
	_mouth_override = -1.0
	_elapsed = 0.0
	apply_expression("normal")
	return OK


func apply_expression(command: String) -> bool:
	if not is_instance_valid(_model):
		return false
	var selected: String = _mapping.get("expression_projection", {}).get(command, command)
	if not selected in _model.call("get_expressions"):
		return false
	_model.call("start_expression", selected)
	_expression = selected
	_eye_base = _expression_eyes.get(selected, Vector2.ONE)
	_base_mouth = float(_mapping.get("mouth_value_projection", {}).get(selected, -1.0))
	return true


func play_motion(group: String, index: int = 0) -> bool:
	if not is_instance_valid(_model):
		return false
	var motions: Dictionary = _model.call("get_motions")
	if not motions.has(group) or index < 0 or index >= int(motions[group]):
		return false
	_model.call("start_motion", group, index, 2)
	return true


func set_mouth_openness(value: float) -> void:
	if is_instance_valid(_model):
		_mouth_override = -1.0 if value < 0 else clampf(value, 0.0, 1.0)


func get_status() -> Dictionary:
	if not is_instance_valid(_model):
		return {"loaded": false, "canvas_size": Vector2.ZERO,"character_id":"","resource_id":"",
			"expression": "", "motion_groups": [], "mouth_openness": 0.0, "eye_openness":Vector2.ZERO}
	var mouth := _mouth_override if _mouth_override >= 0 else _base_mouth
	if mouth < 0:
		mouth = float(_parameters.ParamMouthOpenY.value) if _parameters.has("ParamMouthOpenY") else 0.0
	return {"loaded": true, "canvas_size": _model.call("get_canvas_info").size_in_pixels,"character_id":_character_id,"resource_id":_resource_id,
		"expression": _expression, "motion_groups": _model.call("get_motions").keys(),
		"mouth_openness": mouth, "eye_openness":Vector2(
			float(_parameters.ParamEyeLOpen.value) if _parameters.has("ParamEyeLOpen") else 0.0,
			float(_parameters.ParamEyeROpen.value) if _parameters.has("ParamEyeROpen") else 0.0)}


func _apply_parameters(_source: Object, delta: float) -> void:
	_elapsed += delta
	# The bundled model has no EyeBlink group, so use its actual eye parameters.
	var blink_phase := fmod(_elapsed, 4.5)
	var openness := absf(blink_phase - 4.41) / 0.09 if blink_phase > 4.32 else 1.0
	for index in 2:
		var eye: String = ["ParamEyeLOpen", "ParamEyeROpen"][index]
		if _parameters.has(eye): _parameters[eye].value = _eye_base[index] * openness
	var mouth := _mouth_override if _mouth_override >= 0 else _base_mouth
	if mouth >= 0 and _parameters.has("ParamMouthOpenY"):
		_parameters.ParamMouthOpenY.value = mouth
