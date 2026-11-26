extends Window
@export var window_system: Resource = preload("res://src/platform/window_system.gd").new()
const StorageService = preload("res://src/storage/storage_service.gd")
const ReleaseInfo = preload("res://src/storage/release_info.gd")
const ErrorDialog = preload("res://src/ui/error_dialog.gd")
const UiMotion = preload("res://src/ui/ui_motion.gd")
const SIDEBAR_TOGGLE_ICON := preload("res://assets/ui/icons/ui_sidebar_toggle.svg")
const SIDEBAR_EXPAND_ICON := preload("res://assets/ui/icons/ui_sidebar_expand.svg")
const INK_ACTIVE := Color("1278ad")
const INK_NORMAL := Color("3f5563")
const INK_DISABLED := Color("9aaab5")
## 保存中要一直看得见，成功短留、失败留久一点；负数代表常驻。
const NOTICE_SECONDS := {"saving": -1.0, "success": 2.0, "error": 8.0}
const DEFAULT_NOTICE_SECONDS := 2.0
const PAGE_ORDER := ["profile", "preferences", "models", "audio", "style"]
const SCROLL_TRANSITION_SECONDS := 0.18
signal saving_finished(ok: bool)
signal logout_requested
var _preferences: Node
var _models: Node
var _executor: Node
var _clear_cache: Callable
var _storage_service: StorageService
var _cache_directory := ""
var _app_data_directory := ""
var _saving := false
var _close_after_save := false
var _hidden_by_main := false
var _notice_kind := ""
var _ui_style: RefCounted
var _avatar_source: Node
var _media_migration: Object
var _settings_store: Resource
var _scope := ""
var _current_page_key := ""
var _scroll_tween: Tween
var _sidebar_compact := false
var _full_version := "AgentLuo v0.2.0.2"
var _mini_version := "v0.2"
@onready var _preferences_page = %PreferencesPage
@onready var _model_page = %ModelPage
@onready var _profile_page = %ProfilePage
@onready var _toast = %SaveToast
@onready var _content_scroll: ScrollContainer = %Content


func set_avatar_source(source: Node) -> void:
	_avatar_source = source
	if is_node_ready(): _profile_page.set_avatar_source(source)


func set_media_migration(migration: Object) -> void:
	_media_migration = migration
	if is_node_ready():
		%AudioPage.set_media_migration(migration)


func set_audio_migration(migration: Object) -> void:
	set_media_migration(migration)


func set_ui_style(ui_style: RefCounted) -> void:
	_ui_style = ui_style
	if is_node_ready() and _ui_style != null:
		_forward_ui_style()


func _forward_ui_style() -> void:
	for node in [%StylePage, %SaveToast, %PreferencesPage, %ModelPage, %AudioPage, %ProfilePage]:
		if node != null and node.has_method("set_ui_style"):
			node.set_ui_style(_ui_style)


func setup(
	preferences: Node,
	models: Node,
	executor: Node = null,
	clear_cache: Callable = Callable(),
	storage_service: StorageService = null,
	cache_directory: String = "",
	app_data_directory: String = "",
	settings_store: Resource = null,
	scope: String = ""
) -> void:
	_preferences = preferences
	_models = models
	_executor = executor
	_clear_cache = clear_cache
	_storage_service = storage_service
	_cache_directory = cache_directory
	_app_data_directory = app_data_directory
	_settings_store = settings_store
	_scope = scope


