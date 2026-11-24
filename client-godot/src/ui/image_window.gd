extends Window
@export var window_system: Resource = preload("res://src/platform/window_system.gd").new()
const ErrorDialog = preload("res://src/ui/error_dialog.gd")
const UiMotion = preload("res://src/ui/ui_motion.gd")
var _source: WeakRef
var _previous_focus: WeakRef
var _provider: Callable
var _confirm: Callable
var _active := false
var _hidden_by_source := false
var _fitting := true
var _zoom := 1.0
var _error_announced := false
var _panning := false

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
		else:
			_set_feedback("")
			ErrorDialog.present(self, "图片暂时无法发送，请检查当前连接后重试。图片已保留。"))
	%ImageScroll.resized.connect(func(): if _fitting: _resize_image())
	%ImageScroll.gui_input.connect(_on_scroll_gui_input)
	%Picture.gui_input.connect(_on_scroll_gui_input)
	UiMotion.bind_interactive_cursors(self)

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
	_error_announced = false
	_set_feedback("")
	%ConfirmImage.visible = confirm.is_valid()
	%CloseImage.text = "取消" if confirm.is_valid() else "关闭"
	_load_image()
	_reveal()
	_focus_action.call_deferred()
	_resize_image.call_deferred()


## 打开后键盘焦点必须落在可用动作上：失败时是重试，正常时是适应窗口。
func _focus_action() -> void:
	if %RetryImage.visible:
		%RetryImage.grab_focus()
	else:
		%FitImage.grab_focus()

func _reveal() -> void:
	%Chrome.open_window()

func _load_image() -> void:
	var texture: Texture2D = _provider.call() if _provider.is_valid() else null
	%Picture.texture = texture
	%Picture.visible = texture != null
	%Backdrop.visible = texture != null
	%ImageError.visible = false
	%RetryImage.visible = texture == null
	if texture == null and not _error_announced:
		_error_announced = true
		ErrorDialog.present(self, "图片暂时无法读取，请重试。")
	for button in [%ZoomIn,%ZoomOut,%FitImage,%OriginalSize,%ConfirmImage]: button.disabled = texture == null
	if texture != null: _resize_image()
	# 重试成功后按钮会消失，焦点不能跟着消失，否则键盘用户就断了出口。
	if not %RetryImage.visible and %RetryImage.has_focus(): %FitImage.grab_focus()

func _set_feedback(text: String) -> void:
	%Feedback.text = text
	%Feedback.visible = not text.is_empty()

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
	if not visible:
		return
	if event.is_action_pressed("ui_cancel"):
		get_viewport().set_input_as_handled()
		close_requested.emit()
		return
	if event is InputEventKey and event.pressed and not event.echo:
		_handle_zoom_key(event)


func _handle_zoom_key(event: InputEventKey) -> void:
	if %Picture.texture == null:
		return
	match event.keycode:
		KEY_EQUAL, KEY_KP_ADD, KEY_PLUS:
			_zoom_by(1.25)
		KEY_MINUS, KEY_KP_SUBTRACT:
			_zoom_by(0.8)
		KEY_0, KEY_KP_0:
			_fitting = true
			_resize_image()
		_:
			return
	get_viewport().set_input_as_handled()


func _on_scroll_gui_input(event: InputEvent) -> void:
	if %Picture.texture == null:
		return
	if event is InputEventMouseButton:
		_handle_scroll_button(event)
	elif event is InputEventMouseMotion and _panning:
		%ImageScroll.scroll_horizontal -= roundi(event.relative.x)
		%ImageScroll.scroll_vertical -= roundi(event.relative.y)
		%ImageScroll.accept_event()


func _handle_scroll_button(event: InputEventMouseButton) -> void:
	if event.button_index == MOUSE_BUTTON_LEFT:
		_panning = event.pressed
		%Picture.mouse_default_cursor_shape = Control.CURSOR_MOVE if _panning else Control.CURSOR_ARROW
		return
	if not event.pressed:
		return
	if event.button_index == MOUSE_BUTTON_WHEEL_UP:
		_zoom_by(1.15)
		%ImageScroll.accept_event()
	elif event.button_index == MOUSE_BUTTON_WHEEL_DOWN:
		_zoom_by(1.0 / 1.15)
		%ImageScroll.accept_event()
