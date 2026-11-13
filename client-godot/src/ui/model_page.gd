extends Control
signal plaintext_answer(allowed: bool)
const Card = preload("res://scenes/ui/settings/model_purpose_card.tscn")
const ErrorDialog = preload("res://src/ui/error_dialog.gd")
const StatusBanner = preload("res://src/ui/status_banner.gd")
var _settings: Node
var _executor: Node
var _types: Array = []
var _drafts: Dictionary = {}
var _cards: Dictionary = {}
var _initialized := false
var _testing := false
var _last_error_code := ""
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

func is_data_settled() -> bool:
	if _settings == null: return true
	var state: Dictionary = _settings.get_state()
	if state.phase in ["idle","loading"]: return false
	if state.phase != "ready": return true
	return _cards.size() == _types.size()

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
		_set_status("正在获取模型用途…" if state.phase == "loading" else "", "info")
		if state.phase != "loading" and state.code != _last_error_code:
			_last_error_code = state.code
			ErrorDialog.present(self, "部分配置未能恢复，可刷新重试。")
	elif state.code not in ["OK", ""]:
		_set_status("", "muted")
		if state.code != _last_error_code:
			_last_error_code = state.code
			ErrorDialog.present(self, "部分配置未能恢复，可刷新重试。")
	else:
		_last_error_code = ""
	_set_editable()


func _set_status(text: String, kind: String) -> void:
	_status.text = text
	if not text.is_empty():
		StatusBanner.apply_surface_status(null, _status, kind)

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
		_cards[id].show_error("")
		ErrorDialog.present(self, "参数不是有效的 JSON，请检查后重试。" if code == "INVALID_JSON" else "未保存，请重试。")
		_reveal_error_card.call_deferred(_cards[id])

func _reveal_error_card(card: Control) -> void:
	if not is_instance_valid(card):
		return
	var scroll := _scroll_ancestor(card)
	if scroll != null:
		scroll.ensure_control_visible(card)


func _scroll_ancestor(node: Node) -> ScrollContainer:
	var current := node.get_parent()
	while current != null:
		if current is ScrollContainer:
			return current
		current = current.get_parent()
	return null

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
	_set_status("已复制为草稿；保存时按目标用途重新校验。", "info")
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
	_set_status("正在测试…", "progress")
	var result: Dictionary = await _executor.test_config(_test_type, _test_snapshot)
	_test_snapshot.clear()
	_testing = false
	_set_editable()
	if result.ok:
		_set_status("本次请求成功；不代表已全面认证模型能力。", "success")
	else:
		_set_status("", "muted")
		ErrorDialog.present(self, "请先填写模型地址和密钥。" if result.code in ["MODEL_FIELDS_REQUIRED","INVALID_CONFIG"] else "测试未通过，请检查服务地址和密钥后重试。")
