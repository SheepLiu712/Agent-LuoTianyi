extends VBoxContainer
signal audio_action(action: String)
signal image_opened(texture: Texture2D)
signal image_action(action: String)
const USER_ICON := preload("res://assets/ui/user_icon.png")
const TIANYI_ICON := preload("res://assets/ui/tianyi_icon.png")
const AudioRow = preload("res://scenes/ui/chat/message_audio.tscn")
const ErrorDialog = preload("res://src/ui/error_dialog.gd")
const IMAGE_PREVIEW_MAX := 250.0
## 送达结果不确定的消息不呈现任何气泡；列表层已先过滤，这里是兜底。
const HIDDEN_STATUSES: Array[String] = ["uncertain", "superseded"]
@export var own_style: StyleBoxFlat
@onready var _row: HBoxContainer = %Row
@onready var _time_marker: CenterContainer = %TimeMarker
@onready var _time_panel: PanelContainer = %TimePanel
@onready var _time_text: Label = %TimeText
@onready var _system_label: Label = %System
@onready var _avatar: TextureRect = %Avatar
@onready var _body: Control = %Body
@onready var _column: VBoxContainer = %MessageColumn
@onready var _bubble: PanelContainer = %Bubble
@onready var _text: RichTextLabel = %Text
@onready var _history_picture: TextureRect = %HistoryPicture
@onready var _image_button: Button = %ImageButton
@onready var _picture: TextureRect = %Picture
@onready var _caption: Label = %Caption
var _audio
var _own := false
var _system_message := false
var _is_image := false
var _image_status := "idle"
var _layout_pending := false
var _original_size := Vector2i.ZERO
var _ui_style: RefCounted
var _other_style: StyleBoxFlat
var _styled_panel: StyleBoxFlat
var _time_style: StyleBoxFlat
var _user_avatar: Texture2D

## 自定义头像只影响自己的气泡；没有上传时仍回落到占位图。
func set_user_avatar(texture: Texture2D) -> void:
	_user_avatar = texture
	if is_node_ready() and _own:
		_avatar.texture = _avatar_texture()

func _avatar_texture() -> Texture2D:
	if not _own:
		return TIANYI_ICON
	return _user_avatar if _user_avatar != null else USER_ICON

func set_ui_style(style: RefCounted) -> void:
	if _ui_style != null and _ui_style.style_changed.is_connected(_apply_ui_style):
		_ui_style.style_changed.disconnect(_apply_ui_style)
	_ui_style = style
	_ui_style.style_changed.connect(_apply_ui_style)
	if is_node_ready(): _apply_ui_style()
	if _audio != null: _audio.set_ui_style(style)

func _apply_ui_style() -> void:
	if _ui_style != null and _time_style != null:
		_time_style.bg_color = _ui_style.time_chip_color(_chip_base_color())
	if _ui_style == null or _styled_panel == null: return
	_ui_style.apply_bubble_style(_styled_panel)
	_styled_panel.bg_color = _ui_style.bubble_color(_own, _bubble_base_color())

## 扁平模式的底色来自共享主题，脚本只负责清透模式的替换。
func _bubble_base_color() -> Color:
	var style := _own_panel_style() if _own else _other_style
	return style.bg_color if style != null else Color.WHITE

func _chip_base_color() -> Color:
	var style := get_theme_stylebox("panel", "MessageTimeChip") as StyleBoxFlat
	return style.bg_color if style != null else Color.WHITE

func _ready() -> void:
	_time_style = _time_panel.get_theme_stylebox("panel").duplicate() as StyleBoxFlat
	_time_panel.add_theme_stylebox_override("panel", _time_style)
	_other_style = _bubble.get_theme_stylebox("panel") as StyleBoxFlat
	_image_button.pressed.connect(func(): image_action.emit("retry" if _image_status == "error" else "preview"))
	# 两个图片入口都用同一套激活信号：鼠标点击与键盘 Enter/Space 行为一致。
	_history_picture.activated.connect(func(): image_action.emit("preview"))
	_picture.activated.connect(func():
		if _picture.texture != null: image_opened.emit(_picture.texture))
	resized.connect(_queue_layout)
	_text.theme_changed.connect(_queue_layout)
	_bubble.theme_changed.connect(_queue_layout)
	_column.minimum_size_changed.connect(_sync_height)
	_queue_layout()

## 场景不再自带一份气泡底板：共享主题是唯一来源，本导出只在确有局部覆盖时生效。
func _own_panel_style() -> StyleBoxFlat:
	if own_style != null:
		return own_style
	return get_theme_stylebox("panel", "MessageBubbleOwn") as StyleBoxFlat

func configure(message: Dictionary, image_texture: Texture2D = null) -> void:
	_system_message = message.role == "system"
	if _system_message:
		_avatar.hide()
		_body.hide()
		_system_label.text = message.text
		_system_label.show()
		return
	_own = message.role == "user"
	_is_image = message.get("type") == "image"
	_row.alignment = BoxContainer.ALIGNMENT_END if _own else BoxContainer.ALIGNMENT_BEGIN
	_avatar.texture = _avatar_texture()
	if _own:
		_row.move_child(_avatar,_row.get_child_count()-1)
	_styled_panel = (_own_panel_style() if _own else _other_style).duplicate() as StyleBoxFlat
	_bubble.add_theme_stylebox_override("panel", _styled_panel)
	_apply_ui_style()
	if _is_image:
		_history_picture.show()
		_image_button.show()
		%Content.move_child(_text, %Content.get_child_count() - 1)
		_text.add_theme_font_size_override("normal_font_size", 12)
	if image_texture != null:
		_picture.texture = image_texture
		_original_size = Vector2i(image_texture.get_size())
		_picture.show()
	update_message(message)

