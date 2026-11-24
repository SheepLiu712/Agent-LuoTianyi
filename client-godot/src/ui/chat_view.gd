extends MarginContainer
@export var window_system: Resource = preload("res://src/platform/window_system.gd").new()
@export var files: Resource = preload("res://src/platform/file_interaction.gd").new()
signal image_requested(provider: Callable)
signal attachment_requested(provider: Callable, confirm: Callable)
signal attachment_cleared
## 松手才发一次：应用层据此写盘，拖动过程中不碰磁盘。
signal composer_height_changed(height: float)
const Attachment = preload("res://src/media/image_attachment.gd")
const DraftAutosave = preload("res://src/ui/draft_autosave.gd")
const ErrorDialog = preload("res://src/ui/error_dialog.gd")
const StatusBanner = preload("res://src/ui/status_banner.gd")
const ToastOverlay = preload("res://src/ui/toast_overlay.gd")
const UiMotion = preload("res://src/ui/ui_motion.gd")
const DecisionDialog = preload("res://scenes/ui/components/decision_dialog.tscn")
const MIN_COMPOSER_HEIGHT := 44.0
const MAX_COMPOSER_HEIGHT := 320.0
const AUTO_MAX_HEIGHT := 128.0
const COMPOSER_LINE_HEIGHT := 22.0
const COMPOSER_PADDING := 22.0
const DOT_ONLINE := Color("228b54")
const DOT_BUSY := Color("c77d18")
const DOT_THINKING := Color("1278ad")
const DOT_OFFLINE := Color("8da0ad")
var _attachment: Dictionary = {}
var _drafts: RefCounted
var _scope := ""
var _text_draft: RefCounted
var _attachment_save_failed := false
@onready var _margin: MarginContainer = %Margin
@onready var _status_dot: Panel = %StatusDot
@onready var _status: Label = %Status
@onready var _composer_box: PanelContainer = %ComposerBox
@onready var _history_status: Label = %HistoryStatus
@onready var _history_retry: Button = %HistoryRetry
@onready var _history_skip: Button = %HistorySkip
@onready var _history_reset: Button = %HistoryReset
@onready var _scroll = %Scroll
@onready var _latest: Button = %Latest
@onready var _unread: Button = %Unread
@onready var _volume: HSlider = %Volume
@onready var _input: TextEdit = %Input
@onready var _send_button: Button = %Send
## 输入区上沿的分隔线就是拖动带：抓这里才是抓那条线。
@onready var _composer = %ComposerSurface
var _session: Node
var _initialized := false
var _ui_style: RefCounted
var _card_style: StyleBoxFlat
var _composer_style: StyleBoxFlat
var _composer_box_style: StyleBoxFlat
var _status_dot_style: StyleBoxFlat
var _input_focused := false
var _auto_height := MIN_COMPOSER_HEIGHT
var _manual_height := 0.0
## 未读目标不在当前窗口时，等下一页历史到达后再试一次；用户显式操作会取消。
var _pending_unread_jump := false
var _last_error_code := ""
var _last_history_phase := ""
var _announced_messages: Dictionary = {}
var _auth_announced := false
var _history_incomplete_announced := false
var _refresh_queued := false
var _volume_trigger: RefCounted

func set_ui_style(style: RefCounted) -> void:
	if _ui_style != null and _ui_style.style_changed.is_connected(_apply_ui_style):
		_ui_style.style_changed.disconnect(_apply_ui_style)
	_ui_style = style
	style.apply_view(self, {"ImageButton":"action_image", "Send":"action_send", "Latest":"action_arrow_down", "Unread":"action_arrow_down", "VolumeButton":"media_volume"})
	get_node("%Scroll").set_ui_style(style)
	_ui_style.style_changed.connect(_apply_ui_style)
	if is_node_ready(): _apply_ui_style()

func _apply_ui_style() -> void:
	if _ui_style == null or not is_node_ready():
		return
	_ui_style.apply_chat_card_style(_card_style)
	if _card_style != null and not _ui_style.is_crystal():
		_card_style.set_corner_radius_all(10)
	_ui_style.apply_composer_style(_composer_style)
	_ui_style.apply_composer_box_style(_composer_box_style)
	_send_button.add_theme_constant_override("icon_max_width", 16)
	_sync_composer_focus_border()
	_sync_history_banner(_last_history_phase)

func setup(session: Node, drafts: RefCounted = null, scope: String = "") -> void:
	_session = session
	_drafts = drafts
	_scope = scope
	if is_node_ready():
		_initialize()

