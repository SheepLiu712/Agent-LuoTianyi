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
@onready var _purpose_title: Label = %PurposeTitle
@onready var _enabled: CheckBox = %Enabled
@onready var _requirements: Label = %Requirements
@onready var _description: Label = %Description
@onready var _fields_box: VBoxContainer = %Fields
@onready var _provider_input: LineEdit = %provider
@onready var _base_url_input: LineEdit = %base_url
@onready var _api_key_input: LineEdit = %api_key
@onready var _model_input: LineEdit = %ModelName
@onready var _json_check: CheckBox = %Json
@onready var _thinking_check: CheckBox = %Thinking
@onready var _params_edit: TextEdit = %Params
@onready var _copy_slot: Button = %CopySlot
@onready var _copy_button: Button = %CopyButton
@onready var _test_button: Button = %TestButton
@onready var _card_status: Label = %CardStatus


func setup(purpose: Dictionary, draft: Dictionary, purposes: Array, can_test: bool = false) -> void:
	_purpose = purpose
	_draft = draft.duplicate(true)
	_purposes = purposes
	_can_test = can_test

func _ready() -> void:
	_fields = {"provider":_provider_input,"base_url":_base_url_input,"api_key":_api_key_input,"model":_model_input}
	_purpose_title.text = _purpose.get("name", "模型用途")
	_requirements.text = "调用要求：%s%s%s" % [_purpose.get("model_kind", "llm").to_upper(), " / 需要 JSON" if _purpose.get("requires_json", false) else "", " / 需要 thinking" if _purpose.get("requires_thinking", false) else ""]
	_description.text = _purpose.get("description", "")
	var options: Array = []
	for purpose in _purposes: options.append({"id":purpose.id,"label":purpose.name})
	_copy_slot.set_items(options)
	set_draft(_draft)
	for field in _fields.values(): field.text_changed.connect(func(_text): _edit())
	_enabled.toggled.connect(func(value):
		_fields_box.visible = value
		_edit())
	_json_check.toggled.connect(func(_value): _edit())
	_thinking_check.toggled.connect(func(_value): _edit())
	_params_edit.text_changed.connect(_edit)
	_copy_button.pressed.connect(func(): copy_requested.emit(_purpose.id, _copy_slot.get_selected_id()))
	_test_button.visible = _can_test
	_test_button.pressed.connect(func(): test_requested.emit(_purpose.id, _draft.duplicate(true)))

func set_draft(draft: Dictionary) -> void:
	_draft = draft.duplicate(true)
	if not is_node_ready(): return
	_refreshing = true
	for key in _fields: _fields[key].text = _draft.get(key, "")
	_enabled.button_pressed = _draft.get("enabled", false)
	_fields_box.visible = _enabled.button_pressed
	_json_check.button_pressed = _draft.get("model_capabilities", {}).get("can_use_json", false)
	_thinking_check.button_pressed = _draft.get("model_capabilities", {}).get("can_enable_thinking", false)
	_params_edit.text = _draft.get("params_text", "{}")
	_refreshing = false

func set_editable(value: bool) -> void:
	_enabled.disabled = not value
	for field in _fields.values(): field.editable = value
	_params_edit.editable = value
	for control in [_json_check, _thinking_check, _copy_slot, _copy_button, _test_button]: control.disabled = not value

func show_error(text: String) -> void:
	_set_card_status(text)
	if not text.is_empty(): _fields_box.show()

func _edit() -> void:
	if _refreshing: return
	for key in _fields: _draft[key] = _fields[key].text
	_draft.enabled = _enabled.button_pressed
	_draft.model_capabilities = {"can_use_json":_json_check.button_pressed,"can_enable_thinking":_thinking_check.button_pressed}
	_draft.params_text = _params_edit.text
	_set_card_status("有未保存的修改。")
	edited.emit(_purpose.id, _draft.duplicate(true))

func _set_card_status(text: String) -> void:
	_card_status.text = text
	_card_status.visible = not text.is_empty()
