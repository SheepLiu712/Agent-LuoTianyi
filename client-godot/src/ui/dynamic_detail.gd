extends VBoxContainer
const CommentRow = preload("res://scenes/ui/dynamics/dynamic_comment_row.tscn")
const TIANYI_ICON := preload("res://assets/ui/tianyi_icon.png")
const USER_ICON := preload("res://assets/ui/user_icon.png")
const DraftAutosave = preload("res://src/ui/draft_autosave.gd")
const ErrorDialog = preload("res://src/ui/error_dialog.gd")
const ToastOverlay = preload("res://src/ui/toast_overlay.gd")
const UiMotion = preload("res://src/ui/ui_motion.gd")

@onready var _scroll: ScrollContainer = %DetailScroll
@onready var _column: VBoxContainer = %Column
@onready var _avatar: TextureRect = %Avatar
@onready var _author: Label = %Author
@onready var _created_at: Label = %CreatedAt
@onready var _body: RichTextLabel = %Body
@onready var _action_comments: Button = %ActionComments
@onready var _action_copy: Button = %ActionCopy
@onready var _action_more: Button = %ActionMore
@onready var _more_menu: PopupMenu = %MoreMenu
@onready var _comments_heading: Label = %CommentsHeading
@onready var _notice: Label = %Notice
@onready var _composer_bar: PanelContainer = %ComposerBar
@onready var _reply_chip_row: HBoxContainer = %ReplyChipRow
@onready var _reply_label: Label = %ReplyLabel
@onready var _cancel: Button = %CancelReply
@onready var _draft: TextEdit = %CommentDraft
@onready var _send: Button = %Send
@onready var _comments: VBoxContainer = %Comments
@onready var _status: Label = %Status
var _controller: Node
var _post: Dictionary
var _parent := ""
var _drafts: RefCounted
var _scope := ""
var _comment_autosave: RefCounted
var _reply_target_failed := false
var _rows := {}
var _writing := false
var _last_comment_code := ""
var _initialized := false
var _ui_style: RefCounted
var _pending_scroll := -1
var _restore_frames := 0
var _custom_avatar: Texture2D
var _username := ""
var _applying_scroll := false


static func avatar_texture(item: Dictionary, custom: Texture2D, username: String) -> Texture2D:
	var author_type := str(item.get("author_type", ""))
	if custom != null and author_type == "user" and str(item.get("author_name", "")) == username:
		return custom
	return TIANYI_ICON if author_type == "agent" else USER_ICON


func set_avatar_context(texture: Texture2D, username: String) -> void:
	_custom_avatar = texture
	_username = username
	if not is_node_ready():
		return
	_avatar.texture = _avatar_for(_post)
	for item in _controller.get_comments(_post.id).items:
		if _rows.has(item.id): _rows[item.id].set_avatar(_avatar_for(item))


func _avatar_for(item: Dictionary) -> Texture2D:
	return avatar_texture(item, _custom_avatar, _username)


func set_ui_style(style: RefCounted) -> void:
	_ui_style = style


func setup(controller: Node, post: Dictionary, drafts: RefCounted = null, scope: String = "") -> void:
	_controller = controller
	_post = post.duplicate(true)
	_drafts = drafts
	_scope = scope
	if is_node_ready(): _initialize()


func _ready() -> void:
	set_process(false)
	UiMotion.bind_interactive_cursors(self)
	if _controller == null: return
	_initialize()


