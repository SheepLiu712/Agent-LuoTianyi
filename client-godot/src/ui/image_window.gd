extends Window
@export var window_system: Resource = preload("res://src/platform/window_system.gd").new()
var _source: WeakRef
var _previous_focus: WeakRef
var _provider: Callable
var _confirm: Callable
var _active := false
var _hidden_by_source := false
var _fitting := true
var _zoom := 1.0

func _ready() -> void:
	close_requested.connect(close_image)
	%CloseImage.pressed.connect(func(): close_requested.emit())
	%RetryImage.pressed.connect(_load_image)
	%FitImage.pressed.connect(func(): _fitting = true; _resize_image())
	%OriginalSize.pressed.connect(func(): _fitting = false; _zoom = 1; _resize_image())
	%ZoomOut.pressed.connect(func(): _zoom_by(.8))
	%ZoomIn.pressed.connect(func(): _zoom_by(1.25))
	%ConfirmImage.pressed.connect(func():
		if _confirm.is_valid() and _confirm.call(%Picture.texture): close_image()
		else: %Feedback.text = "图片暂时无法发送，请检查当前连接后重试。图片已保留。")
	%ImageScroll.resized.connect(func(): if _fitting: _resize_image())

func present(source: Window, provider: Callable, confirm: Callable = Callable()) -> void:
	_source = weakref(source)
	var focus := source.gui_get_focus_owner()
	_previous_focus = weakref(focus) if focus != null else null
	_provider = provider
	_confirm = confirm
	_active = true
	_hidden_by_source = false
	_fitting = true
	_zoom = 1
	%Feedback.text = ""
	%ConfirmImage.visible = confirm.is_valid()
	%CloseImage.text = "取消" if confirm.is_valid() else "关闭"
	_load_image()
	_reveal()
	_resize_image.call_deferred()

func _reveal() -> void:
	%Chrome.open_window()

func _load_image() -> void:
	var texture: Texture2D = _provider.call() if _provider.is_valid() else null
	%Picture.texture = texture
	%Picture.visible = texture != null
	%ImageError.visible = texture == null
	%RetryImage.visible = texture == null
	for button in [%ZoomIn,%ZoomOut,%FitImage,%OriginalSize,%ConfirmImage]: button.disabled = texture == null
	if texture != null: _resize_image()

func _resize_image() -> void:
	var texture: Texture2D = %Picture.texture
	if texture == null: return
	var original := texture.get_size()
	if _fitting:
		var available: Vector2 = (%ImageScroll.size-Vector2(20,20)).max(Vector2.ONE)
		_zoom = minf(available.x/original.x,available.y/original.y)
	%Picture.custom_minimum_size = original*_zoom
	%ZoomLabel.text = "%s%%" % roundi(_zoom*100)

func _zoom_by(factor: float) -> void:
	_fitting = false
	_zoom = clampf(_zoom*factor,.05,8)
	_resize_image()

func close_image() -> void:
	_active = false
	_hidden_by_source = false
	hide()
	%Picture.texture = null
	_provider = Callable()
	_confirm = Callable()
	var source = _source.get_ref() if _source != null else null
	if is_instance_valid(source) and not window_system.minimized(source):
		window_system.focus(source)
		var control = _previous_focus.get_ref() if _previous_focus != null else null
		if is_instance_valid(control) and control.is_visible_in_tree(): control.grab_focus()

func _process(_delta: float) -> void:
	if not _active: return
	var source = _source.get_ref() if _source != null else null
	if not is_instance_valid(source): close_image(); return
	if window_system.minimized(source):
		if not _hidden_by_source and not window_system.minimized(self):
			_hidden_by_source = true
			hide()
	elif _hidden_by_source:
		_hidden_by_source = false
		_reveal()

func _input(event: InputEvent) -> void:
	if visible and event.is_action_pressed("ui_cancel"):
		get_viewport().set_input_as_handled()
		close_requested.emit()
