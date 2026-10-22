extends VBoxContainer
## One comment of a dynamic: the static look lives in the scene, setup() injects the row.
@onready var _avatar: TextureRect = %Avatar
@onready var _author: Label = %Author
@onready var _body: RichTextLabel = %Body
@onready var _time: Label = %Time
@onready var _reply: Button = %Reply
var _configured := false
var _avatar_path := ""
var _author_name := ""
var _body_text := ""
var _time_text := ""
var _tooltip := ""
var _allow_comment := false
var _reply_action := Callable()

func setup(avatar_path: String,author: String,body: String,time_text: String,created_at: String,allow_comment: bool,reply_action: Callable) -> void:
	_avatar_path = avatar_path
	_author_name = author
	_body_text = body
	_time_text = time_text
	_tooltip = created_at
	_allow_comment = allow_comment
	_reply_action = reply_action
	_configured = true
	if is_node_ready(): _apply()

func _ready() -> void:
	if not _configured: return
	_apply()

func _apply() -> void:
	_avatar.texture = load(_avatar_path)
	_author.text = _author_name
	_body.text = _body_text
	_time.text = _time_text
	_time.tooltip_text = _tooltip
	_reply.disabled = not _allow_comment
	if _reply_action.is_valid(): _reply.pressed.connect(_reply_action)
