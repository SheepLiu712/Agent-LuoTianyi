extends Button
## 动态列表卡片：左侧未读色条、两行正文预览与底部评论数。
const UiMotion = preload("res://src/ui/ui_motion.gd")

@onready var _avatar: TextureRect = %Avatar
@onready var _author: Label = %Author
@onready var _time: Label = %Time
@onready var _excerpt: Label = %Excerpt
@onready var _comment_count: Label = %CommentCount
@onready var _unread_bar: Panel = %UnreadBar
var _post: Dictionary = {}
var _avatar_texture: Texture2D
var _unread := false
var _comments := 0


func setup(post: Dictionary, avatar_texture: Texture2D) -> void:
	_post = post
	_avatar_texture = avatar_texture
	_comments = int(post.get("comment_count", _comments))
	if is_node_ready(): _apply()


func set_avatar(texture: Texture2D) -> void:
	if _avatar_texture == texture:
		return
	_avatar_texture = texture
	if is_node_ready(): _avatar.texture = _avatar_texture


func set_unread(unread: bool) -> void:
	if _unread == unread:
		return
	_unread = unread
	if is_node_ready():
		_sync_unread()


func set_comment_count(count: int) -> void:
	_comments = maxi(0, count)
	if is_node_ready():
		_comment_count.text = str(_comments)


func _ready() -> void:
	mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	UiMotion.bind_tactile_press(self)
	_excerpt.resized.connect(_sync_height)
	if _post.is_empty(): return
	_apply()


func _apply() -> void:
	_avatar.texture = _avatar_texture
	_author.text = str(_post.get("author_name", ""))
	_time.text = _short_time(str(_post.get("created_at", "")))
	_time.tooltip_text = str(_post.get("created_at", ""))
	_excerpt.text = str(_post.get("content", "")).replace("\n", " ")
	_comment_count.text = str(_comments)
	_sync_unread()
	_sync_height.call_deferred()


func _sync_unread() -> void:
	_unread_bar.visible = _unread
	_author.add_theme_color_override("font_color", Color("0e2a3b") if _unread else Color("3f5563"))


func _sync_height() -> void:
	var margin := get_node_or_null("Margin") as Control
	if margin != null:
		custom_minimum_size.y = maxf(76.0, margin.get_combined_minimum_size().y)


static func _short_time(raw: String) -> String:
	if raw.length() >= 16:
		return raw.substr(5, 5)
	return raw
