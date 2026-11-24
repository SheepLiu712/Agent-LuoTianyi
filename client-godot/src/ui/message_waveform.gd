extends Control
## Audio waveform visualizer driven by normalized amplitude samples and playback progress.

const Tokens = preload("res://src/ui/design_tokens.gd")
const MAX_BARS := 24
const BAR_WIDTH := 2.0

@export var played_color := Tokens.WAVE_BAR_ACTIVE
@export var remaining_color := Tokens.WAVE_BAR_INACTIVE

var values := PackedFloat32Array():
	set(value):
		values = value
		queue_redraw()
var progress := 0.0:
	set(value):
		progress = value
		queue_redraw()


func _ready() -> void:
	resized.connect(queue_redraw)
	queue_redraw()


func bar_count() -> int:
	return mini(values.size(), MAX_BARS)


func bar_color(index: int, count: int) -> Color:
	return played_color if count > 0 and float(index) / float(count) < progress else remaining_color


func _draw() -> void:
	var count := bar_count()
	if count <= 0 or size.x <= 0.0 or size.y <= 0.0:
		return
	var slot_width := size.x / float(count)
	for index in count:
		var bar_height := maxf(2.0, clampf(values[index], 0.0, 1.0) * size.y)
		var x := slot_width * float(index) + (slot_width - BAR_WIDTH) * 0.5
		var y := (size.y - bar_height) * 0.5
		draw_rect(Rect2(x, y, BAR_WIDTH, bar_height), bar_color(index, count))
