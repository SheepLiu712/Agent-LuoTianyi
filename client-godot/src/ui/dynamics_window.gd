extends "res://src/ui/draft_window.gd"
@export var window_system: Resource = preload("res://src/platform/window_system.gd").new()
const Detail = preload("res://src/ui/dynamic_detail.gd")
const DetailScene = preload("res://scenes/ui/dynamics/dynamic_detail.tscn")
const PostRow = preload("res://scenes/ui/dynamics/dynamics_post_row.tscn")
const PublishOverlay = preload("res://scenes/ui/dynamics/publish_overlay.tscn")
const ErrorDialog = preload("res://src/ui/error_dialog.gd")
const ToastOverlay = preload("res://src/ui/toast_overlay.gd")
const UiMotion = preload("res://src/ui/ui_motion.gd")
@onready var _unread_chip: PanelContainer = %UnreadChip
@onready var _unread: Label = %Unread
@onready var _notice_wrap: MarginContainer = %NoticeWrap
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
var _drafts: RefCounted
var _scope := ""
@export var settings: Resource = preload("res://src/storage/settings_store.gd").new()
var _ratio := .35
var _selected := ""
var _read_request_key := ""
var _details := {}
var _detail_scroll_positions := {}
var _rows := {}
var _publisher: Control
var _refreshing := false
var _notice_dismissed := false
var _last_hint := false
var _last_failure_code := ""
var _last_unread_code := ""
var _initialized := false
var _ui_style: RefCounted
var _avatar_source: Node
var _custom_avatar: Texture2D
var _username := ""


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
	_ui_style.style_changed.connect(_apply_ui_style)
	if is_node_ready(): _apply_ui_style()


func _apply_ui_style() -> void:
	if _ui_style == null or not is_node_ready(): return
	_ui_style.apply_view(self, {"Publish":"action_edit", "Refresh":"action_refresh", "ReadAll":"action_check_all"})
	for button in [_publish, _refresh_button, _read_all]:
		button.add_theme_constant_override("icon_max_width", 16)
	_select_style()


func setup(controller: Node, settings_store: Resource = null, drafts: RefCounted = null, scope: String = "") -> void:
	_controller = controller
	if settings_store != null: settings = settings_store
	_drafts = drafts
	_scope = scope
	if is_node_ready(): _initialize()


func _ready() -> void:
	super._ready()
	UiMotion.bind_interactive_cursors(self)
	UiMotion.bind_tactile_press(%Publish, func(): return _ui_style)
	_apply_ui_style()
	if _controller == null: return
	_initialize()


func _unhandled_input(event: InputEvent) -> void:
	if not visible or not (event is InputEventKey and event.pressed and not event.echo):
		return
	if event.is_action_pressed("ui_cancel") and not is_instance_valid(_publisher):
		get_viewport().set_input_as_handled()
		close_requested.emit()
	elif event.keycode == KEY_F5 or (event.ctrl_pressed and event.keycode == KEY_R):
		get_viewport().set_input_as_handled()
		_refresh()


func _initialize() -> void:
	if _initialized: return
	_initialized = true
	var config = settings
	if config.load_settings() == OK:
		var saved: Variant = config.get_value("window", "size", size)
		if saved is Vector2i: size = saved.max(min_size)
		var ratio: Variant = config.get_value("window", "ratio", .35)
		if (ratio is float or ratio is int) and is_finite(ratio): _ratio = clampf(ratio, .25, .7)
	else:
		push_warning("Dynamics window layout could not be loaded")
	_publish.pressed.connect(_open_publisher)
	_refresh_button.pressed.connect(_refresh)
	%NoticeRefresh.pressed.connect(_refresh)
	%NoticeClose.pressed.connect(func():
		_notice_dismissed = true
		_notice_wrap.hide())
	%ListEmptyAction.pressed.connect(_on_empty_action)
	_read_all.pressed.connect(func():
		_controller.mark_read()
		ToastOverlay.present_in(self, "已全部标为已读。", "success", 2.0, _ui_style))
	_list_scroll.get_v_scroll_bar().value_changed.connect(func(_value): _at_bottom())
	_list_scroll.gui_input.connect(_list_input)
	_split.resized.connect(_resize_split)
	_split.dragged.connect(func(_offset):
		_ratio = clampf(_split.split_offset / maxf(1, _split.size.x), .25, .7)
		_save_layout())
	size_changed.connect(_save_layout)
	_controller.changed.connect(_update)
	_controller.unread_changed.connect(_update_unread)
	_update()
	_update_unread(_controller.get_state().unread)
	_resize_split.call_deferred()
	if _controller.get_state().code.is_empty(): _controller.refresh()


