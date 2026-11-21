extends VBoxContainer
## 动态的一条评论：节点由 dynamic_comment_row.tscn 定义，脚本负责数据填充。

@onready var _avatar: TextureRect = %Avatar
@onready var _author: Label = %Author
@onready var _body: RichTextLabel = %Body
@onready var _time: Label = %Time
@onready var _reply: Button = %Reply
var _configured := false
var _avatar_texture: Texture2D
var _author_name := ""
var _body_text := ""
var _time_text := ""
var _tooltip := ""
var _allow_comment := false
var _reply_action := Callable()


func setup(avatar_texture: Texture2D, author: String, body: String, time_text: String, created_at: String, allow_comment: bool, reply_action: Callable) -> void:
	_avatar_texture = avatar_texture
	_author_name = author
	_body_text = body
	_time_text = time_text
	_tooltip = created_at
	_allow_comment = allow_comment
	_reply_action = reply_action
	_configured = true
	if is_node_ready(): _apply()


func set_avatar(texture: Texture2D) -> void:
	if _avatar_texture == texture:
		return
	_avatar_texture = texture
	if is_node_ready(): _avatar.texture = _avatar_texture


func _ready() -> void:
	if not _configured: return
	_apply()


func _apply() -> void:
	_avatar.texture = _avatar_texture
	_author.text = _author_name
	_body.text = _body_text
	_time.text = _time_text
	_time.tooltip_text = _tooltip
	_reply.disabled = not _allow_comment
	if _reply_action.is_valid(): _reply.pressed.connect(_reply_action)
