extends HBoxContainer
## Audio waveform visualizer driven by normalized amplitude samples and playback progress.

const Tokens = preload("res://src/ui/design_tokens.gd")

@export var played_color := Tokens.WAVE_BAR_ACTIVE
@export var remaining_color := Tokens.WAVE_BAR_INACTIVE

var values := PackedFloat32Array():
	set(value):
		values = value
		_refresh()
var progress := 0.0:
	set(value):
		progress = value
		_refresh()


func _ready() -> void:
	resized.connect(_refresh)
	_refresh()


func _refresh() -> void:
	if not is_node_ready():
		return
	var count := mini(values.size(), get_child_count())
	for index in get_child_count():
		var slot := get_child(index) as Control
		slot.visible = index < count
		if index >= count:
			continue
		var bar := slot.get_node("Bar") as ColorRect
		bar.custom_minimum_size.y = maxf(2.0, clampf(values[index], 0.0, 1.0) * size.y)
		bar.color = played_color if float(index) / float(count) < progress else remaining_color
