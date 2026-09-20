extends Control
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
@onready var _plain: Window = %PlainDialog
signal plaintext_answer(allowed: bool)
var _initialized := false
var _refreshing := false
var _executor: Node
var _test_button: Button
var _test_dialog: Window
var _test_snapshot := {}
var _test_type := ""

func setup(settings: Node,executor: Node = null) -> void:
	_settings = settings
	_executor = executor
	if is_node_ready() and _settings != null: _initialize()

func _ready() -> void:
	%TestButton.visible = _executor != null
	if _settings != null: _initialize()

func _initialize() -> void:
	if _initialized: return
	_initialized = true
	%TestButton.visible = _executor != null
	_selector.activated.connect(func(index): _select(index))
	_enabled.toggled.connect(func(_value): _edit())
	_fields = {"provider":%provider,"base_url":%base_url,"api_key":%api_key,"model":%ModelName}
	for key in _fields:
		_fields[key].text_changed.connect(func(_value): _edit())
	for flag in [_json,_thinking]:
		flag.toggled.connect(func(_value): _edit())
	_params.text_changed.connect(_edit)
	%CopyButton.pressed.connect(_copy_selected)
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
	_plain.confirmed.connect(func(): plaintext_answer.emit(true))
	_plain.canceled.connect(func(): plaintext_answer.emit(false))
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
	var parser := JSON.new()
	var parsed: Variant = parser.data if parser.parse(config.get("params_text","")) == OK else null
	if not parsed is Dictionary:
		_status.text = "高级参数必须是有效 JSON 对象。"
		return {}
	config.erase("params_text")
	config.params = parsed
	return config

func validate_changes() -> Dictionary:
	var failures: Array = []
	for id in _drafts:
		if _drafts[id] == _as_draft(_settings.get_config(id)): continue
		var config: Dictionary = _drafts[id].duplicate(true)
		var parser := JSON.new()
		var parsed: Variant = parser.data if parser.parse(config.params_text) == OK else null
		var result := {"ok":false,"code":"INVALID_JSON"}
		if parsed is Dictionary:
			config.params = parsed
			config.erase("params_text")
			result = _settings.validate(id,config)
		if not result.ok:
			failures.append({"section":"models","id":id,"ok":false,"code":result.code})
	return {"ok":failures.is_empty(),"results":failures}

func save_changes() -> Dictionary:
	var validation := validate_changes()
	if not validation.ok: return validation
	var results: Array = []
	var all_ok := true
	for id in _drafts:
		if _drafts[id] == _as_draft(_settings.get_config(id)): continue
		var config: Dictionary = _drafts[id].duplicate(true)
		config.params = JSON.parse_string(config.params_text)
		config.erase("params_text")
		var result: Dictionary = _settings.save(id,config)
		if result.code == "PLAINTEXT_CONFIRMATION_REQUIRED":
			_plain.popup_centered()
			_plain.get_cancel_button().grab_focus()
			var allowed: bool = await plaintext_answer
			if allowed: result = _settings.save(id,config,true)
		if result.ok: _drafts[id] = _as_draft(config)
		else: all_ok = false
		results.append({"section":"models","id":id,"ok":result.ok,"code":result.code})
	return {"ok":all_ok,"results":results}

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
