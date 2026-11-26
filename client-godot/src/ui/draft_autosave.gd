extends RefCounted
## 把一个 TextEdit 绑定到某条草稿：恢复内容、停顿后落盘、关闭前同步 flush。

const SAVE_DELAY := 0.3

var _store: RefCounted
var _scope := ""
var _key := ""
var _editor: TextEdit
var _timer: Timer
var _failed := false
var _bound := false


func bind(editor: TextEdit, store: RefCounted, scope: String, key: String, restore: bool = true) -> void:
	_editor = editor
	_store = store
	_scope = scope
	_key = key
	if _editor == null or _store == null or _scope.is_empty() or _key.is_empty():
		return
	if restore:
		var restored := str(_store.read_text(_scope, _key))
		if not restored.is_empty():
			_editor.text = restored
	_timer = Timer.new()
	_timer.one_shot = true
	_timer.wait_time = SAVE_DELAY
	_timer.timeout.connect(_save)
	_editor.add_child(_timer)
	_editor.text_changed.connect(_schedule)
	_bound = true


func flush() -> bool:
	if not _bound:
		return true
	if is_instance_valid(_timer):
		_timer.stop()
	return _save()


func clear() -> void:
	if is_instance_valid(_timer):
		_timer.stop()
	if _bound:
		_store.clear_text(_scope, _key)
	_failed = false


func has_failure() -> bool:
	return _failed


func _schedule() -> void:
	if is_instance_valid(_timer):
		_timer.start()


func _save() -> bool:
	if not _bound or not is_instance_valid(_editor):
		return true
	var text := _editor.text
	var error := int(_store.write_text(_scope, _key, "" if text.strip_edges().is_empty() else text))
	_failed = error != OK
	return not _failed
