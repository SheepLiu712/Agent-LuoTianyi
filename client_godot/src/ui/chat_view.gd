extends MarginContainer
signal logout_requested
signal log_requested
signal settings_requested(kind: String)
const ImageOverlay = preload("res://scenes/preview/image_overlay.tscn")
@onready var _margin: MarginContainer = %Margin
@onready var _menu = %ChatMore
@onready var _clear_dialog: Window = %ClearDialog
@onready var _status: Label = %Status
@onready var _history_status: Label = %HistoryStatus
@onready var _history_retry: Button = %HistoryRetry
@onready var _history_skip: Button = %HistorySkip
@onready var _scroll = %Scroll
@onready var _empty: Label = %Empty
@onready var _latest: Button = %Latest
@onready var _unread: Button = %Unread
@onready var _volume: HSlider = %Volume
@onready var _stop_voice: Button = %StopVoice
@onready var _input: TextEdit = %Input
@onready var _send_button: Button = %Send
@onready var _dynamics_button: Button = %Dynamics
var _session: Node
var _initialized := false

func setup(session: Node) -> void:
	_session = session
	if is_node_ready():
		_initialize()

func set_dynamics_unread(count: int) -> void:
	_dynamics_button.text = "动态" if count <= 0 else "动态 · "+("99+" if count > 99 else str(count))

func _ready() -> void:
	if _session == null:
		return
	_initialize()

func _initialize() -> void:
	if _initialized:
		return
	_initialized = true
	_dynamics_button.pressed.connect(func(): settings_requested.emit("dynamics"))
	_menu.action_menu = true
	_menu.text = "更多 ···"
	_menu.set_items([{ "id":"logs","label":"打开日志","disabled":_session.get_log_directory().is_empty()},{"id":"cache","label":"清理本账号语音缓存"},{"id":"preferences","label":"相处模式"},{"id":"models","label":"LLM / VLM 模型设置"},{"separator":true},{"id":"logout","label":"退出登录"}])
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
	_clear_dialog.confirmed.connect(func(): _session.clear_cache())
	_history_retry.pressed.connect(_session.retry_history)
	_history_skip.pressed.connect(_session.skip_history)
	_scroll.audio_action.connect(_audio_action)
	_scroll.image_action.connect(_image_action)
	_scroll.visible_messages.connect(_visible_audio)
	_scroll.interacted.connect(_session.note_read_interaction)
	_latest.pressed.connect(_to_latest)
	_unread.pressed.connect(_jump_reading)
	_input.send_requested.connect(_send)
	_input.text_changed.connect(func():
		var lines: int = _input.get_line_count()
		for line in _input.get_line_count():
			lines += _input.get_line_wrap_count(line)
		_input.custom_minimum_size.y = clampf(lines * 24 + 30, 92, 150))
	_volume.value = _session.get_audio_state().volume
	_volume.value_changed.connect(func(value): _session.set_volume(value))
	_stop_voice.pressed.connect(func(): _session.stop_voice())
	_send_button.pressed.connect(_send)
	_session.message_audio_changed.connect(_audio_changed)
	_session.message_image_changed.connect(func(id,state): _scroll.set_image_state(id,state))
	_session.changed.connect(_refresh)
	_session.state_changed.connect(_state_changed)
	_state_changed(_session.get_state())
	_refresh()
	get_window().focus_entered.connect(_report_reading)

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
			var overlay = ImageOverlay.instantiate()
			overlay.setup(texture,false)
			_margin.add_child(overlay)
			overlay.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