func is_dirty() -> bool:
	return not _input.text.strip_edges().is_empty() or not _attachment.is_empty()

func _ready() -> void:
	_volume_trigger = preload("res://src/ui/popup_trigger.gd").new(%VolumeButton, %VolumePopup)
	_send_button.add_theme_constant_override("icon_max_width", 16)
	%VolumeButton.pressed.connect(_show_volume)
	_card_style = get_node("Background").get_theme_stylebox("panel").duplicate() as StyleBoxFlat
	get_node("Background").add_theme_stylebox_override("panel", _card_style)
	_composer_style = _composer.get_theme_stylebox("panel").duplicate() as StyleBoxFlat
	_composer.add_theme_stylebox_override("panel", _composer_style)
	_composer_box_style = _composer_box.get_theme_stylebox("panel").duplicate() as StyleBoxFlat
	_composer_box.add_theme_stylebox_override("panel", _composer_box_style)
	_status_dot_style = _status_dot.get_theme_stylebox("panel").duplicate() as StyleBoxFlat
	_status_dot.add_theme_stylebox_override("panel", _status_dot_style)
	_input.focus_entered.connect(func(): _input_focused = true; _sync_composer_focus_border())
	_input.focus_exited.connect(func(): _input_focused = false; _sync_composer_focus_border())
	_apply_ui_style()
	UiMotion.bind_interactive_cursors(self)
	UiMotion.bind_tactile_press(_send_button, func(): return _ui_style)
	UiMotion.bind_tactile_press(_latest, func(): return _ui_style)
	UiMotion.bind_tactile_press(_unread, func(): return _ui_style)
	for prompt in %QuickPrompts.get_children():
		if prompt is Button:
			UiMotion.bind_tactile_press(prompt, func(): return _ui_style)
			prompt.pressed.connect(func(): _fill_quick_prompt(prompt.text))
	resized.connect(_update_density)
	_update_density()
	_composer.drag_delta.connect(_on_resize_drag)
	_composer.drag_committed.connect(_on_resize_commit)
	if _session == null:
		return
	_initialize()

func _initialize() -> void:
	if _initialized:
		return
	_initialized = true
	_history_retry.pressed.connect(_session.retry_history)
	_history_skip.pressed.connect(_session.skip_history)
	_history_reset.pressed.connect(_confirm_reset_history)
	_scroll.audio_action.connect(_audio_action)
	_scroll.image_action.connect(_image_action)
	_scroll.delivery_action.connect(_delivery_action)
	_scroll.visible_messages.connect(_visible_audio)
	_scroll.at_latest_changed.connect(_on_at_latest_changed)
	_scroll.interacted.connect(_on_scroll_interacted)
	if _session.has_method("load_older_history"):
		_scroll.older_requested.connect(_session.load_older_history)
	if _session.has_method("set_avatar"):
		_session.user_avatar_changed.connect(_scroll.set_user_avatar)
		_scroll.set_user_avatar(_session.get_user_avatar())
	_latest.pressed.connect(_to_latest)
	_unread.pressed.connect(_request_unread)
	_input.send_requested.connect(_send)
	_input.image_pasted.connect(func(image):
		_session.set_image_selecting(true)
		_attach(Attachment.from_image(image)))
	%ImageButton.pressed.connect(func():
		_session.set_image_selecting(true)
		files.select_image())
	files.bind(%ImagePicker)
	files.image_selected.connect(func(result): _attach(Attachment.from_bytes(result.bytes,result.mime) if result.ok else result))
	files.canceled.connect(func(): _session.set_image_selecting(false))
	%PreviewImage.pressed.connect(_preview_attachment)
	%RemoveImage.pressed.connect(func(): _clear_attachment(true))
	_input.text_changed.connect(_on_input_text_changed)
	_restore_drafts()
	_volume.value = _session.get_audio_state().volume
	_volume.value_changed.connect(func(value): _session.set_volume(value))
	_send_button.pressed.connect(_send)
	_session.message_audio_changed.connect(_audio_changed)
	_session.message_image_changed.connect(func(id,state): _scroll.set_image_state(id,state))
	_session.changed.connect(_schedule_refresh)
	_session.state_changed.connect(_state_changed)
	_state_changed(_session.get_state())
	_refresh()
	get_window().focus_entered.connect(_report_reading)

