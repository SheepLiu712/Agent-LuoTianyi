extends RefCounted
## 动态持久化门面：控制器唯一知道「要写库」的地方。
## 与聊天共用同一个 ScopeSession，不重复开库；行转 DTO 在存储层完成。

const POST_LIMIT := 500
const COMMENT_LIMIT := 1000

var _scope_session: RefCounted


func _init(scope_session: RefCounted = null) -> void:
	_scope_session = scope_session


func is_open() -> bool:
	return _scope_session != null and _scope_session.is_open()


func scope() -> String:
	return "" if _scope_session == null else str(_scope_session.scope())


func open_scope(root: String, scope: String) -> Dictionary:
	if _scope_session == null:
		return _failure("STORAGE_UNAVAILABLE")
	return await _scope_session.ensure_open(root, scope)


func close_scope() -> Dictionary:
	if _scope_session == null:
		return _success()
	return await _scope_session.close_scope()


func load_posts(limit: int = POST_LIMIT) -> Dictionary:
	return await _submit("dynamics_load", {"limit": limit})


func load_summary() -> Dictionary:
	return await _submit("dynamics_load", {"summary_only": true})


func load_comments(post_id: String, limit: int = COMMENT_LIMIT) -> Dictionary:
	return await _submit("dynamics_load", {"post_id": post_id, "limit": limit})


func save_posts(rows: Array, options: Dictionary = {}) -> Dictionary:
	var payload := {"rows": rows.duplicate(true), "prune": true}
	payload.merge(options, true)
	return await _submit("dynamics_save_posts", payload)


func save_comments(post_id: String, rows: Array, options: Dictionary = {}) -> Dictionary:
	var payload := {"post_id": post_id, "rows": rows.duplicate(true)}
	payload.merge(options, true)
	return await _submit("dynamics_save_comments", payload)


func mark_post_read(post_id: String) -> Dictionary:
	return await _submit("dynamics_mark_read", {"post_id": post_id})


func mark_all_read() -> Dictionary:
	return await _submit("dynamics_mark_read", {})


func read_state() -> Dictionary:
	return await _submit("dynamics_state", {})


func write_state(patch: Dictionary) -> Dictionary:
	return await _submit("dynamics_state", {"patch": patch.duplicate(true)})


func _submit(operation: String, payload: Dictionary) -> Dictionary:
	if not is_open():
		return _failure("STORAGE_UNAVAILABLE")
	payload["scope"] = scope()
	return await _scope_session.worker().submit(operation, payload).wait()


static func _failure(code: String) -> Dictionary:
	return {"ok": false, "code": code, "data": {}}


static func _success(data: Dictionary = {}) -> Dictionary:
	return {"ok": true, "code": "OK", "data": data}
