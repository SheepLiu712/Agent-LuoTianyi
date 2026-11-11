extends ScrollContainer
signal visible_messages(ids: Array[String])
signal older_requested
signal interacted
signal audio_action(id: String, action: String)
signal image_opened(texture: Texture2D)
signal image_action(id: String, action: String)
const Bubble = preload("res://scenes/ui/message_bubble.tscn")
const ChatTime = preload("res://src/ui/chat_time.gd")
## 送达结果不确定的消息按「没发生过」处理：不建气泡、不占高度、退出也不会因此拦人。
const HIDDEN_STATUSES: Array[String] = ["uncertain", "superseded"]
@onready var _canvas: Control = %Canvas
var _messages: Array[Dictionary] = []
var _offsets: Array[float] = []
var _heights: Dictionary = {}
var _nodes: Dictionary = {}
var _indices: Dictionary = {}
var _time_markers: Dictionary = {}
var _total := 0.0
var _width := 0.0
var _laying := false
var _visible: Array[String] = []
var _restore_pending := false
var _restore_queued := false
var _measure_queued := false
var _pending_anchor: Dictionary = {}
var _pending_follow := false
## 用户最后稳定看到的正文位置：异步图片改高度时用它补偿，避免重排后的中间状态污染锚点。
var _stable_anchor: Dictionary = {}
var _stable_follow := true
var _stable_ready := false
var _ui_style: RefCounted
var _older_state := "idle"
var _older_armed := false
var _user_avatar: Texture2D

func set_user_avatar(texture: Texture2D) -> void:
	_user_avatar = texture
	for bubble in _nodes.values(): bubble.set_user_avatar(texture)

func set_ui_style(style: RefCounted) -> void:
	_ui_style = style
	for bubble in _nodes.values(): bubble.set_ui_style(style)

func _ready() -> void:
	get_v_scroll_bar().value_changed.connect(func(_value):
		if not _laying and not _restore_pending:
			_capture_stable_now()
			_render()
			_request_older())
	get_v_scroll_bar().gui_input.connect(_user_input)
	gui_input.connect(_user_input)
	resized.connect(_resized)

func set_messages(messages: Array[Dictionary]) -> void:
	var follow := _layout_follow()
	var anchor := _layout_anchor()
	var anchor_index := int(_indices.get(str(anchor.get("id", "")), -1))
	_messages = _renderable(messages)
	if _messages.is_empty():
		_stable_anchor = {}
		_stable_follow = true
		_stable_ready = true
		_older_armed = false
		_layout({}, true)
		return
	_sync_time_markers()
	_rebuild_indices()
	_prune_missing()
	anchor = _resolve_anchor(anchor, anchor_index)
	_older_armed = false
	_layout(anchor, follow)

func _sync_time_markers() -> void:
	var next_markers := ChatTime.markers(_messages)
	for id in _heights.keys():
		if _time_markers.get(id, "") != next_markers.get(id, ""):
			_heights.erase(id)
	_time_markers = next_markers

func _rebuild_indices() -> void:
	_indices.clear()
	for index in _messages.size():
		_indices[_messages[index].id] = index

func _prune_missing() -> void:
	for id in _nodes.keys():
		if not _indices.has(id):
			_remove(id)
	for id in _heights.keys():
		if not _indices.has(id):
			_heights.erase(id)

func _resolve_anchor(anchor: Dictionary, anchor_index: int) -> Dictionary:
	if anchor.is_empty() or _indices.has(str(anchor.get("id", ""))):
		return anchor
	return {"id":_messages[clampi(anchor_index, 0, _messages.size()-1)].id, "offset":0.0}

## 不可见状态在入口就剔掉，后面的索引、偏移、可见集合才和屏幕上真正有的气泡一致。
func _renderable(messages: Array[Dictionary]) -> Array[Dictionary]:
	var kept: Array[Dictionary] = []
	for message in messages:
		if not HIDDEN_STATUSES.has(str(message.get("status", ""))):
			kept.append(message)
	return kept

## 上翻到顶部一屏内才请求；同一批没回来之前不重复触发。
func _request_older() -> void:
	if not _can_request_older():
		return
	_older_armed = true
	older_requested.emit()

func _can_request_older() -> bool:
	if _older_armed or _older_state == "exhausted" or _messages.is_empty():
		return false
	return float(scroll_vertical) <= size.y * 0.5

func set_older_state(state: String) -> void:
	_older_state = state
	if state != "loading":
		_older_armed = false

