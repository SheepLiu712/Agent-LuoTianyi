extends "res://src/ui/draft_window.gd"
const Detail = preload("res://src/ui/dynamic_detail.gd")
const TYPES := {"citywalk":"城市漫步","diary":"天依日记","song_learned":"学会新歌","system_notice":"系统通知","user_post":"生活动态"}
var _controller: Node
var _layout_path: String
var _ratio := .45
var _split := HSplitContainer.new()
var _list := VBoxContainer.new()
var _list_scroll := ScrollContainer.new()
var _right := PanelContainer.new()
var _empty := Label.new()
var _unread := Label.new()
var _notice := Label.new()
var _more := Button.new()
var _selected := ""
var _details := {}
var _rows := {}
var _publisher: Window
var _refreshing := false

func _init(controller: Node,layout_path: String = "user://dynamics-window.cfg") -> void:
	_controller = controller
	_layout_path = layout_path
	title = "天依的动态"
	visible = false
	force_native = true
	transient = false
	min_size = Vector2i(900,640)
	size = Vector2i(1000,780)
	var config := ConfigFile.new()
	if config.load(_layout_path) == OK:
		var saved: Variant = config.get_value("window","size",size)
		if saved is Vector2i: size = saved.max(min_size)
		var ratio: Variant = config.get_value("window","ratio",.45)
		if (ratio is float or ratio is int) and is_finite(ratio): _ratio = clampf(ratio,.25,.7)

func _ready() -> void:
	super._ready()
	var panel := PanelContainer.new()
	panel.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	panel.add_theme_stylebox_override("panel",Style.box(Style.SURFACE,0,16))
	add_child(panel)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation",12)
	panel.add_child(column)
	var toolbar := HBoxContainer.new()
	column.add_child(toolbar)
	_unread.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_unread.add_theme_font_size_override("font_size",20)
	toolbar.add_child(_unread)
	toolbar.add_child(Style.button("发布动态",_open_publisher))
	toolbar.add_child(Style.button("刷新",_refresh))
	toolbar.add_child(Style.button("全部已读",_controller.mark_read))
	_notice.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_notice.add_theme_font_size_override("font_size",12)
	column.add_child(_notice)
	_split.size_flags_vertical = Control.SIZE_EXPAND_FILL
	column.add_child(_split)
	var left := VBoxContainer.new()
	left.custom_minimum_size.x = 270
	_split.add_child(left)
	_list_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	_list_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	left.add_child(_list_scroll)
	_list.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_list.add_theme_constant_override("separation",5)
	_list_scroll.add_child(_list)
	left.add_child(_more)
	_more.pressed.connect(func():
		if _controller.get_state().has_more: _controller.load_more()
		else: _controller.refresh())
	_list_scroll.get_v_scroll_bar().value_changed.connect(func(_value): _at_bottom())
	_right.custom_minimum_size.x = 330
	_right.add_theme_stylebox_override("panel",Style.box(Color.WHITE,12,0))
	_split.add_child(_right)
	_empty.text = "选择一条动态"
	_empty.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_empty.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	_right.add_child(_empty)
	_split.resized.connect(_resize_split)
	_split.dragged.connect(func(_offset):
		_ratio = clampf(_split.split_offset/maxf(1,_split.size.x),.25,.7)
		_save_layout())
	size_changed.connect(_save_layout)
	_controller.changed.connect(_update)
	_controller.unread_changed.connect(_update_unread)
	_update()
	_update_unread(_controller.get_state().unread)
	_resize_split.call_deferred()
	if _controller.get_posts().is_empty(): _controller.refresh()

func get_selected_id() -> String:
	return _selected

func select_post(id: String) -> bool:
	var posts: Array = _controller.get_posts().filter(func(post): return post.id == id)
	if posts.is_empty(): return false
	if _selected == id: return true
	_selected = id
	_empty.hide()
	for detail in _details.values(): detail.hide()
	if not _details.has(id):
		var detail = Detail.new(_controller,posts[0])
		_details[id] = detail
		_right.add_child(detail)
	_details[id].show()
	_select_style()
	var state: Dictionary = _controller.get_comments(id)
	if not state.loaded and not state.busy: _controller.load_comments(id)
	return true