func get_selected_id() -> String:
	return _selected


func select_post(id: String) -> bool:
	var posts: Array = _controller.get_posts().filter(func(post): return post.id == id)
	if posts.is_empty(): return false
	if _selected == id:
		_refresh_selected_comments(id)
		return true
	if _controller.is_unread(posts[0]):
		_controller.dismiss_preview(posts[0].id)
		_controller.mark_post_read(posts[0].id)
	if not _selected.is_empty() and _details.has(_selected):
		_detail_scroll_positions[_selected] = _details[_selected].get_reading_position()
	_selected = id
	_read_request_key = ""
	_empty.hide()
	for detail in _details.values(): detail.hide()
	if not _details.has(id):
		var detail = DetailScene.instantiate()
		if _ui_style != null: detail.set_ui_style(_ui_style)
		detail.setup(_controller, posts[0], _drafts, _scope)
		detail.set_avatar_context(_custom_avatar, _username)
		_details[id] = detail
		_right.add_child(detail)
	_details[id].show()
	var position := int(_detail_scroll_positions.get(id, 0))
	_details[id].restore_reading_position(position)
	_select_style()
	_refresh_selected_comments(id)
	return true


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


func flush_drafts() -> bool:
	var ok := true
	if is_instance_valid(_publisher):
		ok = bool(_publisher.flush_drafts()) and ok
	for detail in _details.values():
		if is_instance_valid(detail):
			ok = bool(detail.flush_drafts()) and ok
	return ok


func loss_warnings() -> Array[String]:
	if _drafts == null or _scope.is_empty():
		return super.loss_warnings()
	var warnings: Array[String] = []
	if is_instance_valid(_publisher):
		for item in _publisher.loss_warnings():
			warnings.append(str(item))
	for detail in _details.values():
		if is_instance_valid(detail):
			for item in detail.loss_warnings():
				warnings.append(str(item))
	return warnings


func clear_drafts() -> void:
	if is_instance_valid(_publisher):
		_publisher.clear_draft()
	for detail in _details.values():
		if is_instance_valid(detail):
			detail.clear_drafts()


func _update_unread(count: int) -> void:
	_unread_chip.visible = count > 0
	_unread.text = "%s 条未读" % ("99+" if count > 99 else str(count))
	var state: Dictionary = _controller.get_state()
	var hint := bool(state.get("unread_hint", false))
	if hint and not _last_hint:
		_notice_dismissed = false
	_last_hint = hint
	var text := "有新的评论尚未同步到本地列表。" if hint else ""
	_notice.text = text
	_notice_wrap.visible = not text.is_empty() and not _notice_dismissed


func _shows_failure(state: Dictionary) -> bool:
	if _controller.get_posts().is_empty(): return false
	return state.phase == "failed" or str(state.code) not in ["", "OK"]


func _update() -> void:
	var state: Dictionary = _controller.get_state()
	_announce_failures(state)
	_update_unread(state.unread)
	var posts: Array = _controller.get_posts()
	_sync_rows(posts)
	_mark_selected_read(posts)
	_sync_details(posts)
	_sync_selection(posts)
	_refresh_placeholder(posts, state)


