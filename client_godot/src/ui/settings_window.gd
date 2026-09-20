extends Window
signal saving_finished(ok: bool)
var _preferences: Node
var _models: Node
var _executor: Node
var _saving := false
var _close_after_save := false
@onready var _preferences_page = %PreferencesPage
@onready var _model_page = %ModelPage

func setup(preferences: Node, models: Node, executor: Node = null) -> void:
	_preferences = preferences
	_models = models
	_executor = executor

func _ready() -> void:
	_preferences_page.setup(_preferences)
	_model_page.setup(_models,_executor)
	%PreferencesTab.disabled = _preferences == null
	%ModelsTab.disabled = _models == null
	%PreferencesTab.pressed.connect(func(): select_page("preferences"))
	%ModelsTab.pressed.connect(func(): select_page("models"))
	%SaveAll.pressed.connect(save_changes)
	%CloseSettings.pressed.connect(func(): close_requested.emit())
	close_requested.connect(_request_close)
	%UnsavedDialog.confirmed.connect(queue_free)
	%UnsavedDialog.custom_action.connect(func(action):
		if action == "save":
			%UnsavedDialog.hide()
			_close_after_save = true
			save_changes())
	select_page("preferences" if _preferences != null else "models")

func select_page(page: String) -> void:
	_preferences_page.visible = page == "preferences"
	_model_page.visible = page == "models"
	%PreferencesTab.button_pressed = page == "preferences"
	%ModelsTab.button_pressed = page == "models"

func open() -> void:
	%Chrome.open_window()

func is_dirty() -> bool:
	return _saving or _preferences_page.is_dirty() or _model_page.is_dirty()

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
	%Result.text = "正在保存全部修改…"
	var model_result: Dictionary = await _model_page.save_changes()
	var preference_result: Dictionary = await _preferences_page.save_changes()
	var results: Array = model_result.results + preference_result.results
	var ok: bool = model_result.ok and preference_result.ok
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
		else: errors.append("%s：%s" % [result.id,result.code])
	%Result.text = "全部修改已保存。" if errors.is_empty() else "已保存 %s 项；未保存：%s。草稿已保留。" % [successes,"；".join(errors)]

func _input(event: InputEvent) -> void:
	if _saving and event is InputEventKey:
		get_viewport().set_input_as_handled()
