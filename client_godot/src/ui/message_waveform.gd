extends Control
## Audio waveform strip: self-drawn bars, colours supplied by the scene.
@export var played_color := Color("66ccff")
@export var remaining_color := Color("9eb6c4")
var values := PackedFloat32Array()
var progress := 0.0

func _draw() -> void:
	if values.is_empty():
		return
	var spacing := size.x/values.size()
	for index in values.size():
		var height := maxf(2.0,values[index]*size.y)
		var color := played_color if float(index)/values.size() < progress else remaining_color
		draw_line(Vector2((index+.5)*spacing,(size.y-height)/2),Vector2((index+.5)*spacing,(size.y+height)/2),color,2,true)
