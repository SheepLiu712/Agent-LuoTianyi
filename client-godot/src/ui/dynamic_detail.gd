extends ScrollContainer
const CommentRow = preload("res://scenes/ui/dynamic_comment_row.tscn")
@onready var _column: VBoxContainer = %Column
@onready var _avatar: TextureRect = %Avatar
@onready var _author: Label = %Author
@onready var _created_at: Label = %CreatedAt
@onready var _body: RichTextLabel = %Body
@onready var _notice: Label = %Notice
@onready var _draft: TextEdit = %CommentDraft
@onready var _send: Button = %Send
@onready var _comments: VBoxContainer = %Comments
@onready var _reply_box: VBoxContainer = %ReplyBox
@onready var _reply_label: Label = %ReplyLabel
@onready var _reply_draft: TextEdit = %ReplyDraft
@onready var _cancel: Button = %CancelReply
@onready var _reply_send: Button = %ReplySend
@onready var _status: Label = %Status
var _controller: Node
var _post: Dictionary
var _parent := ""
var _rows := {}
var _writing := false
var _initialized := false
var _ui_style: RefCounted
var _draft_style: StyleBoxFlat
var _reply_style: StyleBoxFlat
var _pending_scroll := -1
var _restore_frames := 0
var _applying_scroll := false

func set_ui_style(style: RefCounted) -> void:
	if _ui_style != null and _ui_style.style_changed.is_connected(_apply_ui_style):
		_ui_style.style_changed.disconnect(_apply_ui_style)
	_ui_style = style
	style.apply_view(self, {"Send":"action_send", "ReplySend":"action_send", "CancelReply":"action_close"})
	_ui_style.style_changed.connect(_apply_ui_style)
	if is_node_ready(): _apply_ui_style()

func _apply_ui_style() -> void:
	if _ui_style == null or not is_node_ready(): return
	if _draft_style == null:
		_draft_style = _draft.get_theme_stylebox('normal').duplicate() as StyleBoxFlat
	if _reply_style == null:
		_reply_style = _reply_draft.get_theme_stylebox('normal').duplicate() as StyleBoxFlat
	_ui_style.apply_input_style(_draft_style)
	_ui_style.apply_input_style(_reply_style)
	_draft.add_theme_stylebox_override('normal', _draft_style)
	_reply_draft.add_theme_stylebox_override('normal', _reply_style)

func setup(controller: Node,post: Dictionary) -> void:
	_controller = controller
	_post = post.duplicate(true)
	if is_node_ready(): _initialize()

func _ready() -> void:
	set_process(false)
	if _controller == null: return
	_initialize()

func _initialize() -> void:
	if _initialized: return
	_initialized = true
	_avatar.texture = load(avatar_path(_post))
	_author.text = _post.author_name
	_created_at.text = _post.created_at
	_send.pressed.connect(func(): _submit(false))
	_cancel.pressed.connect(func():
		_parent = ""
		_place_reply())
	_reply_send.pressed.connect(func(): _submit(true))
	get_v_scroll_bar().value_changed.connect(func(_value): _at_bottom())
	get_v_scroll_bar().gui_input.connect(_scroll_input)
	_column.resized.connect(_queue_restore)
	_controller.changed.connect(update_comments)
	update_post(_post)
	update_comments()

func update_post(post: Dictionary) -> void:
	_post = post.duplicate(true)
	if _body.text != _post.content: _body.text = _post.content
	_notice.visible = not _post.allow_comment
	_draft.editable = _post.allow_comment and not _writing
	_reply_draft.editable = _draft.editable
	_send.disabled = not _draft.editable
	_reply_send.disabled = _send.disabled

func is_dirty() -> bool:
	return _writing or not _draft.text.is_empty() or not _reply_draft.text.is_empty()

func get_reading_position() -> int:
	return _pending_scroll if _pending_scroll >= 0 else scroll_vertical

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
	var bar := get_v_scroll_bar()
	_applying_scroll = true
	scroll_vertical = clampi(_pending_scroll, 0, maxi(0, int(bar.max_value - bar.page)))
	_applying_scroll = false
	_pending_scroll = -1
	set_process(false)

func _gui_input(event: InputEvent) -> void:
	_scroll_input(event)

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
	return event.button_index == MOUSE_BUTTON_LEFT and get_v_scroll_bar().get_global_rect().has_point(event.global_position)

