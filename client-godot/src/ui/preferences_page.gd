extends Control
## 相处偏好页：保存失败走错误弹窗；加载失败用不挡输入的浮层说明如何重试。
const ErrorDialog = preload("res://src/ui/error_dialog.gd")
var _controller: Node
var _fields: Dictionary = {}
var _selector_values: Dictionary = {}
@onready var _toast = %Toast
@onready var _load_banner = %LoadErrorBanner
var _initialized := false
var _refreshing := false
var _presets: Array[Button] = []
var _last_error_code := ""
var _ui_style: RefCounted

func setup(controller: Node) -> void:
	_controller = controller
	if is_node_ready() and _controller != null: _initialize()
func _ready() -> void:
	_apply_ui_style()
	if _controller == null:
		return
	_initialize()

func set_ui_style(ui_style: RefCounted) -> void:
	_ui_style = ui_style
	if is_node_ready():
		_apply_ui_style()

func _apply_ui_style() -> void:
	if _ui_style != null:
		_toast.set_ui_style(_ui_style)
		_load_banner.set_ui_style(_ui_style)

func _initialize() -> void:
	if _initialized: return
	_initialized = true
	add_child(_controller)
	_load_banner.action_pressed.connect(_controller.reload)
	var selectors := {"relationship":%RelationshipPresets,"speaking_style":%SpeakingStylePresets}
	var blocks := {"personality_text":%PersonalityField,"custom_context":%CustomContextField}
	for pair in [["relationship","关系"],["speaking_style","表达风格"],["personality_text","性格关键词"],["custom_context","补充上下文"]]:
		if pair[0] in ["relationship","speaking_style"]:
			var presets = selectors[pair[0]]
			_presets.append(presets)
			var values: Dictionary = {"friend":"朋友","confidant":"知己","idol":"偶像","partner":"搭档","family":"家人"} if pair[0] == "relationship" else {"lively":"活泼可爱","gentle":"温柔可人","quiet":"文静恬淡"}
			var options: Array = []
			for id in values:
				options.append({"id":id,"label":values[id]})
			presets.set_items(options)
			presets.set_meta("field",pair[0])
			presets.set_meta("values",values)
			_selector_values[pair[0]] = ""
			presets.activated.connect(_on_preset_selected.bind(pair[0], values, presets))
		else:
			var input: TextEdit = blocks[pair[0]]
			_fields[pair[0]] = input
			input.text_changed.connect(_edit)
	_controller.changed.connect(_update)
	_update(_controller.get_state())

func is_dirty() -> bool:
	return _controller != null and _controller.get_state().dirty

func is_data_settled() -> bool:
	return _controller != null and _controller.get_state().phase not in ["idle","loading"]

## 页面重新可见时给加载失败一次机会，浮层文案里的「重新打开设置可重试」才成立。
func retry_if_failed() -> void:
	if _controller != null and _controller.get_state().phase == "error":
		_controller.reload()

func _edit() -> void:
	if _refreshing:
		return
	var fields := {}
	for key in _fields:
		fields[key] = _fields[key].text
	for key in _selector_values:
		fields[key] = _selector_values[key]
	_controller.edit(fields)

func _update(state: Dictionary) -> void:
	_refreshing = true
	for key in _fields: _apply_field(key, state)
	for key in _selector_values:
		_selector_values[key] = state.fields.get(key, "")
	_refreshing = false
	_update_presets(state)
	_update_notice(state)

func _apply_field(key: String, state: Dictionary) -> void:
	var value: String = state.fields.get(key,"")
	if _fields[key].text != value:
		_fields[key].text = value
	_fields[key].editable = state.phase == "ready"

func _update_notice(state: Dictionary) -> void:
	_toast.clear()
	if state.phase == "error":
		push_warning("Preferences failed to load")
		_load_banner.set_status("相处偏好加载失败，可点击重试或重新打开设置。", "error", "重试加载")
		_toast.show_kind("相处偏好加载失败，请重新打开设置重试。", "error", 3.5)
		return
	_load_banner.clear_status()
	if state.phase == "ready" and state.code != "OK":
		if state.code != _last_error_code:
			_last_error_code = state.code
			ErrorDialog.present(self, "偏好保存失败，修改已保留。")
	else:
		_last_error_code = ""

func save_changes() -> Dictionary:
	if not is_dirty(): return {"ok":true,"results":[]}
	await _controller.save()
	var state: Dictionary = _controller.get_state()
	return {"ok":not state.dirty,"results":[{"section":"preferences","id":"相处模式","ok":not state.dirty,"code":state.code}]}

func _update_presets(state: Dictionary) -> void:
	for presets in _presets:
		presets.disabled = state.phase != "ready"
		var values: Dictionary = presets.get_meta("values")
		var value: String = _selector_values.get(presets.get_meta("field"), "")
		presets.clear_selection()
		for id in values:
			if values[id] == value: presets.set_selected_id(id)

func _on_preset_selected(id: String, field: String, values: Dictionary, presets: Button) -> void:
	presets.set_selected_id(id)
	_selector_values[field] = values.get(id, "")
	_edit()
