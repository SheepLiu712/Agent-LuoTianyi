extends RefCounted
const AccountScope = preload("res://src/domain/account_scope.gd")
const ServerAddress = preload("res://src/domain/server_address.gd")
var _root: String
var _path := ""
var _messages: Array = []
var _state: Dictionary
func _init(root: String = "user://reading") -> void:
	_root = root
	start("","")
func start(server: String, username: String) -> void:
	_messages = []
	_path = ""
	_state = {"saved_id":"","target_id":"","pending":true,"manual":false,"located":false,"reason":""}
	var base := ServerAddress.normalize(server)
	if base.is_empty() or username.is_empty():
		return
	_path = _root.path_join(AccountScope.key(server, username)+".json")
	if FileAccess.file_exists(_path):
		var data: Variant = JSON.parse_string(FileAccess.get_file_as_string(_path))
		if data is Dictionary and data.get("uuid") is String:
			_state.saved_id = data.uuid
func update(messages: Array, history_state: Dictionary) -> void:
	_messages = messages.duplicate()
	if not _state.pending or history_state.get("phase") in ["idle","first_loading","first_failed","skipped"]:
		return
	if not _state.saved_id.is_empty():
		var index := _index(_state.saved_id)
		if index >= 0:
			_state.target_id = messages[mini(index+1,messages.size()-1)].id
		elif history_state.get("phase") != "complete":
			return
		else:
			_state.reason = "NOT_FOUND"
	if _state.target_id.is_empty() and not messages.is_empty():
		_state.target_id = messages[-1].id
	_state.pending = false
func get_state() -> Dictionary:
	return _state.duplicate(true)
func interact() -> void:
	_state.manual = true
func located() -> void:
	if not _state.pending:
		_state.located = true
func report_visible(ids: Array, foreground: bool) -> Error:
	if not foreground or _state.pending or not _state.located or _path.is_empty():
		return OK
	var candidate: String = _state.saved_id
	var previous := _index(candidate)
	for id in ids:
		var index := _index(id)
		if index <= previous or index < 0:
			continue
		var message: Dictionary = _messages[index]
		if (message.get("history",false) or message.get("role") == "assistant") and not message.get("is_ephemeral",false):
			candidate = id
			previous = index
	if candidate == _state.saved_id:
		return OK
	var error := DirAccess.make_dir_recursive_absolute(_root)
	if error == OK:
		var file := FileAccess.open(_path+".tmp",FileAccess.WRITE)
		if file == null:
			error = FileAccess.get_open_error()
		else:
			file.store_string(JSON.stringify({"uuid":candidate}))
			file.flush()
			error = file.get_error()
			file.close()
			if error == OK:
				error = DirAccess.rename_absolute(_path+".tmp",_path)
	if error == OK:
		_state.saved_id = candidate
	else:
		_state.reason = "SAVE_FAILED"
		if FileAccess.file_exists(_path+".tmp"):
			DirAccess.remove_absolute(_path+".tmp")
	return error
func _index(id: String) -> int:
	for index in _messages.size():
		if _messages[index].id == id:
			return index
	return -1
