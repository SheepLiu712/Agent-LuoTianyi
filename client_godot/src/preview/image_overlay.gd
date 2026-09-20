extends PanelContainer
signal confirmed(texture: Texture2D)
@onready var _title: Label = %Title
@onready var _zoom_out: Button = %ZoomOut
@onready var _zoom_in: Button = %ZoomIn
@onready var _close: Button = %Close
@onready var _picture: TextureRect = %Picture
@onready var _feedback: Label = %Feedback
@onready var _confirm: Button = %Confirm
var feedback: Label
var _texture: Texture2D
var _pending := false
var _zoom := 1.0
var _initialized := false

func setup(texture: Texture2D, pending: bool) -> void:
	_texture = texture
	_pending = pending
	if is_node_ready():
		_initialize()

func _ready() -> void:
	if _texture == null:
		return
	_initialize()

func _initialize() -> void:
	if _initialized:
		return
	_initialized = true
	feedback = _feedback
	_title.text = "待发送图片" if _pending else "图片预览"
	_close.text = "取消" if _pending else "关闭"
	_close.pressed.connect(queue_free)
	_zoom_out.pressed.connect(func(): _resize_image(0.8))
	_zoom_in.pressed.connect(func(): _resize_image(1.25))
	_picture.texture = _texture
	_feedback.visible = _pending
	_confirm.visible = _pending
	_confirm.pressed.connect(func(): confirmed.emit(_texture))
	resized.connect(func(): _resize_image(1.0))

func _resize_image(factor: float) -> void:
	_zoom = clampf(_zoom * factor, 0.3, 4.0)
	var original := _picture.texture.get_size()
	var available := Vector2(maxf(100, size.x - 60), maxf(100, size.y - 130))
	_picture.custom_minimum_size = original * minf(available.x / original.x, available.y / original.y) * _zoom

func _input(event: InputEvent) -> void:
	if event.is_action_pressed("ui_cancel"):
		get_viewport().set_input_as_handled()
		queue_free()
