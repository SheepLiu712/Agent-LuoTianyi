extends Control
signal plaintext_answer(allowed: bool)
const Card = preload("res://scenes/ui/model_purpose_card.tscn")
var _settings: Node
var _executor: Node
var _types: Array = []
var _drafts: Dictionary = {}
var _cards: Dictionary = {}
var _initialized := false
var _testing := false
var _saving := false
var _test_snapshot: Dictionary = {}
var _test_type := ""
@onready var _status: Label = %Status
@onready var _plain: Window = %PlainDialog

func setup(settings: Node, executor: Node = null) -> void:
	_settings = settings
	_executor = executor
	if is_node_ready() and _settings != null: _initialize()

func _ready() -> void:
	%RefreshTypes.disabled = _settings == null
	if _settings != null: _initialize()

func _initialize() -> void:
	if _initialized: return
	_initialized = true
	_plain.confirmed.connect(func(): plaintext_answer.emit(true))
	_plain.canceled.connect(func(): plaintext_answer.emit(false))
	%TestDialog.confirmed.connect(_test)
	%TestDialog.canceled.connect(func(): _test_snapshot.clear())
	%RefreshTypes.pressed.connect(_reload)
	_settings.changed.connect(_update)
	_update(_settings.get_state())

func is_dirty() -> bool:
	for id in _drafts:
		if _drafts[id] != _as_draft(_settings.get_config(id)): return true
	return false

func _as_draft(config: Dictionary) -> Dictionary:
	var draft := config.duplicate(true)
	draft.params_text = JSON.stringify(config.get("params", {}), "  ")
	return draft

func _update(state: Dictionary) -> void:
	if _types.is_empty() and state.phase == "ready":
		_types = _settings.get_types()
		for purpose in _types:
			_drafts[purpose.id] = _as_draft(_settings.get_config(purpose.id))
			var card := Card.instantiate()
			card.setup(purpose, _drafts[purpose.id], _types, _executor != null)
			card.edited.connect(func(id, draft):
				_drafts[id] = draft
				_status.text = "有未保存的修改。"
				_set_editable())
			card.copy_requested.connect(_copy_config)
			card.test_requested.connect(_request_test)
			%Cards.add_child(card)
			_cards[purpose.id] = card
	if state.phase != "ready":
		_status.text = "正在获取模型用途…" if state.phase == "loading" else "无法读取模型用途（%s），请刷新重试。" % state.code
	elif state.code not in ["OK", ""]:
		_status.text = "部分配置未能恢复或不满足用途要求（%s）。" % state.code
	_set_editable()

func _set_editable() -> void:
	var ready: bool = _settings != null and _settings.get_state().phase == "ready" and not _testing and not _saving
	for card in _cards.values(): card.set_editable(ready)
	%RefreshTypes.disabled = _settings == null or _settings.get_state().phase == "loading" or _testing or _saving or is_dirty()

func _reload() -> void:
	if is_dirty() or _testing or _saving: return
	for card in _cards.values():
		%Cards.remove_child(card)
		card.queue_free()
	_cards.clear()
	_types.clear()
	_drafts.clear()
	await _settings.reload()

func _locate_error(id: String, code: String) -> void:
	if _cards.has(id):
		_cards[id].show_error("未保存：" + code)
		_reveal_error_card.call_deferred(_cards[id])

func _reveal_error_card(card: Control) -> void:
	if is_instance_valid(card) and %Scroll.is_ancestor_of(card):
		%Scroll.ensure_control_visible(card)

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
			_locate_error(id, result.code)
	return {"ok":failures.is_empty(),"results":failures}

func save_changes() -> Dictionary:
	var validation := validate_changes()
	if not validation.ok: return validation
	_saving = true
	_set_editable()
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
		if result.ok:
			_drafts[id] = _as_draft(config)
			_cards[id].set_draft(_drafts[id])
			_cards[id].show_error("")
		else:
			all_ok = false
			_locate_error(id, result.code)
		results.append({"section":"models","id":id,"ok":result.ok,"code":result.code})
	_saving = false
	_set_editable()
	return {"ok":all_ok,"results":results}


func _copy_config(id: String, source_id: String) -> void:
	if not _drafts.has(source_id): return
	_drafts[id] = _settings.copy_config(_drafts[source_id], id)
	_cards[id].set_draft(_drafts[id])
	_status.text = "已复制为草稿；保存时按目标用途重新校验。"
	_set_editable()

func _request_test(id: String, draft: Dictionary) -> void:
	if _testing or _saving: return
	var parser := JSON.new()
	if parser.parse(draft.get("params_text", "")) != OK or not parser.data is Dictionary:
		_locate_error(id, "INVALID_JSON")
		return
	_test_snapshot = draft.duplicate(true)
	_test_snapshot.params = parser.data
	_test_snapshot.erase("params_text")
	_test_type = id
	%TestDialog.popup_centered()

func _test() -> void:
	if _testing or _executor == null: return
	_testing = true
	_set_editable()
	_status.text = "正在测试…"
	var result: Dictionary = await _executor.test_config(_test_type, _test_snapshot)
	_test_snapshot.clear()
	_testing = false
	_set_editable()
	_status.text = "本次请求成功；不代表已全面认证模型能力。" if result.ok else "测试失败（%s）。" % result.code
