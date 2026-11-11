extends Control
## 头像改动立即落盘，所以这一页不参与「保存全部修改」，也不会让窗口变脏。
const DEFAULT_ICON := preload("res://assets/ui/tianyi_icon.png")
const ErrorDialog = preload("res://src/ui/error_dialog.gd")
const OK_TEXT := "头像已更新。"
const RESET_TEXT := "已恢复天依头像。"
const ERROR_TEXT := {
	"NO_ACCOUNT": "登录后才能设置头像。",
	"IMAGE_READ_FAILED": "这张图片读不出来，换一张试试。",
	"IMAGE_TOO_LARGE": "图片超过 6 MB，请换一张小一点的。",
	"IMAGE_FORMAT": "只支持 PNG、JPG、WebP 格式的图片。",
	"AVATAR_WRITE_FAILED": "头像保存失败，请重试。",
}
var _source: Node
@onready var _preview: TextureRect = %Preview
@onready var _account: Label = %Account
@onready var _pick: Button = %PickButton
@onready var _reset: Button = %ResetButton
@onready var _result: Label = %Result
@onready var _dialog: FileDialog = %FileDialog

## 头像源由装配层给出；换账号时它会推新纹理进来，这里只负责跟着画。
func set_avatar_source(source: Node) -> void:
	if _source != null and _source.avatar_changed.is_connected(_sync):
		_source.avatar_changed.disconnect(_sync)
	_source = source
	if source == null:
		if is_node_ready(): _sync(null)
		return
	source.avatar_changed.connect(_sync)
	if is_node_ready(): _sync(source.get_texture())

func _ready() -> void:
	_pick.pressed.connect(func(): _dialog.popup_centered_ratio(.6))
	_reset.pressed.connect(_reset_avatar)
	_dialog.file_selected.connect(_apply_path)
	_dialog.canceled.connect(_dialog.hide)
	_sync(_source.get_texture() if _source != null else null)

func _sync(texture: Texture2D) -> void:
	_preview.texture = texture if texture != null else DEFAULT_ICON
	var username: String = _source.get_username() if _source != null else ""
	_account.text = username if not username.is_empty() else "—"
	var enabled := _source != null and not username.is_empty()
	_pick.disabled = not enabled
	_reset.disabled = not enabled or texture == null

func _apply_path(path: String) -> void:
	_finish(_source.apply_file(path), OK_TEXT)

func _reset_avatar() -> void:
	_finish(_source.reset(), RESET_TEXT)

## 失败按码查文案，成功走各自的提示：两种结果都不会打断页面里其他操作。
func _finish(result: Dictionary, ok_text: String) -> void:
	var code := str(result.get("code", ""))
	var ok := bool(result.get("ok", false))
	if ok:
		_show(ok_text, true)
	else:
		_result.text = ""
		ErrorDialog.present(self, ERROR_TEXT.get(code, "头像设置失败，请重试。"))

func _show(text: String, ok: bool) -> void:
	_result.text = text
	_result.visible = not text.is_empty()
	_result.add_theme_color_override("font_color", Color(.42, .5, .56) if ok else Color(.78, .29, .29))
