extends "res://src/ui/draft_window.gd"
@export var window_system: Resource = preload("res://src/platform/window_system.gd").new()
const Detail = preload("res://src/ui/dynamic_detail.gd")
const DetailScene = preload("res://scenes/ui/dynamic_detail.tscn")
const PostRow = preload("res://scenes/ui/dynamics_post_row.tscn")
@onready var _unread: Label = %Unread
@onready var _notice: Label = %Notice
@onready var _split: HSplitContainer = %Split
@onready var _list_scroll: ScrollContainer = %ListScroll
@onready var _list: VBoxContainer = %List
@onready var _right: PanelContainer = %Right
@onready var _empty: Label = %Empty
@onready var _publish: Button = %Publish
@onready var _refresh_button: Button = %Refresh
@onready var _read_all: Button = %ReadAll
var _controller: Node
@export var settings: Resource = preload("res://src/storage/settings_store.gd").new()
var _ratio := .35
var _selected := ""
var _details := {}
var _detail_scroll_positions := {}
var _rows := {}
var _publisher: Control
var _refreshing := false
var _initialized := false
var _ui_style: RefCounted
var _panel_style: StyleBoxFlat
var _right_style: StyleBoxFlat

func set_ui_style(style: RefCounted) -> void:
	if _ui_style != null and _ui_style.style_changed.is_connected(_apply_ui_style):
		_ui_style.style_changed.disconnect(_apply_ui_style)
	_ui_style = style
	style.apply_view(self, {"Publish":"action_edit", "Refresh":"action_refresh", "ReadAll":"action_check_all"})
	_ui_style.style_changed.connect(_apply_ui_style)
	if is_node_ready(): _apply_ui_style()

func _apply_ui_style() -> void:
	if _ui_style == null or not is_node_ready(): return
	if _panel_style == null:
		_panel_style = (get_node('Panel').get_theme_stylebox('panel') as StyleBoxFlat).duplicate() as StyleBoxFlat
	if _right_style == null:
		_right_style = _right.get_theme_stylebox("panel").duplicate() as StyleBoxFlat
	_ui_style.apply_surface_style(_panel_style)
	_ui_style.apply_surface_style(_right_style)
	get_node('Panel').add_theme_stylebox_override('panel', _panel_style)
	_right.add_theme_stylebox_override("panel", _right_style)

func setup(controller: Node,settings_store: Resource = null) -> void:
	_controller = controller
	if settings_store != null: settings = settings_store
	if is_node_ready(): _initialize()

func _ready() -> void:
	super._ready()
	if _controller == null: return
	_initialize()

func _initialize() -> void:
	if _initialized: return
	_initialized = true
	var config = settings
	if config.load_settings() == OK:
		var saved: Variant = config.get_value("window","size",size)
		if saved is Vector2i: size = saved.max(min_size)
		var ratio: Variant = config.get_value("window","ratio",.35)
		if (ratio is float or ratio is int) and is_finite(ratio): _ratio = clampf(ratio,.25,.7)
	_publish.pressed.connect(_open_publisher)
	_refresh_button.pressed.connect(_refresh)
	_read_all.pressed.connect(_controller.mark_read)
	_list_scroll.get_v_scroll_bar().value_changed.connect(func(_value): _at_bottom())
	_list_scroll.gui_input.connect(_list_input)
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
	if _selected == id:
		_refresh_selected_comments(id)
		return true
	if not _selected.is_empty() and _details.has(_selected):
		_detail_scroll_positions[_selected] = _details[_selected].get_reading_position()
	_selected = id
	_empty.hide()
	for detail in _details.values(): detail.hide()
	if not _details.has(id):
		var detail = DetailScene.instantiate()
		if _ui_style != null: detail.set_ui_style(_ui_style)
		detail.setup(_controller,posts[0])
		_details[id] = detail
		_right.add_child(detail)
	_details[id].show()
	var position := int(_detail_scroll_positions.get(id, 0))
	_details[id].restore_reading_position(position)
	_select_style()
	_refresh_selected_comments(id)
	return true

func _refresh_selected_comments(id: String) -> void:
	var state: Dictionary = _controller.get_comments(id)
	if not state.busy: _details[id].refresh_comments()

func is_dirty() -> bool:
	if is_instance_valid(_publisher) and _publisher.is_dirty(): return true
	return _details.values().any(func(detail): return detail.is_dirty())

func _update_unread(count: int) -> void:
	_unread.text = "动态"+(" · "+("99+" if count>99 else str(count)) if count else "")
	_notice.text = "有新的动态或评论，点击卡片查看最新评论，刷新可更新动态列表。" if count else ""
	var state: Dictionary = _controller.get_state()
	if state.busy:
		_notice.text += " 正在加载动态…"
	elif state.code not in ["","OK"]:
		_notice.text += " 动态加载失败（%s），滚动到底部或点击刷新重试。" % state.code
	var code: String = state.unread_code
	if code not in ["","OK"]: _notice.text += " 未读操作失败（%s）。"%code

func _update() -> void:
	var state: Dictionary = _controller.get_state()
	_update_unread(state.unread)
	var posts: Array = _controller.get_posts()
	for index in posts.size():
		var post: Dictionary = posts[index]
		if not _rows.has(post.id):
			var row = PostRow.instantiate()
			row.name = "Post_"+post.id
			row.setup(post,Detail.avatar_path(post))
			row.pressed.connect(func(): select_post(post.id))
			_list.add_child(row)
			_rows[post.id] = row
		_list.move_child(_rows[post.id],index)
		if _details.has(post.id): _details[post.id].update_post(post)
	_select_style()

func _select_style() -> void:
	for id in _rows:
		var style := get_theme_stylebox("selected" if id == _selected else "normal", "DynamicsPost")
		_rows[id].add_theme_stylebox_override("normal", style)

func _refresh() -> void:
	if _refreshing: return
	_refreshing = true
	await _controller.refresh()
	if _details.has(_selected): await _details[_selected].refresh_comments()
	_refreshing = false

func _open_publisher() -> void:
	if not is_instance_valid(_publisher):
		_publisher = load("res://scenes/ui/publish_overlay.tscn").instantiate()
		if _ui_style != null:
			_ui_style.apply_view(_publisher, {"PublishButton":"action_send", "CancelPublish":"action_close"})
		_publisher.setup(_controller)
		add_child(_publisher)
		_publisher.published.connect(func(id):
			_update()
			select_post(id)
			_list_scroll.scroll_vertical = 0)
	_publisher.open()

func _list_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_WHEEL_DOWN:
		_at_bottom.call_deferred()

func _at_bottom() -> void:
	var bar := _list_scroll.get_v_scroll_bar()
	var state: Dictionary = _controller.get_state()
	if bar.value+bar.page >= bar.max_value-24 and state.has_more and not state.busy:
		_controller.load_more()

func _resize_split() -> void:
	_split.split_offset = int(_split.size.x*_ratio)

func _save_layout() -> void:
	if window_system.minimized(self): return
	var config = settings
	config.set_value("window","size",size)
	config.set_value("window","ratio",_ratio)
	config.save_settings()