func _initialize() -> void:
	if _initialized: return
	_initialized = true
	_avatar.texture = _avatar_for(_post)
	_author.text = str(_post.get("author_name", ""))
	_created_at.text = str(_post.get("created_at", ""))
	_send.pressed.connect(_submit)
	_cancel.pressed.connect(_clear_reply_target)
	_action_comments.pressed.connect(func(): _draft.grab_focus())
	_action_copy.pressed.connect(_copy_post_body)
	_action_more.pressed.connect(_open_more_menu)
	_more_menu.id_pressed.connect(_on_more_item)
	_draft.text_changed.connect(_sync_draft_height)
	_scroll.get_v_scroll_bar().value_changed.connect(func(_value): _at_bottom())
	_scroll.get_v_scroll_bar().gui_input.connect(_scroll_input)
	_scroll.gui_input.connect(_scroll_input)
	_column.resized.connect(_queue_restore)
	_controller.changed.connect(update_comments)
	_bind_drafts()
	update_post(_post)
	update_comments()


func _copy_post_body() -> void:
	DisplayServer.clipboard_set(str(_post.get("content", "")))
	ToastOverlay.present_in(self, "已复制动态正文。", "success", 2.0, _ui_style)


func _open_more_menu() -> void:
	var rect := _action_more.get_global_rect()
	_more_menu.popup(Rect2i(Vector2i(int(rect.end.x - 130), int(rect.end.y + 4)), Vector2i(130, 0)))


func _on_more_item(id: int) -> void:
	if id == 0:
		refresh_comments()
	elif id == 1:
		_copy_post_body()


func _sync_draft_height() -> void:
	var lines := _draft.get_line_count()
	for line in _draft.get_line_count():
		lines += _draft.get_line_wrap_count(line)
	_draft.custom_minimum_size.y = clampf(lines * 21.0 + 23.0, 44.0, 88.0)


func update_post(post: Dictionary) -> void:
	_post = post.duplicate(true)
	if _body.text != _post.content: _body.text = _post.content
	_notice.visible = not _post.allow_comment
	_composer_bar.visible = _post.allow_comment
	_draft.editable = _post.allow_comment and not _writing
	_send.disabled = not _draft.editable


func is_dirty() -> bool:
	return _writing or not _draft.text.is_empty()


func get_reading_position() -> int:
	return _pending_scroll if _pending_scroll >= 0 else _scroll.scroll_vertical


func restore_reading_position(position: int) -> void:
	_pending_scroll = maxi(0, position)
	_queue_restore()
	set_process(true)


func _queue_restore() -> void:
	if _pending_scroll >= 0: _restore_frames = 2


func _process(_delta: float) -> void:
	if not is_visible_in_tree(): return
	if _restore_frames > 0:
		_restore_frames -= 1
		return
	var state: Dictionary = _controller.get_comments(_post.id)
	if state.busy: return
	var bar := _scroll.get_v_scroll_bar()
	_applying_scroll = true
	_scroll.scroll_vertical = clampi(_pending_scroll, 0, maxi(0, int(bar.max_value - bar.page)))
	_applying_scroll = false
	_pending_scroll = -1
	set_process(false)


func _scroll_input(event: InputEvent) -> void:
	if not is_visible_in_tree() or not _is_scroll_input(event): return
	_pending_scroll = -1
	set_process(false)
	_at_bottom.call_deferred()


func _is_scroll_input(event: InputEvent) -> bool:
	if event is InputEventPanGesture or event is InputEventScreenDrag: return true
	if event is InputEventKey:
		return event.pressed and event.keycode in [KEY_UP, KEY_DOWN, KEY_PAGEUP, KEY_PAGEDOWN, KEY_HOME, KEY_END]
	if not event is InputEventMouseButton or not event.pressed: return false
	if event.button_index in [MOUSE_BUTTON_WHEEL_UP, MOUSE_BUTTON_WHEEL_DOWN]: return true
	return event.button_index == MOUSE_BUTTON_LEFT and _scroll.get_v_scroll_bar().get_global_rect().has_point(event.global_position)