func is_dirty() -> bool:
	if is_instance_valid(_publisher) and _publisher.is_dirty(): return true
	return _details.values().any(func(detail): return detail.is_dirty())

func _update_unread(count: int) -> void:
	_unread.text = "动态"+(" · "+("99+" if count>99 else str(count)) if count else "")
	_notice.text = "有新的动态或评论，点击刷新查看。" if count else ""
	var code: String = _controller.get_state().unread_code
	if code not in ["","OK"]: _notice.text += " 未读操作失败（%s）。"%code

func _update() -> void:
	var state: Dictionary = _controller.get_state()
	_more.visible = state.busy or state.has_more or state.code not in ["","OK"]
	_more.disabled = state.busy
	_more.text = "加载中…" if state.busy else ("重试加载动态" if state.code not in ["","OK"] else "加载更多动态")
	var posts: Array = _controller.get_posts()
	for index in posts.size():
		var post: Dictionary = posts[index]
		if not _rows.has(post.id):
			var row := Button.new()
			row.name = "Post_"+post.id
			row.custom_minimum_size.y = 102
			row.clip_contents = true
			row.pressed.connect(func(): select_post(post.id))
			_list.add_child(row)
			_rows[post.id] = row
			var content := HBoxContainer.new()
			content.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
			content.offset_left = 14
			content.offset_right = -14
			content.offset_top = 14
			content.offset_bottom = -10
			row.add_child(content)
			content.add_child(Style.avatar(Detail.avatar_path(post),38))
			var labels := VBoxContainer.new()
			labels.size_flags_horizontal = Control.SIZE_EXPAND_FILL
			content.add_child(labels)
			for text in [post.author_name,TYPES.get(post.get("source_type",""),"动态")+" · "+post.created_at,post.content.replace("\n"," ")]:
				var label := Style.label(text,14 if labels.get_child_count()!=1 else 11)
				label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
				labels.add_child(label)
			_ignore_mouse(content)
		_list.move_child(_rows[post.id],index)
		if _details.has(post.id): _details[post.id].update_post(post)
	_select_style()

func _select_style() -> void:
	for id in _rows:
		var box := Style.box(Color("e3f5ff") if id==_selected else Color.WHITE,10,10)
		if id == _selected:
			box.border_color = Style.ACCENT
			box.border_width_left = 4
		_rows[id].add_theme_stylebox_override("normal",box)

func _refresh() -> void:
	if _refreshing: return
	_refreshing = true
	await _controller.refresh()
	if _details.has(_selected): await _details[_selected].refresh_comments()
	_refreshing = false

func _open_publisher() -> void:
	if not is_instance_valid(_publisher):
		_publisher = load("res://scenes/ui/publish_window.tscn").instantiate()
		_publisher.setup(_controller)
		add_child(_publisher)
		_publisher.published.connect(func(id):
			_update()
			select_post(id)
			_list_scroll.scroll_vertical = 0)
	_publisher.open()

func _at_bottom() -> void:
	var bar := _list_scroll.get_v_scroll_bar()
	var state: Dictionary = _controller.get_state()
	if bar.value+bar.page >= bar.max_value-24 and state.has_more and not state.busy and state.code in ["","OK"]:
		_controller.load_more()

func _resize_split() -> void:
	_split.split_offset = int(_split.size.x*_ratio)

func _save_layout() -> void:
	if mode == Window.MODE_MINIMIZED: return
	var config := ConfigFile.new()
	config.set_value("window","size",size)
	config.set_value("window","ratio",_ratio)
	config.save(_layout_path)

func _ignore_mouse(node: Control) -> void:
	node.mouse_filter = Control.MOUSE_FILTER_IGNORE
	for child in node.get_children():
		if child is Control: _ignore_mouse(child)