func _show_volume() -> void:
	if _volume_trigger != null and not _volume_trigger.should_open():
		return
	var popup: PopupPanel = %VolumePopup
	var button: Button = %VolumeButton
	var popup_position := button.get_global_rect().position if get_viewport().gui_embed_subwindows else button.get_screen_position()
	popup_position.y -= popup.size.y + 8
	popup.popup(Rect2i(Vector2i(popup_position), popup.size))
	UiMotion.reveal_overlay(popup.get_node("VolumeMargin"), Vector2(0.15, 1.0), 4.0, 0.16, _ui_style)

func _send() -> void:
	_session.note_read_interaction()
	_session.set_typing(false)
	var has_text := not _input.text.strip_edges().is_empty()
	var has_attachment := not _attachment.is_empty()
	if not has_text and not has_attachment:
		return
	if str(_session.get_state().get("phase", "")) in ["idle", "auth_rejected"]:
		ErrorDialog.present(self, "未连接，消息未发送。")
		return
	if has_attachment and not _confirm_attachment(null):
		return
	if has_text and not _session.send_text(_input.text).is_empty():
		_input.clear()
		if _text_draft != null:
			_text_draft.clear()
		_last_error_code = ""
		_update_auto_height()

## 文本自动增高只决定下限：手动拖过的高度不会被一段短文本压回去。
func _on_input_text_changed() -> void:
	_session.set_typing(not _input.text.is_empty(), _input.text.length())
	_update_auto_height()

func _update_auto_height() -> void:
	var lines: int = _input.get_line_count()
	for line in _input.get_line_count():
		lines += _input.get_line_wrap_count(line)
	_auto_height = clampf(lines * COMPOSER_LINE_HEIGHT + COMPOSER_PADDING, MIN_COMPOSER_HEIGHT, AUTO_MAX_HEIGHT)
	_apply_height()

## 0（或任何小于最小值的数）表示只跟随文本自动高度。
func set_composer_height(height: float) -> void:
	_manual_height = 0.0 if height < MIN_COMPOSER_HEIGHT else minf(height, MAX_COMPOSER_HEIGHT)
	_apply_height()

func get_composer_height() -> float:
	return _input.custom_minimum_size.y

func _apply_height() -> void:
	_input.custom_minimum_size.y = clampf(maxf(_auto_height, _manual_height), MIN_COMPOSER_HEIGHT, MAX_COMPOSER_HEIGHT)

## 往上拖 relative.y 为负，所以用减法：base - delta 就是「变高」。
func _on_resize_drag(delta_y: float) -> void:
	var base := _manual_height if _manual_height > 0.0 else _auto_height
	_manual_height = clampf(base - delta_y, MIN_COMPOSER_HEIGHT, MAX_COMPOSER_HEIGHT)
	_apply_height()

func _on_resize_commit() -> void:
	if _manual_height > 0.0:
		composer_height_changed.emit(_manual_height)

func _attach(result: Dictionary) -> void:
	%ImageStatus.show()
	if not result.ok:
		%ImageStatus.text = ""
		%ImageStatus.hide()
		ErrorDialog.present(self, {"IMAGE_TOO_LARGE":"图片过大，请选择小于 6 MiB 的图片。", "IMAGE_DIMENSIONS":"图片尺寸过大（最多8192像素、1600万像素）。", "IMAGE_FORMAT":"支持 PNG、JPEG、WebP 和 BMP 图片。", "IMAGE_READ_FAILED":"图片无法读取，请检查文件后重试。"}.get(result.code,"图片格式无效或文件已损坏。"))
		_session.set_image_selecting(false)
		return
	_apply_attachment(result)
	_persist_attachment()
	if _should_default_preview_image():
		_preview_attachment()


func _apply_attachment(result: Dictionary) -> void:
	_attachment = result
	%AttachmentThumbnail.texture = result.texture
	%AttachmentBar.show()
	%ImageStatus.text = ""
	%ImageStatus.hide()

func _should_default_preview_image() -> bool:
	return bool(_ui_style.default_preview_image) if _ui_style != null and "default_preview_image" in _ui_style else true

func _preview_attachment() -> void:
	if _attachment.is_empty(): return
	var texture: Texture2D = _attachment.texture
	attachment_requested.emit(func(): return texture, _confirm_attachment)

func _confirm_attachment(_texture: Texture2D) -> bool:
	if _attachment.is_empty(): return false
	var id: String = _session.send_image(_attachment.bytes, _attachment.mime)
	if id.is_empty():
		%ImageStatus.text = ""
		%ImageStatus.hide()
		ErrorDialog.present(self, "图片暂时无法发送，请检查当前连接后重试。图片已保留。")
		return false
	_clear_attachment(false)
	return true

