extends "res://src/ui/draft_window.gd"
var _settings: Node
var _types: Array = []
var _drafts := {}
var _current := ""
@onready var _selector = %SelectorSlot
@onready var _copy = %CopySlot
var _fields := {}
@onready var _enabled: CheckBox = %Enabled
@onready var _json: CheckBox = %Json
@onready var _thinking: CheckBox = %Thinking
@onready var _params: TextEdit = %Params
@onready var _status: Label = %Status
@onready var _requirements: Label = %Requirements
@onready var _save_button: Button = %SaveButton
@onready var _plain: ConfirmationDialog = %PlainDialog
var _refreshing := false
var _executor: Node
var _test_button: Button
var _test_dialog: ConfirmationDialog
var _test_snapshot := {}
var _test_type := ""

func setup(settings: Node,executor: Node = null) -> void:
	_settings = settings
	_executor = executor

func _ready() -> void:
	super._ready()
	_selector.activated.connect(func(index): _select(index))
	_enabled.toggled.connect(func(_value): _edit())
	_fields = {"provider":%provider,"base_url":%base_url,"api_key":%api_key,"model":%ModelName}
	for key in _fields:
		_fields[key].text_changed.connect(func(_value): _edit())
	for flag in [_json,_thinking]:
		flag.toggled.connect(func(_value): _edit())
	_params.text_changed.connect(_edit)
	%CopyButton.pressed.connect(_copy_selected)
	_save_button.pressed.connect(func(): _save(false))
	if _executor != null:
		_test_button = %TestButton
		_test_dialog = %TestDialog
		_test_button.pressed.connect(func():
			_test_snapshot = _config()
			_test_type = _current
			if not _test_snapshot.is_empty():
				_test_dialog.popup_centered()
				_test_dialog.get_cancel_button().grab_focus())
		_test_dialog.confirmed.connect(_test)
	else:
		%TestButton.visible = false
	_plain.confirmed.connect(func(): _save(true))
	if _settings == null:
		return
	_settings.changed.connect(_update)
	_update(_settings.get_state())

func is_dirty() -> bool:
	for id in _drafts:
		if _drafts[id] != _as_draft(_settings.get_config(id)):
			return true
	return false

func _as_draft(config: Dictionary) -> Dictionary:
	var draft := config.duplicate(true)
	draft.params_text = JSON.stringify(config.get("params",{}),"  ")
	return draft

func _update(state: Dictionary) -> void:
	_save_button.disabled = state.phase != "ready"
	if _types.is_empty() and state.phase == "ready":
		_types = _settings.get_types()
		var options: Array = []
		for type in _types:
			options.append({"id":type.id,"label":type.name})
			_drafts[type.id] = _as_draft(_settings.get_config(type.id))
		_selector.set_items(options)
		_copy.set_items(options)
		if not _types.is_empty():
			_select(_types[0].id)
	if state.phase != "ready":
		_status.text = "正在获取模型用途…" if state.phase == "loading" else "无法读取模型用途（%s），可关闭后重新打开。"%state.code
	elif state.code not in ["OK",""]:
		_status.text = "部分配置未能恢复或不再满足用途要求，请检查（%s）。"%state.code

func _select(id: String) -> void:
	_current = id
	_refreshing = true
	var draft: Dictionary = _drafts[_current]
	for key in _fields:
		_fields[key].text = draft.get(key,"")
	_enabled.button_pressed = draft.enabled
	_json.button_pressed = draft.model_capabilities.can_use_json
	_thinking.button_pressed = draft.model_capabilities.can_enable_thinking
	_params.text = draft.params_text
	var type: Dictionary = _types.filter(func(item): return item.id == id)[0]
	_requirements.text = "%s · %s\n要求：JSON %s / thinking %s"%[type.model_kind.to_upper(),type.description,"是" if type.requires_json else "否","是" if type.requires_thinking else "否"]
	_refreshing = false
	_status.text = "能力勾选是配置声明，不代表已完成全面认证。"

func _edit() -> void:
	if _refreshing or _current.is_empty():
		return
	var draft: Dictionary = _drafts[_current]
	for key in _fields:
		draft[key] = _fields[key].text
	draft.enabled = _enabled.button_pressed
	draft.model_capabilities = {"can_use_json":_json.button_pressed,"can_enable_thinking":_thinking.button_pressed}
	draft.params_text = _params.text
	_status.text = "有未保存的修改。"

func _config() -> Dictionary:
	var config: Dictionary = _drafts.get(_current,{}).duplicate(true)
	var parsed: Variant = JSON.parse_string(config.get("params_text",""))
	if not parsed is Dictionary:
		_status.text = "高级参数必须是有效 JSON 对象。"
		return {}
	config.erase("params_text")
	config.params = parsed
	return config

func _save(allow_plain: bool) -> void:
	var config := _config()
	if config.is_empty():
		return
	var result: Dictionary = _settings.save(_current,config,allow_plain)
	if result.ok:
		_drafts[_current] = _as_draft(config)
		_select(_selector.get_selected_id())
		_status.text = "已保存；后续委托使用新配置。"
	elif result.code == "PLAINTEXT_CONFIRMATION_REQUIRED":
		_plain.popup_centered()
		_plain.get_cancel_button().grab_focus()
	else:
		_status.text = "保存失败，草稿已保留（%s）。"%result.code

func _copy_selected() -> void:
	if _current.is_empty() or _copy.get_selected_id().is_empty():
		return
	var copied: Dictionary = _settings.copy_config(_drafts[_copy.get_selected_id()],_current)
	_drafts[_current] = copied
	_select(_selector.get_selected_id())
	_status.text = "已复制为草稿；保存时按目标用途重新校验。"

func _test() -> void:
	_test_button.disabled = true
	_status.text = "正在测试…"
	var result: Dictionary = await _executor.test_config(_test_type,_test_snapshot)
	_test_snapshot.clear()
	_test_button.disabled = false
	_status.text = "本次请求成功；不代表已全面认证模型能力。" if result.ok else "测试失败（%s）。"%result.code
