extends "res://src/ui/draft_window.gd"
@export var window_system: Resource = preload("res://src/platform/window_system.gd").new()
const Detail = preload("res://src/ui/dynamic_detail.gd")
const DetailScene = preload("res://scenes/ui/dynamics/dynamic_detail.tscn")
const PostRow = preload("res://scenes/ui/dynamics/dynamics_post_row.tscn")
const PublishOverlay = preload("res://scenes/ui/dynamics/publish_overlay.tscn")
const ErrorDialog = preload("res://src/ui/error_dialog.gd")
const StatusBanner = preload("res://src/ui/status_banner.gd")
const ToastOverlay = preload("res://src/ui/toast_overlay.gd")
@onready var _unread: Label = %Unread
@onready var _notice_banner: PanelContainer = %NoticeBanner
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
const PLACEHOLDERS := {
	"loading": "正在加载动态…",
	"empty": "还没有动态，发布第一条吧。",
	"failed": "暂无动态",
	"unselected": "选择左侧一条动态查看评论。",
}
var _ratio := .35
var _selected := ""
var _details := {}
var _detail_scroll_positions := {}
var _rows := {}
var _publisher: Control
var _refreshing := false
var _last_failure_code := ""
var _last_unread_code := ""
var _initialized := false
var _ui_style: RefCounted
var _right_style: StyleBoxFlat
var _avatar_source: Node
var _custom_avatar: Texture2D
var _username := ""

## 头像源由装配层给出；这里只把纹理转发给每一行和每个详情，重建列表交给控制器。
func set_avatar_source(source: Node) -> void:
	if _avatar_source != null and _avatar_source.avatar_changed.is_connected(_sync_avatar):
		_avatar_source.avatar_changed.disconnect(_sync_avatar)
	_avatar_source = source
	if source == null:
		return
	source.avatar_changed.connect(_sync_avatar)
	_sync_avatar(source.get_texture())

func _sync_avatar(texture: Texture2D) -> void:
	_custom_avatar = texture
	_username = _avatar_source.get_username() if _avatar_source != null else ""
	for id in _rows:
		_rows[id].set_avatar(_row_avatar(_find_post(str(id))))
	for id in _details:
		_details[id].set_avatar_context(texture, _username)

func _row_avatar(post: Dictionary) -> Texture2D:
	return Detail.avatar_texture(post, _custom_avatar, _username)

func _find_post(id: String) -> Dictionary:
	for post in _controller.get_posts():
		if str(post.id) == id:
			return post
	return {}

func set_ui_style(style: RefCounted) -> void:
	if _ui_style != null and _ui_style.style_changed.is_connected(_apply_ui_style):
		_ui_style.style_changed.disconnect(_apply_ui_style)
	_ui_style = style
	style.apply_view(self, {"Publish":"action_edit", "Refresh":"action_refresh", "ReadAll":"action_check_all"})
	_ui_style.style_changed.connect(_apply_ui_style)
	if is_node_ready(): _apply_ui_style()

func _apply_ui_style() -> void:
	if _ui_style == null or not is_node_ready(): return
	if _right_style == null:
		_right_style = _right.get_theme_stylebox("panel").duplicate() as StyleBoxFlat
	_ui_style.apply_surface_style(_right_style)
	_right.add_theme_stylebox_override("panel", _right_style)
	if _notice_banner.visible:
		StatusBanner.apply_surface_status(_notice_banner, _notice, "info", _ui_style)
	_select_style()

func setup(controller: Node,settings_store: Resource = null) -> void:
	_controller = controller
	if settings_store != null: settings = settings_store
	if is_node_ready(): _initialize()

func _ready() -> void:
	super._ready()
	_apply_ui_style()
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
	else:
		push_warning("Dynamics window layout could not be loaded")
	_publish.pressed.connect(_open_publisher)
	_refresh_button.pressed.connect(_refresh)
	_read_all.pressed.connect(func():
		_controller.mark_read()
		ToastOverlay.present_in(self, "已全部标为已读。", "success", 2.0, _ui_style))
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
	# 只有「一次也没取过」才在开窗时补拉；空列表与失败都有各自的占位和重试入口，
	# 开窗时再拉一次会把已经落定的状态改写成加载中。
	if _controller.get_state().code.is_empty(): _controller.refresh()

func get_selected_id() -> String:
	return _selected

func select_post(id: String) -> bool:
	var posts: Array = _controller.get_posts().filter(func(post): return post.id == id)
	if posts.is_empty(): return false
	if _selected == id:
		_refresh_selected_comments(id)
		return true
	# 点开就算读过：已读时间戳推到这条的发布时间，圆点随之消退。
	if _controller.is_unread(posts[0]): _controller.mark_read(posts[0].created_at)
	if not _selected.is_empty() and _details.has(_selected):
		_detail_scroll_positions[_selected] = _details[_selected].get_reading_position()
	_selected = id
	_empty.hide()
	for detail in _details.values(): detail.hide()
	if not _details.has(id):
		var detail = DetailScene.instantiate()
		if _ui_style != null: detail.set_ui_style(_ui_style)
		detail.setup(_controller,posts[0])
		detail.set_avatar_context(_custom_avatar, _username)
		_details[id] = detail
		_right.add_child(detail)
	_details[id].show()
	var position := int(_detail_scroll_positions.get(id, 0))
	_details[id].restore_reading_position(position)
	_select_style()
	_refresh_selected_comments(id)
	return true

