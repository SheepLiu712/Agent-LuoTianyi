extends Button
## 动态列表的一行：静态外观在场景里，setup() 只注入数据。
const TYPES := {"citywalk":"城市漫步","diary":"天依日记","song_learned":"学会新歌","system_notice":"系统通知","user_post":"生活动态"}
@onready var _avatar: TextureRect = %Avatar
@onready var _author: Label = %Author
@onready var _meta: Label = %Meta
@onready var _excerpt: Label = %Excerpt
@onready var _dot: Panel = %UnreadDot
var _post: Dictionary = {}
var _avatar_texture: Texture2D
var _unread := false

func setup(post: Dictionary,avatar_texture: Texture2D) -> void:
	_post = post
	_avatar_texture = avatar_texture
	if is_node_ready(): _apply()

func set_avatar(texture: Texture2D) -> void:
	if _avatar_texture == texture:
		return
	_avatar_texture = texture
	if is_node_ready(): _avatar.texture = _avatar_texture

## 未读只用一个小圆点表示，不抢内容的排版位置。
func set_unread(unread: bool) -> void:
	if _unread == unread:
		return
	_unread = unread
	if is_node_ready(): _dot.visible = _unread

func _ready() -> void:
	if _post.is_empty(): return
	_apply()

func _apply() -> void:
	_avatar.texture = _avatar_texture
	_author.text = _post.author_name
	_meta.text = TYPES.get(_post.get("source_type",""),"动态")+" · "+_post.created_at
	_excerpt.text = _post.content.replace("\n"," ")
	_dot.visible = _unread