func _ready() -> void:
	_init_version_labels()
	_profile_page.set_avatar_source(_avatar_source)
	_profile_page.logout_requested.connect(func(): logout_requested.emit())
	_preferences_page.setup(_preferences)
	_model_page.setup(_models, _executor)
	if _ui_style != null:
		_forward_ui_style()
	%AudioPage.setup(_clear_cache, _storage_service, _cache_directory, _media_migration, _app_data_directory, _settings_store, _scope)
	%AudioTab.disabled = not _clear_cache.is_valid()
	%AudioTab.pressed.connect(func(): select_page("audio"))
	%StyleTab.disabled = _ui_style == null
	%StyleTab.pressed.connect(func(): select_page("style"))
	%ProfileTab.pressed.connect(func(): select_page("profile"))
	%PreferencesTab.disabled = _preferences == null
	%ModelsTab.disabled = _models == null
	%PreferencesTab.pressed.connect(func(): select_page("preferences"))
	%ModelsTab.pressed.connect(func(): select_page("models"))
	%SidebarToggle.pressed.connect(func(): set_sidebar_compact(not _sidebar_compact))
	%SaveAll.pressed.connect(save_changes)
	%DiscardAll.pressed.connect(_discard_all)
	%CloseSettings.pressed.connect(func(): close_requested.emit())
	close_requested.connect(_request_close)
	%UnsavedDialog.confirmed.connect(queue_free)
	%UnsavedDialog.custom_action.connect(func(action):
		if action == "save":
			%UnsavedDialog.hide()
			_close_after_save = true
			save_changes())
	_content_scroll.get_v_scroll_bar().value_changed.connect(_on_settings_scroll)
	_preferences_page.dirty_changed.connect(_sync_dirty_state)
	_model_page.dirty_changed.connect(_sync_dirty_state)
	%StylePage.dirty_changed.connect(_sync_dirty_state)
	UiMotion.bind_interactive_cursors(self)
	UiMotion.bind_tactile_press(%SaveAll, func(): return _ui_style)
	set_sidebar_compact(false)
	_sync_dirty_state()
	select_page("profile")


func _init_version_labels() -> void:
	var ver := str(ReleaseInfo.get_info().get("version", "0.2.0.2"))
	_full_version = "AgentLuo v" + ver
	var parts := ver.split(".")
	_mini_version = "v" + ".".join(parts.slice(0, mini(2, parts.size())))
	%VersionLabel.text = _full_version


func set_sidebar_compact(compact: bool) -> void:
	_sidebar_compact = compact
	if not is_node_ready():
		return
	%Sidebar.custom_minimum_size.x = 64.0 if compact else 208.0
	var margin_x := 10 if compact else 12
	%SidebarMargin.add_theme_constant_override("margin_left", margin_x)
	%SidebarMargin.add_theme_constant_override("margin_right", margin_x)
	%SidebarTitle.visible = not compact
	%SidebarTitlePad.visible = not compact
	%SidebarToggle.icon = SIDEBAR_EXPAND_ICON if compact else SIDEBAR_TOGGLE_ICON
	%VersionMargin.add_theme_constant_override("margin_left", 0 if compact else 10)
	%VersionMargin.add_theme_constant_override("margin_right", 0 if compact else 10)
	%VersionLabel.text = _mini_version if compact else _full_version
	%VersionLabel.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER if compact else HORIZONTAL_ALIGNMENT_LEFT
	for tab in _all_tabs().values():
		_apply_tab_compact_state(tab, compact)


func _apply_tab_compact_state(tab: Button, compact: bool) -> void:
	tab.custom_minimum_size = Vector2(42, 42) if compact else Vector2(0, 38)
	tab.size_flags_horizontal = Control.SIZE_SHRINK_CENTER if compact else Control.SIZE_FILL
	var row := tab.get_node("Row") as HBoxContainer
	row.alignment = BoxContainer.ALIGNMENT_CENTER if compact else BoxContainer.ALIGNMENT_BEGIN
	row.offset_left = 0.0 if compact else 10.0
	row.offset_right = 0.0 if compact else -10.0
	(row.get_node("Text") as Label).visible = not compact
	var dot := tab.get_node("DirtyDot") as Control
	if compact:
		dot.set_anchors_preset(Control.PRESET_TOP_RIGHT)
		dot.offset_left = -13.0
		dot.offset_right = -6.0
		dot.offset_top = 6.0
		dot.offset_bottom = 13.0
	else:
		dot.set_anchors_preset(Control.PRESET_CENTER_RIGHT)
		dot.offset_left = -17.0
		dot.offset_right = -10.0
		dot.offset_top = -3.5
		dot.offset_bottom = 3.5


func _all_tabs() -> Dictionary:
	return {"profile":%ProfileTab, "preferences":%PreferencesTab, "models":%ModelsTab, "audio":%AudioTab, "style":%StyleTab}


