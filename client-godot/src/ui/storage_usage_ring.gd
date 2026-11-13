extends Control
## Multi-segment donut usage ring backed by unified design tokens.

const Tokens = preload("res://src/ui/design_tokens.gd")
const BACKDROP_COLOR := Tokens.RING_BACKDROP
const CLIENT_COLOR := Tokens.RING_CLIENT
const OTHER_COLOR := Tokens.RING_OTHER
const FREE_COLOR := Tokens.RING_FREE
const TRACK_COLOR := Color(1, 1, 1, 1)
const MARKER_RADIUS := 17.0

var _segments: Array[Dictionary] = []
var _total := 0
var _marker_angle := -PI * 0.5
var _marker_visible := false


func set_usage(client_bytes: int, total_bytes: int, free_bytes: int) -> void:
	if client_bytes < 0 or total_bytes <= 0 or free_bytes < 0 or free_bytes > total_bytes:
		set_unavailable()
		return
	var used := total_bytes - free_bytes
	var client := mini(client_bytes, used)
	var other := used - client
	_total = total_bytes
	_segments = [
		{"kind": "client", "bytes": client, "color": CLIENT_COLOR},
		{"kind": "other", "bytes": other, "color": OTHER_COLOR},
		{"kind": "free", "bytes": free_bytes, "color": FREE_COLOR},
	]
	_marker_visible = client > 0
	_marker_angle = -PI * 0.5 + TAU * float(client) / float(total_bytes)
	queue_redraw()


func set_unavailable() -> void:
	_segments = []
	_total = 0
	_marker_visible = false
	queue_redraw()


func get_segments() -> Array[Dictionary]:
	return _segments.duplicate(true)


func has_marker() -> bool:
	return _marker_visible


func get_marker_position() -> Vector2:
	if not _marker_visible:
		return Vector2(-1, -1)
	var geometry := _ring_geometry()
	var center: Vector2 = size * 0.5
	return center + Vector2(cos(_marker_angle), sin(_marker_angle)) * geometry.radius


func _draw() -> void:
	var geometry := _ring_geometry()
	if geometry.outer_radius <= 0:
		return
	var center: Vector2 = size * 0.5
	draw_circle(center, geometry.outer_radius + 8.0, BACKDROP_COLOR)
	draw_arc(center, geometry.radius, 0.0, TAU, 128, TRACK_COLOR, geometry.width, true)
	if not _segments.is_empty() and _total > 0:
		var start := -PI * 0.5
		for segment in _segments:
			var value := int(segment.get("bytes", 0))
			if value <= 0:
				continue
			var span := TAU * float(value) / float(_total)
			var points := maxi(3, ceili(span / (PI / 96.0)))
			draw_arc(center, geometry.radius, start, start + span, points, segment.color, geometry.width, true)
			start += span
	if _marker_visible:
		draw_circle(get_marker_position(), MARKER_RADIUS, CLIENT_COLOR)


func _ring_geometry() -> Dictionary:
	var extent := minf(size.x, size.y)
	var width := clampf(extent * 0.115, 18.0, 28.0)
	var outer_radius := extent * 0.5 - 8.0
	return {
		"width": width,
		"outer_radius": outer_radius,
		"radius": maxf(0.0, outer_radius - width * 0.5),
	}