func scroll_to_message(id: String) -> bool:
	if not _indices.has(id):
		return false
	_stable_anchor = {"id":id, "offset":0.0}
	_stable_follow = false
	_stable_ready = true
	_layout({"id":id,"offset":0.0},false)
	return true

func scroll_to_latest() -> void:
	_stable_anchor = {}
	_stable_follow = true
	_stable_ready = true
	_layout({},true)

func get_visible_ids() -> Array[String]:
	return _visible.duplicate()

func has_message(id: String) -> bool:
	return _indices.has(id)

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

func get_stable_anchor() -> Dictionary:
	return _stable_anchor.duplicate(true)

## 只在稳定状态下采样：用户滚动后或布局恢复完成后。
func _capture_stable_now() -> void:
	if _messages.is_empty() or _offsets.is_empty():
		_stable_anchor = {}
		_stable_follow = true
		_stable_ready = true
		return
	var index := _at(float(scroll_vertical))
	_stable_anchor = {
		"id":_messages[index].id,
		"offset":float(scroll_vertical)-_offsets[index],
	}
	_stable_follow = float(scroll_vertical) >= _total-size.y-24
	_stable_ready = true

## 内容驱动的重排不得读取 pending 锚点；pending 只服务于它自己的延迟恢复。
func _layout_anchor() -> Dictionary:
	if _stable_ready:
		if _stable_anchor.is_empty():
			return {"id":"", "offset":0.0}
		if _indices.has(str(_stable_anchor.get("id", ""))):
			return _stable_anchor.duplicate(true)
	return get_reading_anchor()

func _layout_follow() -> bool:
	return _stable_follow if _stable_ready else is_at_latest()

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
		_capture_stable_now.call_deferred()
		interacted.emit()

func _input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed and event.button_index in [MOUSE_BUTTON_WHEEL_UP,MOUSE_BUTTON_WHEEL_DOWN] and get_global_rect().has_point(get_global_mouse_position()):
		_restore_pending = false
		_capture_stable_now.call_deferred()
		interacted.emit()

func _resized() -> void:
	var anchor := _layout_anchor()
	var follow := _layout_follow()
	if absf(_width-size.x)>1:
		_heights.clear()
		_width = size.x
	_layout(anchor,follow)

## 高度变化由气泡的最小尺寸信号驱动；不再每帧遍历所有可见控件。
func _queue_measure() -> void:
	if _measure_queued:
		return
	_measure_queued = true
	_measure_heights.call_deferred()


func _measure_heights() -> void:
	_measure_queued = false
	if _laying or _messages.is_empty():
		_queue_measure()
		return
	var anchor := _layout_anchor()
	var follow := _layout_follow()
	var changed := false
	for id in _nodes:
		if not _indices.has(id):
			continue
		var system_message: bool = _nodes[id].get_node("%System").visible
		var minimum_height := 18.0 if system_message else 54.0
		var spacing := 4.0 if system_message else 17.0
		var height: float = maxf(minimum_height,_nodes[id].get_combined_minimum_size().y)+spacing
		if absf(float(_heights.get(id,100))-height)>1:
			_heights[id] = height
			changed = true
	if changed:
		_layout(anchor,follow)


func _bubble_minimum_changed(id: String) -> void:
	if _nodes.has(id):
		_queue_measure()

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
	# 画布最小尺寸变化会让父 ScrollContainer 排队重排；必须在重排之后恢复，否则会被夹到旧滚动范围。
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
	_capture_stable_now()

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
				_create_bubble(id, message)
			else:
				_nodes[id].update_message(message)
			_nodes[id].set_time_marker(_time_markers.get(id, ""))
			var spacing := 4.0 if message.role == "system" else 17.0
			var height := float(_heights.get(id,100))-spacing
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

func _create_bubble(id: String, message: Dictionary) -> void:
	var bubble = Bubble.instantiate()
	if _ui_style != null: bubble.set_ui_style(_ui_style)
	bubble.set_user_avatar(_user_avatar)
	_canvas.add_child(bubble)
	bubble.configure(message)
	bubble.audio_action.connect(func(action): audio_action.emit(id,action))
	bubble.image_opened.connect(func(texture): image_opened.emit(texture))
	bubble.image_action.connect(func(action): image_action.emit(id,action))
	_nodes[id] = bubble
	bubble.minimum_size_changed.connect(_bubble_minimum_changed.bind(id))
	_queue_measure()