func _clear_attachment(canceled: bool) -> void:
	_attachment.clear()
	%AttachmentThumbnail.texture = null
	%AttachmentBar.hide()
	%ImageStatus.text = ""
	%ImageStatus.hide()
	_attachment_save_failed = false
	if _drafts != null and not _scope.is_empty():
		_drafts.clear_attachment(_scope, "chat.image")
	if canceled: _session.set_image_selecting(false)
	attachment_cleared.emit()

## 同一帧内多个流式分片只刷新一次，避免重复深拷贝和整表重排。
func _schedule_refresh() -> void:
	if _refresh_queued:
		return
	_refresh_queued = true
	_refresh.call_deferred()


func _fill_quick_prompt(prompt_text: String) -> void:
	_input.text = prompt_text
	_input.grab_focus()
	_input.set_caret_column(prompt_text.length())
	_on_input_text_changed()
	if _text_draft != null:
		_text_draft.flush()


func _refresh() -> void:
	_refresh_queued = false
	var retry_unread := _pending_unread_jump
	var messages: Array[Dictionary] = _session.get_messages_view() if _session.has_method("get_messages_view") else _session.get_messages()
	_announce_message_failures(messages)
	_scroll.set_messages(messages)
	_sync_empty_welcome(messages)
	_visible_audio(_scroll.get_visible_ids())
	_apply_reading()
	if retry_unread and _pending_unread_jump:
		_pending_unread_jump = false
		_jump_reading()


func _sync_empty_welcome(messages: Array[Dictionary]) -> void:
	if _session == null or not _session.has_method("get_state"):
		%EmptyWelcome.visible = messages.is_empty()
		return
	var phase := str(_session.get_state().get("history", {}).get("phase", ""))
	%EmptyWelcome.visible = messages.is_empty() and phase in ["complete", "skipped", "idle", ""]

func _visible_audio(ids: Array[String]) -> void:
	for id in ids:
		_scroll.set_audio_state(id,_session.get_message_audio(id))
		_session.request_message_image(id)
		_scroll.set_image_state(id,_session.get_message_image(id))
	_update_latest_visibility()
	_report_reading()

func _to_latest() -> void:
	_pending_unread_jump = false
	_session.dismiss_unread()
	_unread.hide()
	_scroll.scroll_to_latest()
	_latest.hide()
	_report_reading.call_deferred()

func _sync_composer_focus_border() -> void:
	if _composer_box_style == null:
		return
	var crystal: bool = _ui_style != null and _ui_style.is_crystal()
	var normal_border := Color(0.72, 0.88, 1.0, 0.62) if crystal else Color("dbe7f0")
	_composer_box_style.border_color = Color("66ccff") if _input_focused else normal_border
	_composer_box_style.set_border_width_all(2 if _input_focused else 1)


func _state_changed(state: Dictionary) -> void:
	_update_history_status(state)
	var phase := str(state.get("phase", ""))
	_status.text = {"idle":"离线", "connecting":"正在连接…", "authenticating":"正在验证账户…",
		"ready":"在线", "reconnecting":"连接已断开，正在重试", "auth_rejected":"离线"}.get(phase, "")
	var dot_color := DOT_OFFLINE
	if phase == "ready":
		dot_color = DOT_ONLINE
	elif phase in ["connecting", "authenticating", "reconnecting"]:
		dot_color = DOT_BUSY
	if state.thinking:
		_status.text = "天依正在想一想…"
		dot_color = DOT_THINKING
	if state.get("speaking", false):
		_status.text += " · 正在播放语音"
	if _status_dot_style != null:
		_status_dot_style.bg_color = dot_color
	if phase == "auth_rejected":
		if not _auth_announced:
			_auth_announced = true
			ErrorDialog.present(self, "聊天凭据已失效，请重新登录。")
	else:
		_auth_announced = false
	_announce_chat_code(str(state.code))
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
	if reading.pending:
		return
	if str(reading.target_id).is_empty():
		_unread.hide()
		return
	if reading.located:
		_unread.hide()
		return
	if reading.manual:
		_unread.show()
		if _scroll.has_message(str(reading.target_id)):
			_session.reading_located()
	else:
		_jump_reading()