func _mark_selected_read(posts: Array) -> void:
	if _selected.is_empty() or not visible:
		return
	for post in posts:
		if str(post.id) != _selected:
			continue
		if not post.has("last_activity_at"):
			return
		if not _controller.is_unread(post):
			_read_request_key = ""
			return
		var key := "%s|%s|%s" % [_selected, post.get("last_activity_at", ""), post.get("last_activity_id", "")]
		if key == _read_request_key:
			return
		_read_request_key = key
		_controller.dismiss_preview(_selected)
		_controller.mark_post_read(_selected)
		return


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


func _sync_rows(posts: Array) -> void:
	var live := {}
	for index in posts.size():
		var post: Dictionary = posts[index]
		live[str(post.id)] = true
		if not _rows.has(post.id):
			_rows[post.id] = _create_row(post)
		_rows[post.id].set_avatar(_row_avatar(post))
		_rows[post.id].set_unread(_controller.is_unread(post))
		var comment_count := int(post.get("comment_count", _controller.get_comments(str(post.id)).items.size()))
		_rows[post.id].set_comment_count(comment_count)
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
	row.name = "Post_" + str(post.id)
	row.setup(post, _row_avatar(post))
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
	_read_request_key = ""
	for detail in _details.values(): detail.hide()


func _refresh_placeholder(posts: Array, state: Dictionary) -> void:
	var empty_list := posts.is_empty()
	_list_scroll.visible = not empty_list
	%ListEmptyState.visible = empty_list
	if empty_list:
		if state.phase == "loading":
			%ListEmptyTitle.text = "正在加载动态…"
			%ListEmptySubtitle.text = "请稍候"
			%ListEmptyAction.visible = false
		elif state.phase == "failed":
			%ListEmptyTitle.text = "加载失败"
			%ListEmptySubtitle.text = "暂时无法获取动态列表"
			%ListEmptyAction.text = "重试"
			%ListEmptyAction.visible = true
		else:
			%ListEmptyTitle.text = "还没有动态"
			%ListEmptySubtitle.text = "天依发布的动态和你的分享都会出现在这里"
			%ListEmptyAction.text = "发布第一条动态"
			%ListEmptyAction.visible = true
	_empty.visible = _selected.is_empty()
	_empty.text = "选择左侧的一条动态查看详情"
	_refresh_button.disabled = bool(state.busy)


func _on_empty_action() -> void:
	if _controller != null and _controller.get_state().phase == "failed":
		_refresh()
	else:
		_open_publisher()


func _select_style() -> void:
	for id in _rows:
		var style := get_theme_stylebox("selected" if id == _selected else "normal", "DynamicsPost")
		_rows[id].add_theme_stylebox_override("normal", style)


func _refresh() -> void:
	if _refreshing: return
	_refreshing = true
	_notice_dismissed = false
	await _controller.refresh()
	if _details.has(_selected): await _details[_selected].refresh_comments()
	_refreshing = false


func _open_publisher() -> void:
	if not is_instance_valid(_publisher):
		_publisher = PublishOverlay.instantiate()
		if _ui_style != null:
			_publisher.set_ui_style(_ui_style)
			_ui_style.apply_view(_publisher, {"PublishButton":"action_send", "CancelPublish":"action_close"})
		_publisher.setup(_controller, _drafts, _scope)
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
	if bar.value + bar.page >= bar.max_value - 24 and state.has_more and not state.busy:
		_controller.load_more()


func _resize_split() -> void:
	_split.split_offset = int(clampf(_split.size.x * _ratio, 300.0, maxf(300.0, _split.size.x - 360.0)))


func _save_layout() -> void:
	if window_system.minimized(self): return
	var config = settings
	config.set_value("window", "size", size)
	config.set_value("window", "ratio", _ratio)
	if config.save_settings() != OK:
		push_warning("Dynamics window layout could not be saved")
