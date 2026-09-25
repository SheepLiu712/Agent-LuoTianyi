extends ScrollContainer
signal visible_messages(ids: Array[String])
signal interacted
signal audio_action(id: String, action: String)
signal image_opened(texture: Texture2D)
signal image_action(id: String, action: String)
const Bubble = preload("res://scenes/ui/message_bubble.tscn")
@onready var _canvas: Control = %Canvas
var _messages: Array[Dictionary] = []
var _offsets: Array[float] = []
var _heights: Dictionary = {}
var _nodes: Dictionary = {}
var _indices: Dictionary = {}
var _total := 0.0
var _width := 0.0
var _laying := false
var _visible: Array[String] = []
var _restore_pending := false
var _restore_queued := false
var _pending_anchor: Dictionary = {}
var _pending_follow := false

func _ready() -> void:
	get_v_scroll_bar().value_changed.connect(func(_value):
		if not _laying and not _restore_pending:
			_render())
	get_v_scroll_bar().gui_input.connect(_user_input)
	gui_input.connect(_user_input)
	resized.connect(_resized)

func set_messages(messages: Array[Dictionary]) -> void:
	var follow := is_at_latest()
	var anchor := get_reading_anchor()
	_messages = messages
	_indices.clear()
	for index in messages.size():
		_indices[messages[index].id] = index
	for id in _nodes.keys():
		if not _indices.has(id):
			_remove(id)
	for id in _heights.keys():
		if not _indices.has(id):
			_heights.erase(id)
	_layout(anchor,follow)

func scroll_to_message(id: String) -> bool:
	if not _indices.has(id):
		return false
	_layout({"id":id,"offset":0.0},false)
	return true

func scroll_to_latest() -> void:
	_layout({},true)

func get_visible_ids() -> Array[String]:
	return _visible.duplicate()

func get_reading_anchor() -> Dictionary:
	if _messages.is_empty() or _offsets.is_empty():
		return {"id":"","offset":0.0}
	if _restore_pending and not _pending_follow and _indices.has(_pending_anchor.get("id","")):
		return _pending_anchor.duplicate()
	if _restore_pending and _pending_follow:
		var target := maxf(0,_total-size.y)
		var target_index := _at(target)
		return {"id":_messages[target_index].id,"offset":target-_offsets[target_index]}
	var index := _at(float(scroll_vertical))
	return {"id":_messages[index].id,"offset":float(scroll_vertical)-_offsets[index]}

func is_at_latest() -> bool:
	if _messages.is_empty(): return true
	if _restore_pending: return _pending_follow
	return float(scroll_vertical) >= _total-size.y-24

func set_audio_state(id: String, state: Dictionary) -> void:
	if _nodes.has(id):
		_nodes[id].set_audio_state(state)

func set_image_state(id: String, state: Dictionary) -> void:
	if _nodes.has(id):
		_nodes[id].set_image_state(state)

func _user_input(event: InputEvent) -> void:
	if (event is InputEventMouseButton and event.pressed) or event is InputEventPanGesture or (event is InputEventKey and event.pressed):
		_restore_pending = false
		interacted.emit()

func _input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed and event.button_index in [MOUSE_BUTTON_WHEEL_UP,MOUSE_BUTTON_WHEEL_DOWN] and get_global_rect().has_point(get_global_mouse_position()):
		_restore_pending = false
		interacted.emit()

func _resized() -> void:
	var anchor := get_reading_anchor()
	var follow := is_at_latest()
	if absf(_width-size.x)>1:
		_heights.clear()
		_width = size.x
	_layout(anchor,follow)

func _process(_delta: float) -> void:
	if _laying or _messages.is_empty():
		return
	var anchor := get_reading_anchor()
	var follow := is_at_latest()
	var changed := false
	for id in _nodes:
		var height: float = maxf(54,_nodes[id].get_combined_minimum_size().y)+17
		if absf(float(_heights.get(id,100))-height)>1:
			_heights[id] = height
			changed = true
	if changed:
		_layout(anchor,follow)

func _layout(anchor: Dictionary, follow: bool) -> void:
	if not is_inside_tree():
		return
	_laying = true
	_pending_anchor = anchor.duplicate()
	_pending_follow = follow
	_restore_pending = true
	_offsets.clear()
	_total = 0
	for message in _messages:
		_offsets.append(_total)
		_total += float(_heights.get(message.id,100))
	_canvas.custom_minimum_size = Vector2(0,_total)
	_canvas.size = Vector2(size.x,_total)
	var bar := get_v_scroll_bar()
	bar.max_value = maxf(_total,size.y)
	bar.page = size.y
	if follow:
		scroll_vertical = maxi(0,roundi(_total-size.y))
	elif _indices.has(anchor.get("id","")):
		scroll_vertical = roundi(_offsets[_indices[anchor.id]]+anchor.offset)
	_laying = false
	_render()
	if not _restore_queued:
		_restore_queued = true
		_defer_scroll_restore.call_deferred()

func _defer_scroll_restore() -> void:
	# A changed canvas minimum queues a parent ScrollContainer sort. Restore
	# after that sort, which can otherwise clamp to the old scroll range.
	_finish_scroll_restore.call_deferred()

func _finish_scroll_restore() -> void:
	_restore_queued = false
	if not _restore_pending or not is_inside_tree(): return
	_laying = true
	var bar := get_v_scroll_bar()
	bar.max_value = maxf(_total,size.y)
	bar.page = size.y
	if _pending_follow:
		scroll_vertical = maxi(0,roundi(_total-size.y))
	elif _indices.has(_pending_anchor.get("id","")):
		scroll_vertical = roundi(_offsets[_indices[_pending_anchor.id]]+_pending_anchor.offset)
	_restore_pending = false
	_laying = false
	_render()

func _render() -> void:
	var wanted: Dictionary = {}
	var visible: Array[String] = []
	if not _messages.is_empty():
		var first := maxi(0,_at(float(scroll_vertical))-2)
		var last := mini(_messages.size()-1,_at(float(scroll_vertical)+size.y)+2)
		for index in range(first,last+1):
			var message: Dictionary = _messages[index]
			var id: String = message.id
			wanted[id] = true
			if not _nodes.has(id):
				var bubble = Bubble.instantiate()
				_canvas.add_child(bubble)
				bubble.configure(message)
				bubble.audio_action.connect(func(action): audio_action.emit(id,action))
				bubble.image_opened.connect(func(texture): image_opened.emit(texture))
				bubble.image_action.connect(func(action): image_action.emit(id,action))
				_nodes[id] = bubble
			else:
				_nodes[id].update_message(message)
			var height := float(_heights.get(id,100))-17
			_nodes[id].position = Vector2(0,_offsets[index])
			_nodes[id].size = Vector2(maxf(1,size.x-16),height)
			if _offsets[index]+height > scroll_vertical and _offsets[index]<scroll_vertical+size.y:
				visible.append(id)
	for id in _nodes.keys():
		if not wanted.has(id):
			_remove(id)
	if visible != _visible:
		_visible = visible
		visible_messages.emit(get_visible_ids())

func _remove(id: String) -> void:
	var node: Node = _nodes[id]
	_canvas.remove_child(node)
	node.queue_free()
	_nodes.erase(id)

func _at(position_y: float) -> int:
	var low := 0
	var high := _offsets.size()-1
	while low < high:
		var middle := (low+high+1)/2
		if _offsets[middle] <= position_y:
			low = middle
		else:
			high = middle-1
	return low
