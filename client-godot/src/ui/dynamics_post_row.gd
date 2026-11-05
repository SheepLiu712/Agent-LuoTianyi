extends Button
## One row of the dynamics feed: the static look lives in the scene, setup() injects the row.
const TYPES := {"citywalk":"城市漫步","diary":"天依日记","song_learned":"学会新歌","system_notice":"系统通知","user_post":"生活动态"}
@onready var _avatar: TextureRect = %Avatar
@onready var _author: Label = %Author
@onready var _meta: Label = %Meta
@onready var _excerpt: Label = %Excerpt
var _post: Dictionary = {}
var _avatar_path := ""

func setup(post: Dictionary,avatar_path: String) -> void:
	_post = post
	_avatar_path = avatar_path
	if is_node_ready(): _apply()

func _ready() -> void:
	if _post.is_empty(): return
	_apply()

func _apply() -> void:
	_avatar.texture = load(_avatar_path)
	_author.text = _post.author_name
	_meta.text = TYPES.get(_post.get("source_type",""),"动态")+" · "+_post.created_at
	_excerpt.text = _post.content.replace("\n"," ")