func select_page(page: String) -> void:
	var pages: Dictionary = {"profile":_profile_page,"preferences":_preferences_page,"models":_model_page,"audio":%AudioPage,"style":%StylePage}
	if not pages.has(page):
		return
	_current_page_key = page
	_update_tabs(page)
	_scroll_to_section(pages[page])
	if _preferences_page != null and page == "preferences":
		_preferences_page.retry_if_failed()


func _update_tabs(page: String) -> void:
	var tabs := _all_tabs()
	for key: String in tabs:
		var tab: Button = tabs[key]
		var selected := key == page
		if tab.button_pressed != selected:
			tab.button_pressed = selected
		var tint := INK_DISABLED if tab.disabled else (INK_ACTIVE if selected else INK_NORMAL)
		var row := tab.get_node("Row")
		(row.get_node("Icon") as TextureRect).modulate = tint
		(row.get_node("Text") as Label).add_theme_color_override("font_color", tint)


func _scroll_to_section(target: Control) -> void:
	if not is_instance_valid(target) or not is_visible() or _content_scroll.size.y <= 0:
		return
	var bar := _content_scroll.get_v_scroll_bar()
	var max_scroll := maxi(0, int(bar.max_value - _content_scroll.size.y))
	var destination := clampi(int(target.position.y), 0, max_scroll)
	if _scroll_tween != null and _scroll_tween.is_valid():
		_scroll_tween.kill()
		_scroll_tween = null
	if UiMotion.should_reduce_motion(_ui_style):
		_content_scroll.scroll_vertical = destination
		return
	_scroll_tween = create_tween()
	_scroll_tween.set_trans(Tween.TRANS_CUBIC).set_ease(Tween.EASE_OUT)
	_scroll_tween.tween_method(
		func(value: float): _content_scroll.scroll_vertical = int(value),
		float(_content_scroll.scroll_vertical),
		float(destination),
		SCROLL_TRANSITION_SECONDS
	)
	_scroll_tween.finished.connect(func(): _scroll_tween = null, CONNECT_ONE_SHOT)


func _on_settings_scroll(value: float) -> void:
	if _scroll_tween != null and _scroll_tween.is_valid():
		return
	var pages: Dictionary = {"profile":_profile_page,"preferences":_preferences_page,"models":_model_page,"audio":%AudioPage,"style":%StylePage}
	var bar := _content_scroll.get_v_scroll_bar()
	var threshold := value + 72.0
	var active := PAGE_ORDER[0]
	for key in PAGE_ORDER:
		var page: Control = pages[key]
		if page.position.y <= threshold:
			active = key
		else:
			break
	if value >= bar.max_value - _content_scroll.size.y - 2.0:
		active = PAGE_ORDER.back()
	if active != _current_page_key:
		_current_page_key = active
		_update_tabs(active)


func open() -> void:
	_hidden_by_main = false
	_sync_dirty_state()
	%Chrome.open_window()


func _dirty_sections() -> Dictionary:
	return {
		"preferences": _preferences_page.is_dirty(),
		"models": _model_page.is_dirty(),
		"style": _ui_style != null and %StylePage.ui_style_dirty(),
	}


func _dirty_labels(section_dirty: Dictionary) -> Array[String]:
	var labels: Array[String] = []
	var mapping := [["preferences", "相处模式"], ["models", "模型配置"], ["style", "风格外观"]]
	for item in mapping:
		if bool(section_dirty.get(item[0], false)):
			labels.append(item[1])
	return labels


func _can_sync_dirty_state() -> bool:
	return is_node_ready() and is_inside_tree() and not is_queued_for_deletion() and get_node_or_null("%StylePage") != null and get_node_or_null("%ProfileTab") != null


func _sync_dirty_state() -> void:
	if not _can_sync_dirty_state():
		return
	var section_dirty := _dirty_sections()
	var tabs := _all_tabs()
	for key in ["preferences", "models", "style"]:
		(tabs[key].get_node("DirtyDot") as Control).visible = bool(section_dirty.get(key, false))
	var dirty_labels := _dirty_labels(section_dirty)
	var dirty := _saving or not dirty_labels.is_empty()
	%UnsavedBarWrap.visible = dirty
	%CloseBar.visible = not dirty
	%SaveAll.disabled = _saving or dirty_labels.is_empty()
	%DiscardAll.disabled = _saving or dirty_labels.is_empty()
	%UnsavedSummary.text = "正在保存修改…" if _saving else ("%d 项修改未保存 · %s" % [dirty_labels.size(), "、".join(dirty_labels)] if not dirty_labels.is_empty() else "")
	_clear_success_notice(dirty)


