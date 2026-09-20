extends Control
const Session = preload("res://src/preview/demo_session.gd")
const Bubble = preload("res://scenes/ui/message_bubble.tscn")
const ImagePresenter = preload("res://src/ui/image_presenter.gd")
var _image_presenter: Node
var _session = Session.new()
@onready var _avatar = %AvatarPanel
@onready var _split: HSplitContainer = %Split
@onready var _scroll: ScrollContainer = %Scroll
@onready var _messages: VBoxContainer = %Messages
@onready var _input = %Input
@onready var _status: Label = %Status
@onready var _latest: Button = %Latest
@onready var _empty: Label = %Empty
@onready var _picker: FileDialog = %ImagePicker
@onready var _expressions: OptionButton = %Expressions
@onready var _scenarios: OptionButton = %Scenarios
var _images: Dictionary = {}
var _playing := false
var _scenario := "conversation"
var _ratio := 0.45
var _layout_ready := false
var _refresh_pending := false
var _refresh_again := false

func _ready() -> void:
	_image_presenter = ImagePresenter.new()
	add_child(_image_presenter)
	_expressions.item_selected.connect(func(index): _avatar.avatar.apply_expression(_expressions.get_item_text(index)))
	_scenarios.item_selected.connect(func(index):
		_change_scenario(["conversation", "empty", "disconnected", "error", "thinking"][index]))
	_latest.pressed.connect(_to_latest)
	%PickImage.pressed.connect(_pick_image)
	%TogglePlay.pressed.connect(_toggle_play)
	%Send.pressed.connect(_send)
	_picker.file_selected.connect(func(path): _preview_image(Image.load_from_file(path)))
	_input.send_requested.connect(_send)
	_input.image_pasted.connect(_preview_image)
	_input.text_changed.connect(func():
		var lines: int = _input.get_line_count()
		for line in _input.get_line_count():
			lines += _input.get_line_wrap_count(line)
		_input.custom_minimum_size.y = clampf(lines * 24 + 30, 92, 150))
	var settings := ConfigFile.new()
	if settings.load("user://preview_layout.cfg") == OK:
		var ratio = settings.get_value("layout", "ratio", 0.45)
		if (ratio is float or ratio is int) and is_finite(float(ratio)):
			_ratio = clampf(float(ratio), 0.3, 0.6)
	_split.dragged.connect(func(_offset):
		_ratio = _avatar.size.x / maxf(size.x, 1)
		settings.set_value("layout", "ratio", _ratio)
		if settings.save("user://preview_layout.cfg") != OK:
			_status.text = "分区比例无法保存。")
	resized.connect(_resize_split)
	_session.changed.connect(_refresh)
	_session.select_scenario(_scenario)
	await get_tree().process_frame
	_layout_ready = true
	_resize_split()
	await get_tree().process_frame
	await get_tree().process_frame
	_scroll.scroll_vertical = 0
	for argument in OS.get_cmdline_user_args():
		if argument.begins_with("--scenario="):
			_change_scenario(argument.trim_prefix("--scenario="))
	for argument in OS.get_cmdline_user_args():
		if argument.begins_with("--capture="):
			await get_tree().create_timer(2.0).timeout
			await RenderingServer.frame_post_draw
			var result := get_viewport().get_texture().get_image().save_png(argument.trim_prefix("--capture="))
			get_tree().quit(0 if result == OK else 1)

func _resize_split() -> void:
	if _layout_ready:
		_split.split_offset = roundi(size.x * _ratio)

func _change_scenario(value: String) -> void:
	if value not in ["conversation", "empty", "disconnected", "error", "thinking"]:
		return
	_scenario = value
	_playing = false
	_avatar.avatar.set_mouth_openness(-1)
	_images.clear()
	_session.select_scenario(value)

func _refresh() -> void:
	if _refresh_pending:
		_refresh_again = true
		return
	_refresh_pending = true
	var bar := _scroll.get_v_scroll_bar()
	var follow := bar.value >= bar.max_value - bar.page - 24
	var previous := bar.value
	for child in _messages.get_children():
		if child == _empty:
			continue
		_messages.remove_child(child)
		child.queue_free()
	_empty.visible = _session.get_messages().is_empty()
	_empty.text = {"empty":"从一句问候开始", "disconnected":"连接暂时中断", "error":"暂时无法加载消息"}.get(_scenario, "")
	for message in _session.get_messages():
		message.demo = true
		var bubble = Bubble.instantiate()
		_messages.add_child(bubble)
		var texture: Texture2D = _images.get(message.id)
		if message.has("image"):
			texture = load(message.image)
		bubble.configure(message, texture)
		bubble.image_opened.connect(func(image_texture): _open_image(image_texture, false))
	_status.text = {"conversation":"所有发送状态均为模拟。可以继续输入。", "empty":"还没有消息。写下第一句话吧。", "disconnected":"网络已断开 · 模拟状态，草稿会保留", "error":"历史加载失败 · 模拟状态，草稿会保留", "thinking":"天依正在想一想… · 模拟状态"}[_scenario]
	await get_tree().process_frame
	await get_tree().process_frame
	_refresh_pending = false
	if follow:
		_to_latest()
	else:
		_scroll.scroll_vertical = roundi(previous)
		_latest.visible = true
	if _refresh_again:
		_refresh_again = false
		_refresh()

func _to_latest() -> void:
	_scroll.scroll_vertical = int(_scroll.get_v_scroll_bar().max_value)
	_latest.visible = false

func _send() -> void:
	var id: String = _session.submit_text(_input.text)
	if id.is_empty():
		return
	_input.clear()
	get_tree().create_timer(0.7).timeout.connect(func(): _session.settle(id, true))

func _pick_image() -> void:
	_picker.popup_centered_ratio(0.7)

func _preview_image(image: Image) -> void:
	if image == null or image.is_empty():
		_status.text = "无法读取这张图片，请重新选择。"
		return
	_open_image(ImageTexture.create_from_image(image), true)

func _open_image(texture: Texture2D, pending: bool) -> void:
	_input.release_focus()
	var confirm := Callable()
	if pending:
		confirm = func(value):
			var id: String = _session.submit_text("[图片]")
			if id.is_empty(): return false
			_images[id] = value
			_session.settle(id,true)
			return true
	_image_presenter.open_image(get_window(),func(): return texture,confirm)

func _toggle_play() -> void:
	_playing = not _playing
	_status.text = "模拟播放中 · 仅演示口型，无声音" if _playing else "模拟播放已停止"
	if not _playing:
		_avatar.avatar.set_mouth_openness(-1)

func _process(_delta: float) -> void:
	if _playing:
		_avatar.avatar.set_mouth_openness(absf(sin(Time.get_ticks_msec() * 0.008)) * 0.8)
