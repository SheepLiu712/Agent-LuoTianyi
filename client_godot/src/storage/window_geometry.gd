extends RefCounted
var path: String
func _init(file_path: String) -> void:
	path = file_path
func read_layout(key: String, fallback: Rect2i, minimum: Vector2i, screens: Array[Rect2i]) -> Dictionary:
	var config := ConfigFile.new()
	config.load(path)
	var saved: Variant = config.get_value(key,"rect",fallback)
	var rect: Rect2i = saved if saved is Rect2i and saved.size.x > 0 and saved.size.y > 0 else fallback
	rect.size = rect.size.max(minimum)
	if not screens.is_empty():
		var usable := screens[0]
		var overlap := 0
		for screen in screens:
			var area := rect.intersection(screen).get_area()
			if area > overlap:
				overlap = area
				usable = screen
		rect.size = rect.size.min(usable.size)
		rect.position.x = clampi(rect.position.x,usable.position.x,usable.end.x-rect.size.x)
		rect.position.y = clampi(rect.position.y,usable.position.y,usable.end.y-rect.size.y)
	var maximized: Variant = config.get_value(key,"maximized",false)
	return {"rect":rect,"maximized":maximized if maximized is bool else false}
func write_layout(key: String, rect: Rect2i, maximized: bool) -> Error:
	if key.is_empty() or rect.size.x <= 0 or rect.size.y <= 0:
		return ERR_INVALID_PARAMETER
	var config := ConfigFile.new()
	config.load(path)
	config.set_value(key,"rect",rect)
	config.set_value(key,"maximized",maximized)
	var error := DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	return config.save(path) if error == OK else error
