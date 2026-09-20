extends "res://src/ui/draft_window.gd"
var _controller: Node
var _fields: Dictionary = {}
@onready var _status: Label = %Status
@onready var _save: Button = %Save
@onready var _reload: Button = %Reload
var _refreshing := false
var _presets: Array[Button] = []
func setup(controller: Node) -> void:
	_controller = controller
func _ready() -> void:
	super._ready()
	if _controller == null:
		return
	add_child(_controller)
	var lines := {"relationship":%RelationshipField,"speaking_style":%SpeakingStyleField}
	var selectors := {"relationship":%RelationshipPresets,"speaking_style":%SpeakingStylePresets}
	var blocks := {"personality_text":%PersonalityField,"custom_context":%CustomContextField}
	for pair in [["relationship","关系"],["speaking_style","表达风格"],["personality_text","性格关键词"],["custom_context","补充上下文"]]:
		if pair[0] in ["relationship","speaking_style"]:
			var input: LineEdit = lines[pair[0]]
			_fields[pair[0]] = input
			input.text_changed.connect(func(_text): _edit())
			var presets = selectors[pair[0]]
			_presets.append(presets)
			var values: Dictionary = {"friend":"朋友","confidant":"知己","idol":"偶像","partner":"搭档","family":"家人"} if pair[0] == "relationship" else {"lively":"活泼可爱","gentle":"温柔可人","quiet":"文静恬淡"}
			var options: Array = [{"id":"custom","label":"自定义"}]
			for id in values:
				options.append({"id":id,"label":values[id]})
			presets.set_items(options)
			presets.set_meta("field",pair[0])
			presets.set_meta("values",values)
			presets.activated.connect(func(id):
				if id != "custom":
					input.text = values[id]
					_edit())
		else:
			var input: TextEdit = blocks[pair[0]]
			_fields[pair[0]] = input
			input.text_changed.connect(_edit)
	_reload.pressed.connect(_controller.reload)
	_save.pressed.connect(_controller.save)
	_controller.changed.connect(_update)
	_update(_controller.get_state())
func is_dirty() -> bool:
	return _controller.get_state().dirty
func _edit() -> void:
	if _refreshing:
		return
	var fields := {}
	for key in _fields:
		fields[key] = _fields[key].text
	_controller.edit(fields)
func _update(state: Dictionary) -> void:
	_refreshing = true
	for key in _fields:
		var value: String = state.fields.get(key,"")
		if _fields[key].text != value:
			_fields[key].text = value
		_fields[key].editable = state.phase == "ready"
	_refreshing = false
	for presets in _presets:
		presets.disabled = state.phase != "ready"
		var values: Dictionary = presets.get_meta("values")
		var value: String = _fields[presets.get_meta("field")].text
		presets.set_selected_id("custom")
		for id in values:
			if values[id] == value: presets.set_selected_id(id)
	_save.disabled = not state.can_save
	_reload.disabled = state.phase in ["loading","saving"] or state.dirty
	_status.text = {"idle":"", "loading":"正在读取相处偏好…", "saving":"正在合并服务器最新设置并保存…", "error":"加载失败，请重试。加载成功前不能保存。", "ready":"有未保存的修改。" if state.dirty else "已从服务器读取。"}.get(state.phase,"")
	if state.phase == "ready" and state.code != "OK":
		_status.text = "保存失败，输入已保留（%s）。"%state.code
