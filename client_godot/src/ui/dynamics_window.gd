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
@onready var _more: Button = %More
@onready var _right: PanelContainer = %Right
@onready var _empty: Label = %Empty
@onready var _publish: Button = %Publish
@onready var _refresh_button: Button = %Refresh
@onready var _read_all: Button = %ReadAll
var _controller: Node
@export var settings: Resource = preload("res://src/storage/settings_store.gd").new()
var _ratio := .45
var _selected := ""
var _details := {}
var _rows := {}
var _publisher: Control
var _refreshing := false
var _initialized := false

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
		var ratio: Variant = config.get_value("window","ratio",.45)
		if (ratio is float or ratio is int) and is_finite(ratio): _ratio = clampf(ratio,.25,.7)
	_publish.pressed.connect(_open_publisher)
	_refresh_button.pressed.connect(_refresh)
	_read_all.pressed.connect(_controller.mark_read)
	_more.pressed.connect(func():
		if _controller.get_state().has_more: _controller.load_more()
		else: _controller.refresh())
	_list_scroll.get_v_scroll_bar().value_changed.connect(func(_value): _at_bottom())
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
		var detail = DetailScene.instantiate()
		detail.setup(_controller,posts[0])
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
	if window_system.minimized(self): return
	var config = settings
	config.set_value("window","size",size)
	config.set_value("window","ratio",_ratio)
	config.save_settings()