## 角色卡片携带的是服务端预览快照：列表已加载时直接选中；
## 否则等当前刷新完成。刷新成功仍找不到时视为已删除，
## 只有网络失败才退回快照，避免把临时断网当成删除。
func open_post(post: Dictionary) -> bool:
	if _controller == null or post.is_empty():
		return false
	var id := str(post.get("id", ""))
	if id.is_empty():
		return false
	if select_post(id):
		return true
	await _controller.refresh()
	if select_post(id):
		return true
	if str(_controller.get_state().code) in ["", "OK"]:
		return false
	_controller.accept_post(post)
	return select_post(id)

func _refresh_selected_comments(id: String) -> void:
	var state: Dictionary = _controller.get_comments(id)
	if not state.busy: _details[id].refresh_comments()

func is_dirty() -> bool:
	if is_instance_valid(_publisher) and _publisher.is_dirty(): return true
	return _details.values().any(func(detail): return detail.is_dirty())

func _update_unread(count: int) -> void:
	_unread.text = "动态"+(" · "+("99+" if count>99 else str(count)) if count else "")
	var text := _notice_text(count, _controller.get_state())
	_notice.text = text
	_notice_banner.visible = not text.is_empty()
	if _notice_banner.visible:
		StatusBanner.apply_surface_status(_notice_banner, _notice, "info", _ui_style)

## 只为「已有内容但加载失败」和未读失败保留横幅；首屏状态交给占位文案。
func _notice_text(count: int, state: Dictionary) -> String:
	return "有新的动态或评论，点击卡片查看最新评论，刷新可更新动态列表。" if count else ""

## 翻页失败不会把 phase 推成 failed，只看 phase 会漏报，所以以 code 兜底。
func _shows_failure(state: Dictionary) -> bool:
	if _controller.get_posts().is_empty(): return false
	return state.phase == "failed" or str(state.code) not in ["","OK"]

func _update() -> void:
	var state: Dictionary = _controller.get_state()
	_announce_failures(state)
	_update_unread(state.unread)
	var posts: Array = _controller.get_posts()
	_sync_rows(posts)
	_sync_details(posts)
	_sync_selection(posts)
	_refresh_placeholder(posts, state)

func _announce_failures(state: Dictionary) -> void:
	_announce_posts_failure(state)
	_announce_unread_failure(state)

func _announce_posts_failure(state: Dictionary) -> void:
	var code := str(state.code)
	var first_failed: bool = state.phase == "failed" and _controller.get_posts().is_empty()
	if (_shows_failure(state) or first_failed) and code != _last_failure_code:
		_last_failure_code = code
		ErrorDialog.present(self, "暂时加载不出动态，点击重试。" if first_failed else "刷新失败，点击重试。")
	elif not _shows_failure(state) and not first_failed:
		_last_failure_code = ""

func _announce_unread_failure(state: Dictionary) -> void:
	var unread := str(state.unread_code)
	if unread not in ["", "OK"] and unread != _last_unread_code:
		_last_unread_code = unread
		ErrorDialog.present(self, "未读状态同步失败。")
	elif unread in ["", "OK"]:
		_last_unread_code = ""

## 服务端已删除的动态必须连同行、详情和缓存一起消失，否则刷新只会越积越多。
func _sync_rows(posts: Array) -> void:
	var live := {}
	for index in posts.size():
		var post: Dictionary = posts[index]
		live[str(post.id)] = true
		if not _rows.has(post.id):
			_rows[post.id] = _create_row(post)
		_rows[post.id].set_avatar(_row_avatar(post))
		_rows[post.id].set_unread(_controller.is_unread(post))
		_list.move_child(_rows[post.id], index)
		if _details.has(post.id): _details[post.id].update_post(post)
	for id in _rows.keys():
		if live.has(id): continue
		_list.remove_child(_rows[id])
		_rows[id].queue_free()
		_rows.erase(id)
	_select_style()


func _create_row(post: Dictionary) -> Control:
	var row = PostRow.instantiate()
	row.name = "Post_"+str(post.id)
	row.setup(post,_row_avatar(post))
	row.pressed.connect(func(): select_post(post.id))
	_list.add_child(row)
	return row


func _sync_details(posts: Array) -> void:
	var live := {}
	for post in posts:
		live[str(post.id)] = true
	for id in _details.keys():
		if live.has(id): continue
		_right.remove_child(_details[id])
		_details[id].queue_free()
		_details.erase(id)
		_detail_scroll_positions.erase(id)


func _sync_selection(posts: Array) -> void:
	if _selected.is_empty():
		return
	for post in posts:
		if str(post.id) == _selected:
			return
	_selected = ""
	for detail in _details.values(): detail.hide()


## 四种状态互斥：加载中、空列表、失败可重试、未选择动态。
func _refresh_placeholder(posts: Array, state: Dictionary) -> void:
	var text := _placeholder_text(posts, state)
	_empty.text = text
	_empty.visible = not text.is_empty()
	_refresh_button.disabled = bool(state.busy)


func _placeholder_text(posts: Array, state: Dictionary) -> String:
	if state.phase == "loading" and posts.is_empty():
		return PLACEHOLDERS.loading
	if state.phase == "failed":
		return PLACEHOLDERS.failed
	if posts.is_empty():
		return PLACEHOLDERS.empty
	return PLACEHOLDERS.unselected if _selected.is_empty() else ""

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
		_publisher = PublishOverlay.instantiate()
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
	if config.save_settings() != OK:
		push_warning("Dynamics window layout could not be saved")
