extends MarginContainer
signal logout_requested
signal log_requested
signal settings_requested(kind: String)
const Style = preload("res://src/preview/preview_style.gd")
const Composer = preload("res://src/preview/composer_input.gd")
const Dropdown = preload("res://scenes/ui/unified_dropdown.tscn")
var _session: Node
var _scroll = preload("res://src/ui/virtual_message_list.gd").new()
var _input = Composer.new()
var _status := Label.new()
var _latest := Button.new()
var _empty := Label.new()
var _stop_voice: Button
var _clear_dialog := ConfirmationDialog.new()
var _menu
var _history_status := Label.new()
var _history_retry := Button.new()
var _history_skip := Button.new()
var _unread := Button.new()
var _dynamics_button := Button.new()

func _init(session: Node) -> void:
	_session = session

func set_dynamics_unread(count: int) -> void:
	_dynamics_button.text = "动态" if count <= 0 else "动态 · "+("99+" if count > 99 else str(count))

func _ready() -> void:
	theme = Style.make_theme()
	for side in ["left", "right", "top", "bottom"]:
		add_theme_constant_override("margin_" + side, 22)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 12)
	add_child(column)
	var heading := HBoxContainer.new()
	heading.add_theme_constant_override("separation", 12)
	column.add_child(heading)
	heading.add_child(Style.avatar("res://assets/ui/tianyi_icon.png",42))
	var identity := VBoxContainer.new()
	identity.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	heading.add_child(identity)
	identity.add_child(Style.label("和天依聊聊", 22))
	_dynamics_button.text = "动态"
	_dynamics_button.pressed.connect(func(): settings_requested.emit("dynamics"))
	heading.add_child(_dynamics_button)
	_menu = Dropdown.instantiate()
	_menu.action_menu = true
	_menu.text = "更多 ···"
	heading.add_child(_menu)
	_menu.name = "ChatMore"
	_menu.set_items([{ "id":"logs","label":"打开日志","disabled":_session.get_log_directory().is_empty()},{"id":"cache","label":"清理本账号语音缓存"},{"id":"preferences","label":"相处模式"},{"id":"models","label":"LLM / VLM 模型设置"},{"separator":true},{"id":"logout","label":"退出登录"}])
	_clear_dialog.title = "清理语音缓存"
	_clear_dialog.dialog_text = "清理当前服务器、本账号保存的全部语音？\n聊天文字保留；已清理的语音将无法重放。"
	_clear_dialog.ok_button_text = "清理"
	_clear_dialog.cancel_button_text = "取消"
	add_child(_clear_dialog)
	_clear_dialog.confirmed.connect(func(): _session.clear_cache())
	_menu.activated.connect(func(id):
		if id == "logs":
			log_requested.emit()
		elif id == "cache":
			_clear_dialog.popup_centered()
			_clear_dialog.get_cancel_button().grab_focus()
		elif id == "logout":
			logout_requested.emit()
		elif id == "preferences":
			settings_requested.emit("preferences")
		elif id == "models":
			settings_requested.emit("models"))
	_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_status.add_theme_font_size_override("font_size", 13)
	_status.add_theme_color_override("font_color", Color("607f8d"))
	identity.add_child(_status)
	column.add_child(HSeparator.new())
	var history_row := HBoxContainer.new()
	column.add_child(history_row)
	_history_status.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_history_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_history_status.add_theme_font_size_override("font_size",12)
	history_row.add_child(_history_status)
	_history_retry.text = "重试历史"
	_history_retry.pressed.connect(_session.retry_history)
	history_row.add_child(_history_retry)
	_history_skip.text = "跳过本次"
	_history_skip.pressed.connect(_session.skip_history)
	history_row.add_child(_history_skip)
	var audio_controls := HBoxContainer.new()
	audio_controls.add_child(Style.label("语音音量", 12))
	var volume := HSlider.new()
	volume.min_value = 0
	volume.max_value = 1
	volume.step = .01
	volume.value = _session.get_audio_state().volume
	volume.custom_minimum_size.x = 110
	volume.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	volume.tooltip_text = "回复语音自动播放；拖到最左侧静音"
	volume.value_changed.connect(func(value): _session.set_volume(value))
	audio_controls.add_child(volume)
	_stop_voice = Style.button("停止语音", func(): _session.stop_voice())
	audio_controls.add_child(_stop_voice)
	_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	column.add_child(_scroll)
	_empty.text = "从一句问候开始"
	_empty.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(_empty)
	_scroll.audio_action.connect(_audio_action)
	_scroll.image_action.connect(_image_action)
	_scroll.visible_messages.connect(_visible_audio)
	_scroll.interacted.connect(_session.note_read_interaction)
	_latest.text = "回到最新 ↓"
	_latest.hide()
	_latest.pressed.connect(_to_latest)
	column.add_child(_latest)
	_unread.text = "定位未读"
	_unread.hide()
	_unread.pressed.connect(_jump_reading)
	column.add_child(_unread)
	column.add_child(HSeparator.new())
	column.add_child(audio_controls)
	_input.placeholder_text = "想说些什么？"
	_input.custom_minimum_size.y = 92
	_input.wrap_mode = TextEdit.LINE_WRAPPING_BOUNDARY
	column.add_child(_input)
	_input.send_requested.connect(_send)
	_input.text_changed.connect(func():
		var lines: int = _input.get_line_count()
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
	Style.primary(send)
	footer.add_child(send)
	_session.message_audio_changed.connect(_audio_changed)
	_session.message_image_changed.connect(func(id,state): _scroll.set_image_state(id,state))
	_session.changed.connect(_refresh)
	_session.state_changed.connect(_state_changed)
	_state_changed(_session.get_state())
	_refresh()
	get_window().focus_entered.connect(_report_reading)

func _draw() -> void:
	draw_rect(Rect2(Vector2.ZERO,size), Style.SURFACE)

func _send() -> void:
	_session.note_read_interaction()
	if not _session.send_text(_input.text).is_empty():
		_input.clear()

func _refresh() -> void:
	var messages: Array[Dictionary] = _session.get_messages()
	_empty.visible = messages.is_empty()
	_scroll.set_messages(messages)
	_visible_audio(_scroll.get_visible_ids())
	_apply_reading()

func _visible_audio(ids: Array[String]) -> void:
	for id in ids:
		_scroll.set_audio_state(id,_session.get_message_audio(id))
		_session.request_message_image(id)
		_scroll.set_image_state(id,_session.get_message_image(id))
	_latest.visible = not _scroll.is_at_latest()
	_report_reading()

func _to_latest() -> void:
	_scroll.scroll_to_latest()
	_latest.hide()

func _state_changed(state: Dictionary) -> void:
	var history: Dictionary = state.get("history",{"phase":"idle","count":0})
	_history_retry.visible = history.phase in ["first_failed","failed"]
	_history_skip.visible = history.phase == "first_failed"
	_history_status.text = {"first_loading":"正在同步最近历史；发送的消息将暂时排队。", "first_failed":"首批历史加载失败；可重试或跳过后发送。", "loading":"后台同步历史 · 已加载 %s 条" % history.count, "failed":"较早历史加载失败，已加载内容保留。", "skipped":"已跳过本次历史同步。"}.get(history.phase, "")
	if history.get("incomplete",false):
		_history_status.text += " 检测到分页重复，无法确认历史完整。"
	_apply_reading()
	var reading: Dictionary = _session.get_reading_state()
	if reading.reason == "NOT_FOUND":
		_history_status.text += " 原阅读位置已找不到，回到最新消息。"
	elif reading.reason == "SAVE_FAILED":
		_history_status.text += " 本机阅读位置未能保存。"
	_status.text = {"idle":"连接已关闭", "connecting":"正在连接…", "authenticating":"正在验证账户…",
		"ready":"已连接", "reconnecting":"正在重新连接 · 可以继续输入", "auth_rejected":"聊天凭据已失效，请退出后重新登录。"}.get(state.phase, "")
	if state.thinking:
		_status.text = "天依正在想一想…"
	if state.get("speaking", false):
		_status.text += " · 正在播放语音"
	_stop_voice.disabled = not state.get("speaking", false)
	if state.code == "AUDIO_ERROR":
		_status.text += " · 本条语音暂时无法播放，文字已保留。"
	elif state.code == "CACHE_CLEAR_FAILED":
		_status.text += " · 部分语音未能清理，请关闭占用文件后重试。"
	elif state.code == "SEND_REJECTED":
		_status.text += " · 暂时无法发送，内容已保留。"
	elif state.code == "INVALID_RESPONSE":
		_status.text += " · 收到的数据不完整。"
	elif state.phase == "ready" and not state.code.is_empty():
		_status.text += " · 服务器暂时无法处理请求，请稍后重试。"

func _audio_changed(id: String, state: Dictionary) -> void:
	_scroll.set_audio_state(id,state)

func _audio_action(id: String, action: String) -> void:
	match action:
		"play": _session.replay(id)
		"pause": _session.pause_replay()
		"resume": _session.resume_replay()
		"stop": _session.stop_replay()

func _apply_reading() -> void:
	var reading: Dictionary = _session.get_reading_state()
	if reading.pending or reading.located:
		return
	if reading.manual:
		_unread.visible = not reading.target_id.is_empty()
		_session.reading_located()
	else:
		_jump_reading()

func _jump_reading() -> void:
	var reading: Dictionary = _session.get_reading_state()
	if reading.pending:
		return
	if not reading.target_id.is_empty() and not _scroll.scroll_to_message(reading.target_id):
		return
	_session.reading_located()
	_unread.hide()
	_report_reading.call_deferred()

func _report_reading() -> void:
	if is_inside_tree():
		_session.report_visible_messages(_scroll.get_visible_ids(),is_visible_in_tree() and get_window().has_focus() and get_window().mode != Window.MODE_MINIMIZED)

func _image_action(id: String, action: String) -> void:
	if action == "retry":
		_session.request_message_image(id,true)
	else:
		var texture: Texture2D = _session.preview_message_image(id)
		if texture != null:
			var overlay = preload("res://src/preview/image_overlay.gd").new(texture,false)
			add_child(overlay)
			overlay.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