func _discard_all() -> void:
	if _saving:
		return
	_preferences_page.discard_changes()
	_model_page.discard_changes()
	if _ui_style != null:
		%StylePage.discard_ui_style()
	_sync_dirty_state()


func _process(_delta: float) -> void:
	if not visible and not _hidden_by_main:
		return
	if window_system.minimized(get_tree().root):
		if visible and not window_system.minimized(self):
			_hidden_by_main = true
			hide()
	elif _hidden_by_main:
		_hidden_by_main = false
		show()


func is_dirty() -> bool:
	if _saving or _preferences_page.is_dirty() or _model_page.is_dirty(): return true
	return _ui_style != null and %StylePage.ui_style_dirty()


func is_saving() -> bool:
	return _saving


func is_data_settled() -> bool:
	return _preferences_page.is_data_settled() and _model_page.is_data_settled()


func _request_close() -> void:
	if _saving:
		_close_after_save = true
	elif is_dirty():
		%UnsavedDialog.popup_centered()
		%UnsavedDialog.get_cancel_button().grab_focus()
	else:
		hide()


func save_changes() -> Dictionary:
	if _saving: return {"ok":false,"results":[{"section":"settings","id":"设置","code":"BUSY","ok":false}]}
	var validation: Dictionary = _model_page.validate_changes()
	if not validation.ok:
		_close_after_save = false
		select_page("models")
		_report(validation.results)
		return validation
	_saving = true
	_sync_dirty_state()
	%BusyBlocker.show()
	%BusyBlocker.grab_focus()
	_notify("正在保存全部修改…", "saving")
	var model_result: Dictionary = await _model_page.save_changes(validation)
	var preference_result: Dictionary = await _preferences_page.save_changes()
	var ui_style_result := {"ok":true,"results":[]}
	if _ui_style != null: ui_style_result = await %StylePage.save_ui_style()
	var results: Array = model_result.results + preference_result.results + ui_style_result.results
	var ok: bool = model_result.ok and preference_result.ok and ui_style_result.ok
	_saving = false
	%BusyBlocker.hide()
	_report(results)
	_sync_dirty_state()
	var should_close := _close_after_save and ok and not is_dirty()
	_close_after_save = false
	saving_finished.emit(ok)
	if should_close: queue_free()
	return {"ok":ok,"results":results}


func _report(results: Array) -> void:
	var failures := 0
	var successes := 0
	var messages: Array[String] = []
	for result in results:
		if result.ok: successes += 1
		else:
			failures += 1
			if result.get("message") is String and not str(result.message).is_empty():
				messages.append(str(result.message))
	if failures == 0:
		_notify("全部修改已保存。", "success")
	else:
		_notify("", "")
		for text in messages:
			ErrorDialog.present(self, text)
		if messages.size() < failures:
			ErrorDialog.present(self, "已保存 %d 项；%d 项未保存，修改仍保留在本次会话。" % [successes, failures])


func _clear_success_notice(dirty: bool) -> void:
	if _notice_kind != "success" or not dirty or _saving:
		return
	_notify("", "")


func _notify(text: String, kind: String) -> void:
	_notice_kind = kind
	if text.is_empty():
		_toast.clear()
		return
	var visual: String = str({"success":"success", "error":"error", "saving":"progress"}.get(kind, "info"))
	_toast.show_kind(text, visual, float(NOTICE_SECONDS.get(kind, DEFAULT_NOTICE_SECONDS)))


func _input(event: InputEvent) -> void:
	if visible and event.is_action_pressed("ui_cancel"):
		get_viewport().set_input_as_handled()
		_request_close()
		return
	if _saving and event is InputEventKey:
		get_viewport().set_input_as_handled()