func _jump_reading() -> void:
	var reading: Dictionary = _session.get_reading_state()
	if reading.pending:
		return
	var target := str(reading.target_id)
	if target.is_empty():
		_pending_unread_jump = false
		_unread.hide()
		return
	if not _scroll.scroll_to_message(target):
		_pending_unread_jump = true
		if _session.has_method("load_older_history"):
			_session.load_older_history()
		return
	_pending_unread_jump = false
	_session.reading_located()
	_unread.hide()
	_update_latest_visibility()
	_report_reading.call_deferred()

func _request_unread() -> void:
	_session.note_read_interaction()
	_jump_reading()

## 用户真实滚动会取消待执行的未读跳转，避免下一页到达后反向拉回。
func _on_scroll_interacted() -> void:
	_pending_unread_jump = false
	_session.note_read_interaction()

func _update_latest_visibility() -> void:
	_latest.visible = not _scroll.is_at_latest()

func _on_at_latest_changed(at_latest: bool) -> void:
	_latest.visible = not at_latest

func _report_reading() -> void:
	if is_inside_tree():
		_session.report_visible_messages(_scroll.get_visible_ids(),is_visible_in_tree() and window_system.focused(get_window()))

func _image_action(id: String, action: String) -> void:
	if action == "retry":
		_session.request_message_image(id,true)
	else:
		image_requested.emit(func():
			var texture: Texture2D = _session.preview_message_image(id)
			if texture == null: _session.request_message_image(id,true)
			return texture)


func _delivery_action(id: String, action: String) -> void:
	if action == "retry":
		_session.retry_message(id)
	elif action == "delete":
		_session.delete_message(id)

func flush_drafts() -> bool:
	var ok := true
	if _text_draft != null:
		ok = bool(_text_draft.flush()) and ok
	if not _attachment.is_empty() and _attachment_save_failed:
		_persist_attachment()
		ok = not _attachment_save_failed and ok
	return ok


func loss_warnings() -> Array[String]:
	var warnings: Array[String] = []
	if _drafts == null or _scope.is_empty():
		if is_dirty():
			warnings.append("聊天输入中的未发送文字或图片")
		return warnings
	if not _input.text.strip_edges().is_empty() and _text_draft != null and _text_draft.has_failure():
		warnings.append("聊天草稿保存失败")
	if not _attachment.is_empty() and _attachment_save_failed:
		warnings.append("待发送图片保存失败")
	return warnings


func _restore_drafts() -> void:
	if _drafts == null or _scope.is_empty():
		return
	_text_draft = DraftAutosave.new()
	_text_draft.bind(_input, _drafts, _scope, "chat.text")
	if not _input.text.is_empty():
		_input.set_caret_column(_input.text.length())
		_update_auto_height()
	var stored: Dictionary = _drafts.read_attachment(_scope, "chat.image")
	if stored.is_empty():
		return
	if not bool(stored.get("ok", false)):
		_drafts.clear_attachment(_scope, "chat.image")
		_show_image_restore_error()
		return
	var bytes: PackedByteArray = stored.get("bytes", PackedByteArray())
	var result: Dictionary = Attachment.from_bytes(bytes, str(stored.get("mime", "")))
	if bool(result.get("ok", false)):
		_apply_attachment(result)
	else:
		_drafts.clear_attachment(_scope, "chat.image")
		_show_image_restore_error()


func _persist_attachment() -> void:
	if _drafts == null or _scope.is_empty() or _attachment.is_empty():
		return
	var bytes: PackedByteArray = _attachment.get("bytes", PackedByteArray())
	var error := int(_drafts.write_attachment(_scope, "chat.image", bytes, str(_attachment.get("mime", ""))))
	_attachment_save_failed = error != OK


func _show_image_restore_error() -> void:
	%ImageStatus.text = "上次未发送的图片无法恢复。"
	%ImageStatus.show()
	_session.set_image_selecting(false)


func _exit_tree() -> void:
	flush_drafts()
	files.cancel()

func _update_density() -> void:
	var compact := size.x < 520
	_latest.text = "最新" if compact else "回到最新"
	_latest.tooltip_text = "回到最新消息"
	_unread.text = "未读" if compact else "定位未读"
	_unread.tooltip_text = "定位未读消息"
	if is_instance_valid(%Hint):
		%Hint.text = "Enter 发送" if compact else "Enter 发送 · Shift+Enter 换行"

