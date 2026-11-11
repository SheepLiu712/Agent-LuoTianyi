extends Window
@export var window_system: Resource = preload("res://src/platform/window_system.gd").new()
const StorageService = preload("res://src/storage/storage_service.gd")
const ErrorDialog = preload("res://src/ui/error_dialog.gd")
const SettingsStyle = preload("res://src/ui/settings_style.gd")
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
var _current_page_key := ""
var _scroll_tween: Tween
@onready var _preferences_page = %PreferencesPage
@onready var _model_page = %ModelPage
@onready var _profile_page = %ProfilePage
@onready var _toast = %SaveToast
@onready var _content_scroll: ScrollContainer = %Content

## 头像源和动态窗口共用同一份账号态，所以设置窗只转交，不自己持有纹理。
func set_avatar_source(source: Node) -> void:
	_avatar_source = source
	if is_node_ready(): _profile_page.set_avatar_source(source)


## Python 媒体导入是会话级服务，页面只拿到端口对象。
func set_media_migration(migration: Object) -> void:
	_media_migration = migration
	if is_node_ready():
		%AudioPage.set_media_migration(migration)


## 兼容旧装配入口：页面语义已扩展到语音与图片。
func set_audio_migration(migration: Object) -> void:
	set_media_migration(migration)

## 显示前注入 UI 样式：偏好页 setup 时即读取，脏标记与保存并入统一汇总。
func set_ui_style(ui_style: RefCounted) -> void:
	_ui_style = ui_style
	if is_node_ready() and _ui_style != null:
		%StylePage.set_ui_style(_ui_style)
		%SaveToast.set_ui_style(_ui_style)
		%PreferencesPage.set_ui_style(_ui_style)

func setup(
	preferences: Node,
	models: Node,
	executor: Node = null,
	clear_cache: Callable = Callable(),
	storage_service: StorageService = null,
	cache_directory: String = "",
	app_data_directory: String = ""
) -> void:
	_preferences = preferences
	_models = models
	_executor = executor
	_clear_cache = clear_cache
	_storage_service = storage_service
	_cache_directory = cache_directory
	_app_data_directory = app_data_directory

func _ready() -> void:
	_profile_page.set_avatar_source(_avatar_source)
	_preferences_page.setup(_preferences)
	_model_page.setup(_models,_executor)
	if _ui_style != null:
		%StylePage.set_ui_style(_ui_style)
		%SaveToast.set_ui_style(_ui_style)
		%PreferencesPage.set_ui_style(_ui_style)
	%AudioPage.setup(_clear_cache, _storage_service, _cache_directory, _media_migration, _app_data_directory)
	%AudioTab.disabled = not _clear_cache.is_valid()
	%AudioTab.pressed.connect(func(): select_page("audio"))
	%StyleTab.disabled = _ui_style == null
	%StyleTab.pressed.connect(func(): select_page("style"))
	%ProfileTab.pressed.connect(func(): select_page("profile"))
	%PreferencesTab.disabled = _preferences == null
	%ModelsTab.disabled = _models == null
	%PreferencesTab.pressed.connect(func(): select_page("preferences"))
	%ModelsTab.pressed.connect(func(): select_page("models"))
	%SaveAll.pressed.connect(save_changes)
	%CloseSettings.pressed.connect(func(): close_requested.emit())
	%LogoutButton.pressed.connect(func(): logout_requested.emit())
	close_requested.connect(_request_close)
	%UnsavedDialog.confirmed.connect(queue_free)
	%UnsavedDialog.custom_action.connect(func(action):
		if action == "save":
			%UnsavedDialog.hide()
			_close_after_save = true
			save_changes())
	_content_scroll.get_v_scroll_bar().value_changed.connect(_on_settings_scroll)
	select_page("profile")
	SettingsStyle.apply(self)

func select_page(page: String) -> void:
	var pages: Dictionary = {"profile":_profile_page,"preferences":_preferences_page,"models":_model_page,"audio":%AudioPage,"style":%StylePage}
	if not pages.has(page):
		return
	_current_page_key = page
	_update_tabs(page)
	_scroll_to_section(pages[page])
	# 偏好页把「重新打开设置可重试」写进了浮层，重新进入这一页就该真的重试一次。
	if _preferences_page != null and page == "preferences":
		_preferences_page.retry_if_failed()


func _update_tabs(page: String) -> void:
	var tabs: Dictionary = {"profile":%ProfileTab,"preferences":%PreferencesTab,"models":%ModelsTab,"audio":%AudioTab,"style":%StyleTab}
	for key: String in tabs:
		var tab: Button = tabs[key]
		var selected := key == page
		if tab.button_pressed != selected:
			tab.button_pressed = selected


func _scroll_to_section(target: Control) -> void:
	if not is_instance_valid(target) or not is_visible() or _content_scroll.size.y <= 0:
		return
	var bar := _content_scroll.get_v_scroll_bar()
	var max_scroll := maxi(0, int(bar.max_value - _content_scroll.size.y))
	var destination := clampi(int(target.position.y), 0, max_scroll)
	if _scroll_tween != null and _scroll_tween.is_valid():
		_scroll_tween.kill()
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
	%Chrome.open_window()

func _process(_delta: float) -> void:
	# 关闭后窗口仍被协调器缓存；隐藏状态下不要再逐帧深拷贝模型/偏好算脏。
	if not visible and not _hidden_by_main:
		return
	var dirty := is_dirty()
	%SaveAll.disabled = _saving or not dirty
	_clear_success_notice(dirty)
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
	%SaveAll.disabled = true
	%BusyBlocker.show()
	%BusyBlocker.grab_focus()
	_notify("正在保存全部修改…", "saving")
	var model_result: Dictionary = await _model_page.save_changes()
	var preference_result: Dictionary = await _preferences_page.save_changes()
	var ui_style_result := {"ok":true,"results":[]}
	if _ui_style != null: ui_style_result = await %StylePage.save_ui_style()
	var results: Array = model_result.results + preference_result.results + ui_style_result.results
	var ok: bool = model_result.ok and preference_result.ok and ui_style_result.ok
	_saving = false
	%SaveAll.disabled = false
	%BusyBlocker.hide()
	_report(results)
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

## 成功后用户又改动就撤掉提示；保存中 is_dirty() 恒为真，必须排除，否则会清掉常驻的「正在保存…」。
func _clear_success_notice(dirty: bool) -> void:
	if _notice_kind != "success" or not dirty or _saving:
		return
	_notify("", "")

## 保存反馈统一走顶部浮层：不再占用底栏，也不再把页面区压矮。
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
