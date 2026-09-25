extends PanelContainer
signal edited(id: String, draft: Dictionary)
signal copy_requested(id: String, source_id: String)
signal test_requested(id: String, draft: Dictionary)
var _purpose: Dictionary
var _draft: Dictionary
var _purposes: Array
var _can_test := false
var _fields: Dictionary
var _refreshing := false

func setup(purpose: Dictionary, draft: Dictionary, purposes: Array, can_test: bool = false) -> void:
	_purpose = purpose
	_draft = draft.duplicate(true)
	_purposes = purposes
	_can_test = can_test

func _ready() -> void:
	_fields = {"provider":%provider,"base_url":%base_url,"api_key":%api_key,"model":%ModelName}
	%PurposeTitle.text = _purpose.get("name", "模型用途")
	%Requirements.text = "调用要求：%s%s%s" % [_purpose.get("model_kind", "llm").to_upper(), " / 需要 JSON" if _purpose.get("requires_json", false) else "", " / 需要 thinking" if _purpose.get("requires_thinking", false) else ""]
	%Description.text = _purpose.get("description", "")
	var options: Array = []
	for purpose in _purposes: options.append({"id":purpose.id,"label":purpose.name})
	%CopySlot.set_items(options)
	set_draft(_draft)
	for field in _fields.values(): field.text_changed.connect(func(_text): _edit())
	%Enabled.toggled.connect(func(value):
		%Fields.visible = value
		_edit())
	%Json.toggled.connect(func(_value): _edit())
	%Thinking.toggled.connect(func(_value): _edit())
	%Params.text_changed.connect(_edit)
	%CopyButton.pressed.connect(func(): copy_requested.emit(_purpose.id, %CopySlot.get_selected_id()))
	%TestButton.visible = _can_test
	%TestButton.pressed.connect(func(): test_requested.emit(_purpose.id, _draft.duplicate(true)))

func set_draft(draft: Dictionary) -> void:
	_draft = draft.duplicate(true)
	if not is_node_ready(): return
	_refreshing = true
	for key in _fields: _fields[key].text = _draft.get(key, "")
	%Enabled.button_pressed = _draft.get("enabled", false)
	%Fields.visible = %Enabled.button_pressed
	%Json.button_pressed = _draft.get("model_capabilities", {}).get("can_use_json", false)
	%Thinking.button_pressed = _draft.get("model_capabilities", {}).get("can_enable_thinking", false)
	%Params.text = _draft.get("params_text", "{}")
	_refreshing = false

func set_editable(value: bool) -> void:
	%Enabled.disabled = not value
	for field in _fields.values(): field.editable = value
	%Params.editable = value
	for control in [%Json, %Thinking, %CopySlot, %CopyButton, %TestButton]: control.disabled = not value

func show_error(text: String) -> void:
	%CardStatus.text = text
	if not text.is_empty(): %Fields.show()

func _edit() -> void:
	if _refreshing: return
	for key in _fields: _draft[key] = _fields[key].text
	_draft.enabled = %Enabled.button_pressed
	_draft.model_capabilities = {"can_use_json":%Json.button_pressed,"can_enable_thinking":%Thinking.button_pressed}
	_draft.params_text = %Params.text
	%CardStatus.text = "有未保存的修改。"
	edited.emit(_purpose.id, _draft.duplicate(true))