func _update_history_status(state: Dictionary) -> void:
	var history: Dictionary = state.get("history",{"phase":"idle","count":0})
	_scroll.set_older_state(str(history.get("older","idle")))
	var storage_broken: bool = str(history.get("storage", "")) == "unavailable" or str(history.get("code", "")) in ["CACHE_CONFIG_FAILED", "CACHE_RESET_FAILED", "STORAGE_UNAVAILABLE"]
	var resetting: bool = str(history.get("storage", "")) == "resetting"
	_apply_history_buttons(history, storage_broken, resetting)
	_history_status.text = _history_status_text(history, storage_broken, resetting)
	_announce_history_phase(history)
	_apply_reading()
	_sync_history_banner(str(history.phase))


func _apply_history_buttons(history: Dictionary, storage_broken: bool, resetting: bool) -> void:
	_history_retry.visible = history.phase in ["first_failed","failed"] and not storage_broken and not resetting
	_history_skip.visible = history.phase == "first_failed" and not storage_broken and not resetting
	_history_reset.visible = storage_broken and not resetting


func _history_status_text(history: Dictionary, storage_broken: bool, resetting: bool) -> String:
	if resetting:
		return "正在重建本地缓存…"
	if storage_broken:
		return "本地聊天缓存异常（%s），可尝试重建本地缓存。" % str(history.get("code", "STORAGE_UNAVAILABLE"))
	return {"first_loading":"正在同步最近聊天记录…", "first_failed":"", "loading":"", "failed":"", "skipped":"已跳过历史同步。"}.get(history.phase, "")


func _announce_history_phase(history: Dictionary) -> void:
	if history.phase != _last_history_phase:
		_last_history_phase = str(history.phase)
		if history.phase == "first_failed":
			ErrorDialog.present(self, "首批历史加载失败，可重试或跳过。")
		elif history.phase == "failed":
			ToastOverlay.present_in(self, "较早历史加载失败，已加载内容保留。", "warning", 3.5, _ui_style)
	if history.get("incomplete",false) and not _history_incomplete_announced:
		_history_incomplete_announced = true
		ToastOverlay.present_in(self, "部分历史可能缺失。", "warning", 3.5, _ui_style)


func _sync_history_banner(phase: String) -> void:
	var shown := not _history_status.text.is_empty() or _history_retry.visible or _history_skip.visible or _history_reset.visible
	%HistoryRow.visible = shown
	%HistoryBanner.visible = shown
	if shown:
		var kind := "info" if phase in ["first_loading", "loading"] else "muted"
		StatusBanner.apply_surface_status(%HistoryBanner, _history_status, kind, _ui_style)


func _confirm_reset_history() -> void:
	var dialog = DecisionDialog.instantiate()
	dialog.title = "重建本地历史"
	dialog.dialog_text = "将备份当前本地库并重新同步服务端历史。未发送消息不会自动重发，可在 recovery 备份中恢复。"
	dialog.ok_button_text = "重建"
	dialog.destructive_action = true
	dialog.confirmed.connect(func(): _session.reset_history_storage())
	dialog.confirmed.connect(dialog.queue_free)
	dialog.canceled.connect(dialog.queue_free)
	add_child(dialog)
	dialog.popup_centered()

func _announce_chat_code(code: String) -> void:
	if code == "":
		_last_error_code = ""
		return
	if code == _last_error_code:
		return
	_last_error_code = code
	var text: String = {
		"REMOTE_AUDIO_ERROR":"语音生成失败，可继续文字聊天。",
		"AUDIO_ERROR":"这条语音无法播放。",
		"CACHE_CLEAR_FAILED":"部分语音文件被占用，关闭后重试。",
		"SEND_REJECTED":"消息未发送，内容已保留。",
		"INVALID_RESPONSE":"服务器响应异常，请稍后重试。",
		"SAVE_FAILED":"",
	}.get(code, "服务器暂时无法处理，请稍后重试。")
	if text.is_empty():
		return
	ErrorDialog.present(self, text)

func _announce_message_failures(messages: Array[Dictionary]) -> void:
	for message in messages:
		var id := str(message.get("id", ""))
		if id.is_empty() or _announced_messages.has(id):
			continue
		var status := str(message.get("status", ""))
		if status == "failed":
			_announced_messages[id] = true
			# 从本地库恢复的失败记录由气泡自身提示，不再每次启动弹阻塞框。
			if bool(message.get("restored", false)):
				continue
			if str(message.get("code", "")) == "DELIVERY_UNCERTAIN":
				ErrorDialog.present(self, "消息未确认送达，请刷新核实。")
			else:
				ErrorDialog.present(self, "发送失败")
