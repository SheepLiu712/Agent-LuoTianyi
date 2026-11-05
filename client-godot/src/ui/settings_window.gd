extends Window
@export var window_system: Resource = preload("res://src/platform/window_system.gd").new()
const StorageService = preload("res://src/storage/storage_service.gd")
signal saving_finished(ok: bool)
signal logout_requested
var _preferences: Node
var _models: Node
var _executor: Node
var _clear_cache: Callable
var _storage_service: StorageService
var _cache_directory := ""
var _saving := false
var _close_after_save := false
var _hidden_by_main := false
var _result_kind := ""
var _ui_style: RefCounted
@onready var _preferences_page = %PreferencesPage
@onready var _model_page = %ModelPage

## Inject the UI style service before the window is shown. Preferences page
## reads it during setup; dirty/save are folded into the shared summaries.
func set_ui_style(ui_style: RefCounted) -> void:
	_ui_style = ui_style
	if is_node_ready() and _ui_style != null: %StylePage.set_ui_style(_ui_style)

func setup(preferences: Node, models: Node, executor: Node = null, clear_cache: Callable = Callable(), storage_service: StorageService = null, cache_directory: String = "") -> void:
	_preferences = preferences
	_models = models
	_executor = executor
	_clear_cache = clear_cache
	_storage_service = storage_service
	_cache_directory = cache_directory

func _ready() -> void:
	_preferences_page.setup(_preferences)
	_model_page.setup(_models,_executor)
	if _ui_style != null: %StylePage.set_ui_style(_ui_style)
	%AudioPage.setup(_clear_cache, _storage_service, _cache_directory)
	%AudioTab.disabled = not _clear_cache.is_valid()
	%AudioTab.pressed.connect(func(): select_page("audio"))
	%StyleTab.disabled = _ui_style == null
	%StyleTab.pressed.connect(func(): select_page("style"))
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
	select_page("preferences" if _preferences != null or _ui_style != null else "models")

func select_page(page: String) -> void:
	_preferences_page.visible = page == "preferences"
	_model_page.visible = page == "models"
	%AudioPage.visible = page == "audio"
	%StylePage.visible = page == "style"
	%AudioTab.button_pressed = page == "audio"
	%StyleTab.button_pressed = page == "style"
	%PreferencesTab.button_pressed = page == "preferences"
	%ModelsTab.button_pressed = page == "models"

func open() -> void:
	_hidden_by_main = false
	%Chrome.open_window()

func _process(_delta: float) -> void:
	var dirty := is_dirty()
	%SaveAll.disabled = _saving or not dirty
	if _result_kind == "success" and dirty and not _saving: _set_result("", "")
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

func _request_close() -> void:
	if _saving:
		_close_after_save = true
	elif is_dirty():
		%UnsavedDialog.popup_centered()
		%UnsavedDialog.get_cancel_button().grab_focus()
	else:
		queue_free()

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
	_set_result("正在保存全部修改…", "saving")
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
	var errors: Array[String] = []
	var successes := 0
	for result in results:
		if result.ok: successes += 1
		else:
			var label: String = result.id
			if result.section == "models" and _models != null:
				for purpose in _models.get_types():
					if purpose.id == result.id: label = "模型配置 · " + purpose.name
			errors.append("%s：%s" % [label,result.code])
	_set_result("全部修改已保存。" if errors.is_empty() else "已保存 %s 项；未保存：%s。草稿已保留。" % [successes,"；".join(errors)], "success" if errors.is_empty() else "error")

func _set_result(text: String, kind: String) -> void:
	_result_kind = kind
	%Result.text = text
	%Result.visible = not text.is_empty()
	%ResultScroll.visible = %Result.visible

func _input(event: InputEvent) -> void:
	if _saving and event is InputEventKey:
		get_viewport().set_input_as_handled()