func update_comments() -> void:
	if not is_node_ready(): return
	var scroll_bar := _scroll.get_v_scroll_bar()
	var previous_scroll := scroll_bar.value
	var state: Dictionary = _controller.get_comments(_post.id)
	_update_comment_status(state)
	var names := {}
	for item in state.items:
		names[item.id] = item.author_name
	var count := maxi(state.items.size(), int(_post.get("comment_count", 0)))
	_action_comments.text = "评论 %d" % count
	_comments_heading.text = "全部评论 · %d" % count
	for index in state.items.size():
		_sync_row(state.items[index], index, names)
	_sync_reply_target(names, state)
	if _pending_scroll >= 0:
		_queue_restore()
	elif previous_scroll > 0:
		restore_reading_position(int(previous_scroll))


func _sync_row(item: Dictionary, index: int, names: Dictionary) -> void:
	var target: String = str(item.get("parent_comment_id", "") if item.get("parent_comment_id") != null else "")
	var reply_to_name := "" if target.is_empty() else str(names.get(target, "较早评论"))
	var is_author := str(item.get("author_type", "")) == str(_post.get("author_type", "")) and str(item.get("author_name", "")) == str(_post.get("author_name", ""))
	if not _rows.has(item.id):
		var row = CommentRow.instantiate()
		row.setup(_avatar_for(item), item.author_name, item.content, relative_time(item.created_at), item.created_at, _post.allow_comment, _reply_to(item), is_author, reply_to_name)
		_comments.add_child(row)
		_rows[item.id] = row
	_rows[item.id].set_avatar(_avatar_for(item))
	_rows[item.id].set_highlighted(str(item.id) == _parent)
	_comments.move_child(_rows[item.id], index)


func _reply_to(item: Dictionary) -> Callable:
	return func():
		if _writing: return
		_set_reply_parent(str(item.id))
		_reply_label.text = "回复 @" + str(item.author_name)
		_sync_reply_chip()
		_draft.grab_focus()


func _clear_reply_target() -> void:
	_set_reply_parent("")
	_sync_reply_chip()


func _sync_reply_chip() -> void:
	_reply_chip_row.visible = not _parent.is_empty()
	for id in _rows:
		_rows[id].set_highlighted(str(id) == _parent)


func _bind_drafts() -> void:
	if _drafts == null or _scope.is_empty():
		return
	_comment_autosave = DraftAutosave.new()
	_comment_autosave.bind(_draft, _drafts, _scope, "dynamics.comment." + str(_post.id))
	_parent = str(_drafts.read_text(_scope, _reply_target_key()))
	_sync_reply_chip()
	_sync_draft_height()


func _set_reply_parent(id: String) -> void:
	_parent = id
	if _drafts == null or _scope.is_empty():
		_reply_target_failed = false
		return
	_reply_target_failed = int(_drafts.write_text(_scope, _reply_target_key(), id)) != OK


func _reply_target_key() -> String:
	return "dynamics.reply_to." + str(_post.id)


func _sync_reply_target(names: Dictionary, state: Dictionary) -> void:
	if _parent.is_empty():
		_sync_reply_chip()
		return
	if names.has(_parent):
		_reply_label.text = "回复 @" + str(names[_parent])
		_sync_reply_chip()
		return
	if not bool(state.get("busy", false)) and bool(state.get("loaded", false)):
		_set_reply_parent("")
		_sync_reply_chip()


func flush_drafts() -> bool:
	var ok := true
	if _comment_autosave != null:
		ok = bool(_comment_autosave.flush()) and ok
	if _reply_target_failed:
		_set_reply_parent(_parent)
		ok = not _reply_target_failed and ok
	return ok


func loss_warnings() -> Array[String]:
	if _drafts == null or _scope.is_empty():
		return ["动态评论草稿"] if is_dirty() else []
	var warnings: Array[String] = []
	if _writing:
		warnings.append("评论或回复正在发送，退出后结果可能未确认")
	if not _draft.text.strip_edges().is_empty() and _comment_autosave != null and _comment_autosave.has_failure():
		warnings.append("评论草稿保存失败")
	if _reply_target_failed:
		warnings.append("回复对象保存失败")
	return warnings