func update_comments() -> void:
	if not is_node_ready(): return
	var scroll_bar := get_v_scroll_bar()
	var previous_scroll := scroll_bar.value
	var state: Dictionary = _controller.get_comments(_post.id)
	_update_comment_status(state)
	var names := {}
	for item in state.items: names[item.id] = item.author_name
	for index in state.items.size():
		var item: Dictionary = state.items[index]
		if not _rows.has(item.id):
			var row = CommentRow.instantiate()
			var target: String = str(item.get("parent_comment_id","") if item.get("parent_comment_id") != null else "")
			row.setup(avatar_path(item),item.author_name,("回复 %s："%names.get(target,"较早评论") if not target.is_empty() else "")+item.content,relative_time(item.created_at),item.created_at,_post.allow_comment,func():
				if _writing: return
				_parent = item.id
				_reply_label.text = "回复 "+item.author_name
				_place_reply()
				_reply_draft.grab_focus())
			_comments.add_child(row)
			_rows[item.id] = row
		_comments.move_child(_rows[item.id],index)
	if _pending_scroll >= 0:
		_queue_restore()
	elif previous_scroll > 0:
		restore_reading_position(int(previous_scroll))
func _place_reply() -> void:
	var destination: Node = _column if _parent.is_empty() else _rows.get(_parent,_column)
	if _reply_box.get_parent() != destination: _reply_box.reparent(destination)
	if _parent.is_empty():
		_column.move_child(_reply_box,_comments.get_index())
		_reply_label.text = "已取消回复对象，文字保留为留言草稿"
	_cancel.visible = not _parent.is_empty()
	_reply_send.text = "发送评论" if _parent.is_empty() else "发送回复"
	_reply_box.visible = not _parent.is_empty() or not _reply_draft.text.is_empty()

func _submit(reply: bool) -> void:
	if _writing or not _post.allow_comment: return
	var input := _reply_draft if reply else _draft
	_writing = true
	update_post(_post)
	_cancel.disabled = true
	var result: Dictionary = await _controller.comment(_post.id,input.text,_parent if reply else "")
	_writing = false
	update_post(_post)
	_cancel.disabled = false
	if result.ok:
		input.clear()
		if reply:
			_parent = ""
			_place_reply()
		_set_status("")
	else:
		_set_status("发送结果不确定，请先刷新核实；草稿已保留。" if result.code in ["TIMEOUT","NETWORK_ERROR"] else "评论失败，草稿已保留（%s）。"%result.code)

func _set_status(text: String) -> void:
	_status.text = text
	_status.visible = not text.is_empty()

func refresh_comments() -> void:
	await _controller.refresh_comments(_post.id)

func _at_bottom() -> void:
	if not is_visible_in_tree() or _applying_scroll or _pending_scroll >= 0: return
	var bar := get_v_scroll_bar()
	var state: Dictionary = _controller.get_comments(_post.id)
	if bar.value+bar.page >= bar.max_value-24 and state.loaded and state.has_more and not state.busy and state.code in ["","OK"]:
		_controller.load_comments(_post.id,true)

static func avatar_path(item: Dictionary) -> String:
	return "res://assets/ui/tianyi_icon.png" if item.author_type == "agent" else "res://assets/ui/user_icon.png"

static func relative_time(raw: String) -> String:
	if raw.length() != 19: return raw
	var pattern := RegEx.new()
	pattern.compile("^\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}$")
	if pattern.search(raw) == null: return raw
	if not _valid_calendar_time(raw): return raw
	var normalized := raw.replace(" ","T")
	var epoch := Time.get_unix_time_from_datetime_string(normalized)
	if Time.get_datetime_string_from_unix_time(epoch) != normalized: return raw
	var age := int(Time.get_unix_time_from_system())-(epoch-8*3600)
	if age < 0: return raw
	if age < 60: return "刚刚"
	if age < 3600: return "%s分钟前"%(age/60)
	if age < 86400: return "%s小时前"%(age/3600)
	if age < 7*86400: return "%s天前"%(age/86400)
	return raw.left(10)
func _update_comment_status(state: Dictionary) -> void:
	if state.code not in ["","OK"]:
		_set_status("评论加载失败（%s），已保留现有内容；点击动态卡片重试。"%state.code)
	elif _status.text.begins_with("评论加载失败"):
		_set_status("")

static func _valid_calendar_time(raw: String) -> bool:
	var year := int(raw.substr(0,4))
	var month := int(raw.substr(5,2))
	var day := int(raw.substr(8,2))
	if year < 1 or month < 1 or month > 12: return false
	var days := [31,_february_days(year),31,30,31,30,31,31,30,31,30,31]
	if day < 1 or day > days[month-1] or int(raw.substr(11,2)) > 23 or int(raw.substr(14,2)) > 59 or int(raw.substr(17,2)) > 59: return false
	return true

static func _february_days(year: int) -> int:
	return 29 if year%400==0 or (year%4==0 and year%100!=0) else 28
