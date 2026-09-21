extends HBoxContainer
signal audio_action(action: String)
signal image_opened(texture: Texture2D)
signal image_action(action: String)
const USER_ICON := preload("res://assets/ui/user_icon.png")
const TIANYI_ICON := preload("res://assets/ui/tianyi_icon.png")
const AudioRow = preload("res://scenes/ui/message_audio.tscn")
@export var own_style: StyleBoxFlat
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

func _ready() -> void:
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
	alignment = BoxContainer.ALIGNMENT_END if _own else BoxContainer.ALIGNMENT_BEGIN
	_avatar.texture = USER_ICON if _own else TIANYI_ICON
	if _own:
		move_child(_avatar,get_child_count()-1)
		_bubble.add_theme_stylebox_override("panel",own_style)
		_caption.show()
	if _is_image:
		_history_picture.show()
		_image_button.show()
	if image_texture != null:
		_picture.texture = image_texture
		_picture.show()
	update_message(message)

func _resize_bubble() -> void:
	_layout_pending = false
	if _system_message: return
	var maximum := maxf(1, minf(size.x * .9, size.x - _avatar.get_combined_minimum_size().x - get_theme_constant("separation")))
	var padding := _bubble.get_theme_stylebox("panel").get_minimum_size().x
	var font := _text.get_theme_font("normal_font")
	var font_size := _text.get_theme_font_size("normal_font_size")
	var natural := font.get_multiline_string_size(_text.text, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size).x
	var has_picture := _is_image or _picture.visible
	var width := minf(maximum, ceilf(natural + padding))
	if has_picture: width = minf(maximum, maxf(140, size.x * .76))
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

func update_message(message: Dictionary) -> void:
	if not _system_message and _text.text != message.text:
		_text.text = message.text
		_queue_layout()
	if _own:
		_caption.text = {"waiting_history":"等待历史同步…", "queued":"等待发送…", "sent":"已发送", "sending":"发送中…", "failed":"发送失败", "uncertain":"无法确认送达，请勿重复发送"}.get(message.status, "")
		if message.get("demo", false):
			_caption.text += " · 演示"
		_caption.add_theme_color_override("font_color", get_theme_color("delivery_failed" if message.status in ["failed", "uncertain"] else "delivery_status", "MessageBubble"))

func set_audio_state(state: Dictionary) -> void:
	if _system_message:
		return
	if _audio == null and (state.available or not state.code.is_empty()):
		_audio = AudioRow.instantiate()
		_column.add_child(_audio)
		_audio.action.connect(func(value): audio_action.emit(value))
	if _audio != null:
		_audio.update_state(state)

func set_image_state(state: Dictionary) -> void:
	if not _is_image:
		return
	_image_status = state.status
	_history_picture.texture = state.texture
	_history_picture.visible = state.status == "ready"
	_image_button.disabled = state.status in ["idle","loading"]
	_image_button.text = {"idle":"加载图片…","loading":"正在下载图片…","ready":"打开原图","error":"图片加载失败 · 重试"}.get(state.status,"")
	if state.code == "CACHE_WRITE_FAILED":
		_image_button.text += " · 未能缓存"