func clear_drafts() -> void:
	_draft.clear()
	if _comment_autosave != null:
		_comment_autosave.clear()
	_set_reply_parent("")
	_reply_target_failed = false
	_sync_reply_chip()
	_sync_draft_height()


func _exit_tree() -> void:
	flush_drafts()


func _submit() -> void:
	if _writing or not _post.allow_comment: return
	_writing = true
	update_post(_post)
	_cancel.disabled = true
	var result: Dictionary = await _controller.comment(_post.id, _draft.text, _parent)
	_writing = false
	update_post(_post)
	_cancel.disabled = false
	if result.ok:
		_draft.clear()
		if _comment_autosave != null:
			_comment_autosave.clear()
		_set_reply_parent("")
		_sync_reply_chip()
		_sync_draft_height()
		_set_status("")
	else:
		_set_status("")
		ErrorDialog.present(self, _comment_error_text(str(result.code)))


func _comment_error_text(code: String) -> String:
	match code:
		"TIMEOUT", "NETWORK_ERROR":
			return "发送结果不确定，请先刷新核实；草稿已保留。"
		"INVALID_INPUT":
			return "评论内容不能为空。"
		"BUSY":
			return "正在发送，请稍候。"
		"COMMENT_NOT_ALLOWED":
			return "此动态不支持评论。"
		"INVALID_REPLY_TARGET":
			return "回复对象已不存在。"
		_:
			return "评论失败，草稿已保留。"


func _set_status(text: String) -> void:
	_status.text = text
	_status.visible = not text.is_empty()


func refresh_comments() -> void:
	await _controller.refresh_comments(_post.id)


func _at_bottom() -> void:
	if not is_visible_in_tree() or _applying_scroll or _pending_scroll >= 0: return
	var bar := _scroll.get_v_scroll_bar()
	var state: Dictionary = _controller.get_comments(_post.id)
	if bar.value + bar.page >= bar.max_value - 24 and state.loaded and state.has_more and not state.busy and state.code in ["", "OK"]:
		_controller.load_comments(_post.id, true)


static func relative_time(raw: String) -> String:
	if raw.length() != 19: return raw
	var pattern := RegEx.new()
	pattern.compile("^\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}$")
	if pattern.search(raw) == null: return raw
	if not _valid_calendar_time(raw): return raw
	var normalized := raw.replace(" ", "T")
	var epoch := Time.get_unix_time_from_datetime_string(normalized)
	if Time.get_datetime_string_from_unix_time(epoch) != normalized: return raw
	var age := int(Time.get_unix_time_from_system()) - (epoch - 8 * 3600)
	if age < 0: return raw
	if age < 60: return "刚刚"
	if age < 3600: return "%s分钟前" % (age / 60)
	if age < 86400: return "%s小时前" % (age / 3600)
	if age < 7 * 86400: return "%s天前" % (age / 86400)
	return raw.left(10)


func _update_comment_status(state: Dictionary) -> void:
	if state.code not in ["", "OK"]:
		_set_status("")
		if state.code != _last_comment_code:
			_last_comment_code = state.code
			ErrorDialog.present(self, "评论加载失败，已保留现有内容，可重试。")
	else:
		_last_comment_code = ""
		_set_status("")


static func _valid_calendar_time(raw: String) -> bool:
	var year := int(raw.substr(0, 4))
	var month := int(raw.substr(5, 2))
	var day := int(raw.substr(8, 2))
	if year < 1 or month < 1 or month > 12: return false
	var days := [31, _february_days(year), 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
	if day < 1 or day > days[month - 1] or int(raw.substr(11, 2)) > 23 or int(raw.substr(14, 2)) > 59 or int(raw.substr(17, 2)) > 59: return false
	return true


static func _february_days(year: int) -> int:
	return 29 if year % 400 == 0 or (year % 4 == 0 and year % 100 != 0) else 28
