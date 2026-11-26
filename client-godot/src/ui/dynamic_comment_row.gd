extends PanelContainer
## 动态的一条评论：头像、作者（含作者徽标）、时间、正文与右侧回复入口。

@onready var _avatar: TextureRect = %Avatar
@onready var _author: Label = %Author
@onready var _author_badge: PanelContainer = %AuthorBadge
@onready var _body: RichTextLabel = %Body
@onready var _time: Label = %Time
@onready var _reply: Button = %Reply
var _configured := false
var _avatar_texture: Texture2D
var _author_name := ""
var _body_text := ""
var _reply_to_name := ""
var _time_text := ""
var _tooltip := ""
var _allow_comment := false
var _is_post_author := false
var _reply_action := Callable()
var _normal_style: StyleBox
var _highlight_style: StyleBoxFlat


func setup(
	avatar_texture: Texture2D,
	author: String,
	body: String,
	time_text: String,
	created_at: String,
	allow_comment: bool,
	reply_action: Callable,
	is_post_author: bool = false,
	reply_to_name: String = ""
) -> void:
	_avatar_texture = avatar_texture
	_author_name = author
	_body_text = body
	_time_text = time_text
	_tooltip = created_at
	_allow_comment = allow_comment
	_reply_action = reply_action
	_is_post_author = is_post_author
	_reply_to_name = reply_to_name
	_configured = true
	if is_node_ready(): _apply()


func set_avatar(texture: Texture2D) -> void:
	if _avatar_texture == texture:
		return
	_avatar_texture = texture
	if is_node_ready(): _avatar.texture = _avatar_texture


func set_highlighted(active: bool) -> void:
	if not is_node_ready():
		return
	add_theme_stylebox_override("panel", _highlight_style if active else _normal_style)


func _ready() -> void:
	_normal_style = get_theme_stylebox("panel")
	_highlight_style = StyleBoxFlat.new()
	_highlight_style.bg_color = Color("eef7fe")
	_highlight_style.set_corner_radius_all(6)
	_highlight_style.content_margin_left = 10.0
	_highlight_style.content_margin_top = 10.0
	_highlight_style.content_margin_right = 10.0
	_highlight_style.content_margin_bottom = 10.0
	_reply.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	if not _configured: return
	_apply()


func _apply() -> void:
	_avatar.texture = _avatar_texture
	_author.text = _author_name
	_author_badge.visible = _is_post_author
	if _reply_to_name.is_empty():
		_body.text = _escape_bbcode(_body_text)
	else:
		_body.text = "[color=#1278ad]@%s[/color] %s" % [_escape_bbcode(_reply_to_name), _escape_bbcode(_body_text)]
	_time.text = _time_text
	_time.tooltip_text = _tooltip
	_reply.disabled = not _allow_comment
	_reply.visible = _allow_comment
	if _reply_action.is_valid() and not _reply.pressed.is_connected(_reply_action):
		_reply.pressed.connect(_reply_action)


static func _escape_bbcode(raw: String) -> String:
	return raw.replace("[", "[lb]")
