extends Control
const Style = preload("res://src/preview/preview_style.gd")
const Session = preload("res://src/preview/demo_session.gd")
const AvatarPanel = preload("res://src/avatar/avatar_panel.gd")
const Bubble = preload("res://scenes/ui/message_bubble.tscn")
const Composer = preload("res://src/preview/composer_input.gd")
const ImageOverlay = preload("res://src/preview/image_overlay.gd")
var _session = Session.new()
var _avatar = AvatarPanel.new()
var _split := HSplitContainer.new()
var _scroll := ScrollContainer.new()
var _messages := VBoxContainer.new()
var _input = Composer.new()
var _status := Label.new()
var _latest := Button.new()
var _images: Dictionary = {}
var _playing := false
var _scenario := "conversation"
var _ratio := 0.45
var _layout_ready := false
var _refresh_pending := false
var _refresh_again := false

func _ready() -> void:
	theme = Style.make_theme()
	var background := ColorRect.new()
	background.color = Color("f5f8fa")
	background.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(background)
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(_split)
	_split.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_split.add_theme_constant_override("separation", 6)
	_avatar.custom_minimum_size.x = 290
	_split.add_child(_avatar)
	_build_character_header()
	_build_chat()
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

func _build_character_header() -> void:
	var header := VBoxContainer.new()
	header.position = Vector2(24, 24)
	header.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_avatar.add_child(header)
	header.add_child(Style.label("洛天依", 25, Color("304d60")))
	header.add_child(Style.label("把平凡的日子，慢慢说给我听。", 13, Color("526b7d")))
	var choices := OptionButton.new()
	var expressions := ["微笑脸", "温柔脸", "喜欢脸", "卖萌", "生气脸", "难过脸", "唱歌"]
	for expression in expressions:
		choices.add_item(expression)
	header.add_child(choices)
	choices.item_selected.connect(func(index): _avatar.avatar.apply_expression(expressions[index]))

func _build_chat() -> void:
	var margin := MarginContainer.new()
	margin.custom_minimum_size.x = 410
	margin.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	for side in ["left", "right", "top", "bottom"]:
		margin.add_theme_constant_override("margin_" + side, 22)
	_split.add_child(margin)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 12)
	margin.add_child(column)
	var heading := HBoxContainer.new()
	column.add_child(heading)
	var title := Style.label("和天依聊聊", 23)
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	heading.add_child(title)
	var scenarios := OptionButton.new()
	for caption in ["日常聊天", "空白会话", "网络断开", "加载失败", "正在思考"]:
		scenarios.add_item(caption)
	heading.add_child(scenarios)
	scenarios.item_selected.connect(func(index):
		_change_scenario(["conversation", "empty", "disconnected", "error", "thinking"][index]))
	column.add_child(Style.label("离线样板 · 未连接服务器", 12, Color("809ba7")))
	_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	column.add_child(_scroll)
	_messages.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_messages.add_theme_constant_override("separation", 17)
	_scroll.add_child(_messages)
	_latest.text = "回到最新 ↓"
	_latest.visible = false
	_latest.pressed.connect(_to_latest)
	column.add_child(_latest)
	column.add_child(_status)
	_status.add_theme_font_size_override("font_size", 12)
	_status.add_theme_color_override("font_color", Color("7c969f"))
	var tools := HBoxContainer.new()
	tools.add_theme_constant_override("separation", 10)
	column.add_child(tools)
	tools.add_child(Style.button("＋ 图片", _pick_image))
	tools.add_child(Style.button("▷ 模拟口型 / 停止", _toggle_play))
	_input.placeholder_text = "想说些什么？"
	_input.custom_minimum_size.y = 92
	_input.wrap_mode = TextEdit.LINE_WRAPPING_BOUNDARY
	column.add_child(_input)
	_input.send_requested.connect(_send)
	_input.image_pasted.connect(_preview_image)
	_input.text_changed.connect(func():
		var lines := _input.get_line_count()
		for line in _input.get_line_count():
			lines += _input.get_line_wrap_count(line)
		_input.custom_minimum_size.y = clampf(lines * 24 + 30, 92, 150))
	var footer := HBoxContainer.new()
	column.add_child(footer)
	var hint := Style.label("Enter 发送 · Shift + Enter 换行", 11, Color("94a5af"))
	hint.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	footer.add_child(hint)
	var send := Style.button("发送  ↑", _send)
	send.custom_minimum_size.x = 96
	send.add_theme_stylebox_override("normal", Style.box(Color("bde5ed"), 9, 10))
	footer.add_child(send)

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
		_messages.remove_child(child)
		child.queue_free()
	if _session.get_messages().is_empty():
		var empty := Style.label({"empty":"从一句问候开始", "disconnected":"连接暂时中断", "error":"暂时无法加载消息"}.get(_scenario, ""), 20, Color("839ca8"))
		empty.custom_minimum_size.y = 240
		empty.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		_messages.add_child(empty)
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
	var dialog := FileDialog.new()
	dialog.file_mode = FileDialog.FILE_MODE_OPEN_FILE
	dialog.access = FileDialog.ACCESS_FILESYSTEM
	dialog.filters = PackedStringArray(["*.png, *.jpg, *.jpeg, *.webp ; 图片"])
	dialog.use_native_dialog = true
	add_child(dialog)
	dialog.file_selected.connect(func(path): _preview_image(Image.load_from_file(path)); dialog.queue_free())
	dialog.canceled.connect(dialog.queue_free)
	dialog.popup_centered_ratio(0.7)

func _preview_image(image: Image) -> void:
	if image == null or image.is_empty():
		_status.text = "无法读取这张图片，请重新选择。"
		return
	_open_image(ImageTexture.create_from_image(image), true)

func _open_image(texture: Texture2D, pending: bool) -> void:
	_input.release_focus()
	var overlay := ImageOverlay.new(texture, pending)
	add_child(overlay)
	overlay.focus_mode = Control.FOCUS_ALL
	overlay.grab_focus()
	overlay.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	overlay.offset_left = 60
	overlay.offset_right = -60
	overlay.offset_top = 60
	overlay.offset_bottom = -60
	overlay.confirmed.connect(func(value):
		var id: String = _session.submit_text("[图片]")
		if id.is_empty():
			overlay.feedback.text = "当前模拟场景无法发送，图片已保留。可取消后切换到日常聊天。"
			return
		_images[id] = value
		overlay.queue_free()
		_session.settle(id, true))

func _toggle_play() -> void:
	_playing = not _playing
	_status.text = "模拟播放中 · 仅演示口型，无声音" if _playing else "模拟播放已停止"
	if not _playing:
		_avatar.avatar.set_mouth_openness(-1)

func _process(_delta: float) -> void:
	if _playing:
		_avatar.avatar.set_mouth_openness(absf(sin(Time.get_ticks_msec() * 0.008)) * 0.8)
