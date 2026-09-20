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
@onready var _load: Button = %LoadMore
var _controller: Node
var _post: Dictionary
var _parent := ""
var _rows := {}
var _writing := false
var _refresh_failed := false
var _initialized := false

func setup(controller: Node,post: Dictionary) -> void:
	_controller = controller
	_post = post.duplicate(true)
	if is_node_ready(): _initialize()

func _ready() -> void:
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
	_load.pressed.connect(func():
		if _refresh_failed:
			_refresh_failed = false
			await refresh_comments()
		else:
			var state: Dictionary = _controller.get_comments(_post.id)
			await _controller.load_comments(_post.id,state.loaded and state.has_more))
	get_v_scroll_bar().value_changed.connect(func(_value): _at_bottom())
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

func update_comments() -> void:
	if not is_node_ready(): return
	var state: Dictionary = _controller.get_comments(_post.id)
	_load.visible = state.busy or state.has_more or not state.loaded or state.code not in ["","OK"]
	_load.disabled = state.busy
	_load.text = "加载中…" if state.busy else ("加载更多评论" if state.loaded else "加载评论")
	if state.code not in ["","OK"]:
		_load.text = "重试评论"
		_status.text = "评论加载失败（%s），已保留现有内容。"%state.code
	elif _status.text.begins_with("评论加载失败"):
		_status.text = ""
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
		_status.text = "评论已发送。"
	else:
		_status.text = "发送结果不确定，请先刷新核实；草稿已保留。" if result.code in ["TIMEOUT","NETWORK_ERROR"] else "评论失败，草稿已保留（%s）。"%result.code

func refresh_comments() -> void:
	await _controller.refresh_comments(_post.id)
	_refresh_failed = _controller.get_comments(_post.id).code not in ["","OK"]

func _at_bottom() -> void:
	if not is_visible_in_tree(): return
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
	var year := int(raw.substr(0,4))
	var month := int(raw.substr(5,2))
	var day := int(raw.substr(8,2))
	if year < 1 or month < 1 or month > 12: return raw
	var days := [31,29 if year%400==0 or (year%4==0 and year%100!=0) else 28,31,30,31,30,31,31,30,31,30,31]
	if day < 1 or day > days[month-1] or int(raw.substr(11,2)) > 23 or int(raw.substr(14,2)) > 59 or int(raw.substr(17,2)) > 59: return raw
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