func _resize_bubble() -> void:
	_layout_pending = false
	if _system_message: return
	var maximum := maxf(1, minf(size.x * .9, size.x - _avatar.get_combined_minimum_size().x - _row.get_theme_constant("separation")))
	var padding := _bubble.get_theme_stylebox("panel").get_minimum_size().x
	var font := _text.get_theme_font("normal_font")
	var font_size := _text.get_theme_font_size("normal_font_size")
	var natural := font.get_multiline_string_size(_text.text, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size).x
	var has_picture := _is_image or _picture.visible
	var width := minf(maximum, ceilf(natural + padding))
	if has_picture and _original_size.x > 0 and _original_size.y > 0:
		var preview_size := _fixed_preview_size()
		var available := maxf(1.0, maximum - padding)
		if preview_size.x > available:
			preview_size *= available / preview_size.x
		_apply_preview_size(preview_size)
		width = minf(maximum,maxf(width,preview_size.x+padding))
	_text.visible = not _text.text.is_empty()
	_bubble.visible = _text.visible or has_picture
	_bubble.size_flags_horizontal = Control.SIZE_SHRINK_END if _own else Control.SIZE_SHRINK_BEGIN
	_bubble.custom_minimum_size.x = width
	_sync_height()

## 缩略图尺寸只由原图决定：严格限制在 250×250 内，小图保持原像素且永不放大。
func _fixed_preview_size() -> Vector2:
	if _original_size.x <= 0 or _original_size.y <= 0:
		return Vector2.ZERO
	var scale := minf(1.0, minf(
		IMAGE_PREVIEW_MAX / float(_original_size.x),
		IMAGE_PREVIEW_MAX / float(_original_size.y)))
	return Vector2(_original_size) * scale

func _apply_preview_size(value: Vector2) -> void:
	_history_picture.custom_minimum_size = value
	_picture.custom_minimum_size = value

func _queue_layout() -> void:
	if not is_node_ready() or _layout_pending: return
	_layout_pending = true
	_resize_bubble.call_deferred()

func _sync_height() -> void:
	# 外层只贡献高度，不继承子节点最小宽度，长消息才能在窄视口里收缩。
	_body.custom_minimum_size.y = _column.get_combined_minimum_size().y
	_column.offset_bottom = _body.custom_minimum_size.y

func update_message(message: Dictionary) -> void:
	# 送达结果不确定：整条气泡都不出现，连占位和上一状态的字样都不留。
	visible = not HIDDEN_STATUSES.has(str(message.get("status", "")))
	if not visible:
		_caption.text = ""
		_caption.hide()
		return
	if not _system_message and _text.text != message.text:
		_text.text = message.text
		_queue_layout()
	if _own:
		_caption.text = ""
		_caption.visible = not _caption.text.is_empty()
		_caption.add_theme_color_override("font_color", get_theme_color("delivery_failed", "MessageBubble"))

func set_time_marker(text: String) -> void:
	_time_text.text = text
	_time_marker.visible = not text.is_empty()

func set_audio_state(state: Dictionary) -> void:
	if _system_message:
		return
	if _audio == null and (state.available or not state.code.is_empty()):
		_audio = AudioRow.instantiate()
		if _ui_style != null: _audio.set_ui_style(_ui_style)
		_column.add_child(_audio)
		_audio.action.connect(func(value): audio_action.emit(value))
	if _audio != null:
		_audio.update_state(state)

func set_image_state(state: Dictionary) -> void:
	if not _is_image:
		return
	var next_size := _resolved_original_size(state)
	if _image_state_unchanged(state,next_size):
		return
	_apply_image_state(state,next_size)

func _resolved_original_size(state: Dictionary) -> Vector2i:
	var size: Vector2i = state.get("original_size",Vector2i.ZERO)
	if size == Vector2i.ZERO and state.texture != null:
		size = Vector2i(state.texture.get_size())
	return size

## 可见集合每次变化都会重放同一状态；没有实际变化时不再触发一次重排。
func _image_state_unchanged(state: Dictionary, next_size: Vector2i) -> bool:
	return _image_status == state.status and _history_picture.texture == state.texture and _original_size == next_size

func _apply_image_state(state: Dictionary, next_size: Vector2i) -> void:
	var previous_status := _image_status
	_image_status = state.status
	_history_picture.texture = state.texture
	_original_size = next_size
	_history_picture.visible = state.status == "ready"
	_image_button.visible = state.status != "ready"
	_image_button.disabled = state.status in ["idle","loading"]
	_image_button.text = {"idle":"加载图片…","loading":"正在下载图片…","ready":"打开原图","error":"重试"}.get(state.status,"")
	if state.status == "error" and previous_status != "error":
		ErrorDialog.present(self, "图片未加载，点击重试。")
	if state.status == "ready":
		var preview_size := _fixed_preview_size()
		if preview_size != Vector2.ZERO:
			_apply_preview_size(preview_size)
	_queue_layout()
