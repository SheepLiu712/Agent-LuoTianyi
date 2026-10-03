extends VBoxContainer
signal audio_action(action: String)
signal image_opened(texture: Texture2D)
signal image_action(action: String)
const USER_ICON := preload("res://assets/ui/user_icon.png")
const TIANYI_ICON := preload("res://assets/ui/tianyi_icon.png")
const AudioRow = preload("res://scenes/ui/message_audio.tscn")
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

func set_ui_style(style: RefCounted) -> void:
	if _ui_style != null and _ui_style.style_changed.is_connected(_apply_ui_style):
		_ui_style.style_changed.disconnect(_apply_ui_style)
	_ui_style = style
	_ui_style.style_changed.connect(_apply_ui_style)
	if is_node_ready(): _apply_ui_style()
	if _audio != null: _audio.set_ui_style(style)

func _apply_ui_style() -> void:
	if _ui_style != null and _time_style != null:
		_time_style.bg_color = Color(0.91, 0.95, 0.98, 0.72) if _ui_style.is_crystal() else Color(0.93, 0.95, 0.97, 1)
	if _ui_style == null or _styled_panel == null: return
	_ui_style.apply_bubble_style(_styled_panel)
	_styled_panel.bg_color = (Color(0.863, 0.949, 1, 0.74) if _own else Color(1, 1, 1, 0.75)) if _ui_style.is_crystal() else (Color(0.80, 0.92, 1.0, 1) if _own else Color(0.945, 0.969, 0.984, 1))

func _ready() -> void:
	_time_style = _time_panel.get_theme_stylebox("panel").duplicate() as StyleBoxFlat
	_time_panel.add_theme_stylebox_override("panel", _time_style)
	_other_style = _bubble.get_theme_stylebox("panel") as StyleBoxFlat
	_image_button.pressed.connect(func(): image_action.emit("retry" if _image_status == "error" else "preview"))
	_history_picture.gui_input.connect(func(event):
		if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
			image_action.emit("preview"))
	_picture.gui_input.connect(func(event):
		if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT and event.pressed:
			image_opened.emit(_picture.texture))
	resized.connect(_queue_layout)
	_text.theme_changed.connect(_queue_layout)
	_bubble.theme_changed.connect(_queue_layout)
	_column.minimum_size_changed.connect(_sync_height)
	_queue_layout()

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
	_avatar.texture = USER_ICON if _own else TIANYI_ICON
	if _own:
		_row.move_child(_avatar,_row.get_child_count()-1)
		_bubble.add_theme_stylebox_override("panel",own_style)
	_styled_panel = (own_style if _own else _other_style).duplicate() as StyleBoxFlat
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
		var factor := minf(1, maxf(1,maximum-padding) / _original_size.x)
		var preview_size := Vector2(_original_size) * factor
		_history_picture.custom_minimum_size = preview_size
		_picture.custom_minimum_size = preview_size
		width = minf(maximum,maxf(width,preview_size.x+padding))
	_text.visible = not _text.text.is_empty()
	_bubble.visible = _text.visible or has_picture
	_bubble.size_flags_horizontal = Control.SIZE_SHRINK_END if _own else Control.SIZE_SHRINK_BEGIN
	_bubble.custom_minimum_size.x = width
	_sync_height()

func _queue_layout() -> void:
	if not is_node_ready() or _layout_pending: return
	_layout_pending = true
	_resize_bubble.call_deferred()

func _sync_height() -> void:
	# The wrapper contributes height, not its descendants' minimum width. This
	# lets a previously wide message shrink when the history viewport narrows.
	_body.custom_minimum_size.y = _column.get_combined_minimum_size().y
	_column.offset_bottom = _body.custom_minimum_size.y

func update_message(message: Dictionary) -> void:
	if not _system_message and _text.text != message.text:
		_text.text = message.text
		_queue_layout()
	if _own:
		_caption.text = {"failed":"发送失败", "uncertain":"无法确认送达，请勿重复发送"}.get(message.status, "")
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
	_image_status = state.status
	_history_picture.texture = state.texture
	_original_size = state.get("original_size",Vector2i.ZERO)
	if _original_size == Vector2i.ZERO and state.texture != null:
		_original_size = Vector2i(state.texture.get_size())
	_history_picture.visible = state.status == "ready"
	_image_button.visible = state.status != "ready"
	_image_button.disabled = state.status in ["idle","loading"]
	_image_button.text = {"idle":"加载图片…","loading":"正在下载图片…","ready":"打开原图","error":"图片加载失败 · 重试"}.get(state.status,"")
	if state.code == "CACHE_WRITE_FAILED":
		_image_button.text += " · 未能缓存"
	_queue_layout()
