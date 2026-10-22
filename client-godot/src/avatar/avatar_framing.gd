extends RefCounted
var _settings: Resource
func _init(settings: Resource = null) -> void:
	_settings = settings if settings != null else preload("res://src/storage/settings_store.gd").new()

var _zoom := 1.2
var _offset := Vector2.ZERO


func zoom_by(factor: float) -> void:
	if is_finite(factor) and factor > 0:
		_zoom = clampf(_zoom * factor, 0.6, 2.4)


func pan_by(delta: Vector2, panel_size: Vector2) -> void:
	if panel_size.x <= 0 or panel_size.y <= 0 or not delta.is_finite():
		return
	_offset = (_offset + delta / panel_size).clamp(Vector2(-0.4, -0.4), Vector2(0.4, 0.4))


func reset() -> void:
	_zoom = 1.2
	_offset = Vector2.ZERO


func get_transform(panel: Vector2, canvas: Vector2) -> Transform2D:
	if canvas.x <= 0 or canvas.y <= 0 or panel.x <= 0 or panel.y <= 0:
		return Transform2D.IDENTITY
	var factor := minf(panel.x / canvas.x, panel.y / canvas.y) * _zoom
	return Transform2D(0.0, Vector2.ONE * factor, 0.0, panel * (Vector2(0.5, 0.5) + _offset))


func save_settings() -> Error:
	var config = _settings
	config.set_value("framing", "zoom", _zoom)
	config.set_value("framing", "offset", _offset)
	return config.save_settings()


func load_settings() -> Error:
	var config = _settings
	var result: Error = config.load_settings()
	if result != OK:
		return result if result == ERR_FILE_NOT_FOUND else ERR_INVALID_DATA
	var zoom = config.get_value("framing", "zoom", null)
	var offset = config.get_value("framing", "offset", null)
	if not (zoom is float or zoom is int) or not offset is Vector2:
		return ERR_INVALID_DATA
	if not is_finite(float(zoom)) or not offset.is_finite():
		return ERR_INVALID_DATA
	_zoom = clampf(float(zoom), 0.6, 2.4)
	_offset = offset.clamp(Vector2(-0.4, -0.4), Vector2(0.4, 0.4))
	return OK
