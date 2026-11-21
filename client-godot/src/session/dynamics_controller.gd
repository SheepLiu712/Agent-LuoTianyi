extends Node
## 动态控制器：本地缓存优先，网络页只负责增量刷新。
## 未读使用每条动态独立的「活动水位 / 已读水位」，不再依赖全局发布时间。

signal changed
signal unread_changed(count: int)
signal latest_unread_changed(post: Dictionary)

const ServerAddress = preload("res://src/domain/server_address.gd")
const AccountScope = preload("res://src/domain/account_scope.gd")
const Http = preload("res://src/network/json_request.gd")

const PAGE_SIZE := 10
const COMMENT_PAGE_SIZE := 20
const MAX_REFRESH_PAGES := 20
const SYNC_CANDIDATES := 5
const RETENTION_MS := 500

var _session := {}
var _logger: RefCounted
var _persistence: RefCounted
var _history_root := ""
var _timeout: float
var _generation := 0
var _requests: Array[Node] = []
var _timer: Timer
var _posts: Array[Dictionary] = []
var _comments := {}
var _state := {
	"phase":"idle", "code":"", "unread":0, "unread_code":"", "has_more":false,
	"busy":false, "last_read":"", "unread_hint":false, "revision":0,
	"local_unread_comments":0,
}
var _unread_busy := false
var _writing := false
var _syncing := false
var _syncing_ids := {}
var _latest_unread: Dictionary = {}
var _preview_dismissed := ""
var _server_unread := 0
var _server_comment_unread := 0
var _feed_loaded := false
var _storage_ready := false


func _init(logger: RefCounted = null, persistence: RefCounted = null, timeout: float = 15.0) -> void:
	_logger = logger
	_persistence = persistence
	_timeout = timeout


func _ready() -> void:
	_timer = Timer.new()
	_timer.wait_time = 30.0
	add_child(_timer)
	_timer.timeout.connect(_poll)


func set_history_root(path: String) -> void:
	_history_root = path


func start(session: Dictionary) -> void:
	stop()
	_session = session.duplicate(true)
	_session.server = ServerAddress.normalize(str(session.get("server", "")))
	_state.phase = "ready"
	if _timer != null:
		_timer.start()
	var generation := _generation
	var opened := await _open_scope()
	if generation != _generation:
		return
	if opened:
		await _reload_all()
	if generation != _generation:
		return
	await refresh_unread()


func stop() -> void:
	_generation += 1
	if _timer != null:
		_timer.stop()
	for request in _requests.duplicate():
		request.cancel()
	_session.clear()
	_posts.clear()
	_comments.clear()
	_latest_unread.clear()
	_preview_dismissed = ""
	_server_unread = 0
	_server_comment_unread = 0
	_feed_loaded = false
	_storage_ready = false
	_unread_busy = false
	_writing = false
	_syncing = false
	_syncing_ids.clear()
	_state = {
		"phase":"idle", "code":"", "unread":0, "unread_code":"", "has_more":false,
		"busy":false, "last_read":"", "unread_hint":false, "revision":0,
		"local_unread_comments":0,
	}
	changed.emit()
	unread_changed.emit(0)
	latest_unread_changed.emit({})


func get_state() -> Dictionary:
	var state := _state.duplicate(true)
	state.phase = _phase()
	return state


func get_posts() -> Array[Dictionary]:
	return _posts.duplicate(true)


## 本地 DTO 自带复合水位；没有水位字段的网络快照才退回发布时间比较。
func is_unread(post: Dictionary) -> bool:
	if post.has("last_activity_at"):
		var activity := str(post.get("last_activity_at", ""))
		if activity.is_empty():
			return false
		var read := str(post.get("read_activity_at", ""))
		if activity != read:
			return activity > read
		return str(post.get("last_activity_id", "")) > str(post.get("read_activity_id", ""))
	if str(post.get("author_type", "")) == "user":
		return false
	var created := str(post.get("created_at", ""))
	return not created.is_empty() and created > str(_state.last_read)


func get_latest_unread() -> Dictionary:
	return _latest_unread.duplicate(true)


func dismiss_preview(id: String = "") -> void:
	if _latest_unread.is_empty():
		return
	if not id.is_empty() and str(_latest_unread.get("id", "")) != id:
		return
	_preview_dismissed = str(_latest_unread.get("id", ""))
	_latest_unread.clear()
	latest_unread_changed.emit({})


func get_comments(id: String) -> Dictionary:
	return _ensure_comments(id).duplicate(true)


func refresh() -> void:
	if _session.is_empty() or _state.busy or _writing:
		return
	var generation := _generation
	_state.busy = true
	_notify()
	var result := await _sync_feed("", true, generation)
	if generation != _generation:
		return
	_feed_loaded = result.ok or _feed_loaded
	_state.busy = false
	_state.code = result.code
	_notify()


func load_more() -> void:
	if _session.is_empty() or _state.busy or _writing or not _state.has_more:
		return
	var generation := _generation
	_state.busy = true
	_notify()
	var result := await _sync_feed(str(_state.get("cursor", "")), false, generation)
	if generation != _generation:
		return
	_state.busy = false
	_state.code = result.code
	_notify()


func _sync_feed(cursor: String, refresh: bool, generation: int) -> Dictionary:
	var result := await _request("/dynamics", HTTPClient.METHOD_GET, {}, PAGE_SIZE, cursor)
	if generation != _generation:
		return _failure("CANCELLED")
	if result.ok:
		result = _page(result.data, cursor, false)
	if not result.ok:
		return result
	var persisted := await _persist_posts(result.items, refresh)
	if not persisted.ok:
		return persisted
	var page_state := await _write_page_state(result.cursor, result.has_more)
	return result if page_state.ok else page_state


## 角色卡片拿到的预览来自同一动态接口；落库后详情与列表共用同一份数据。
func accept_post(post: Dictionary) -> void:
	if post.is_empty() or str(post.get("id", "")).is_empty():
		return
	if _storage_ready:
		var saved: Dictionary = await _persistence.save_posts([post], {"prune": false})
		if saved.ok:
			await _reload_all()
			return
	_posts = _merge([post], _posts)
	_notify()


func load_comments(id: String, more: bool = false) -> void:
	if _comments_blocked(id):
		return
	var state := _ensure_comments(id)
	if state.busy or (more and not state.has_more):
		return
	if not state.loaded and _storage_ready:
		await _load_cached_comments(id)
	if _syncing_ids.has(id):
		return
	state = _ensure_comments(id)
	state.busy = true
	_notify()
	var generation := _generation
	var cursor: String = state.cursor if more else ""
	var result := await _fetch_comment_page(id, state, cursor, generation)
	if generation != _generation:
		return
	state = _ensure_comments(id)
	state.busy = false
	state.code = result.code
	_notify()


func _fetch_comment_page(id: String, state: Dictionary, cursor: String, generation: int) -> Dictionary:
	var result := await _request(
		"/dynamics/" + id.uri_encode() + "/comments", HTTPClient.METHOD_GET,
		{}, COMMENT_PAGE_SIZE, cursor)
	if generation != _generation:
		return _failure("CANCELLED")
	if result.ok:
		result = _page(result.data, cursor, true, id)
	if not result.ok:
		return result
	var saved := await _save_comment_page(id, result.items, result.cursor, result.has_more, false, false, state)
	return result if saved.ok else saved


## 增量补齐：从已保存的评论游标继续，直到 has_more=0；不重拉已缓存页。
func refresh_comments(id: String) -> void:
	if _comments_blocked(id):
		return
	var state := _ensure_comments(id)
	if state.busy or _syncing_ids.has(id):
		return
	if not state.loaded and _storage_ready:
		await _load_cached_comments(id)
	state = _ensure_comments(id)
	state.busy = true
	_notify()
	var generation := _generation
	var outcome := await _refresh_comment_pages(id, state, state.cursor, generation)
	if generation != _generation:
		return
	var result: Dictionary = outcome.result
	if result.ok:
		var has_more := bool(result.get("has_more", false))
		var synced := await _save_comment_page(
			id, [], str(outcome.cursor), has_more, not has_more, false, state)
		if not synced.ok:
			result = synced
		await _reload_all()
	state = _ensure_comments(id)
	state.busy = false
	state.code = result.code
	_notify()


func _refresh_comment_pages(id: String, state: Dictionary, start: String, generation: int) -> Dictionary:
	var cursor := start
	var guard := {}
	var result := {"ok": true, "code": "OK"}
	for _page_index in MAX_REFRESH_PAGES:
		guard[cursor] = true
		result = await _fetch_comment_page(id, state, cursor, generation)
		if generation != _generation:
			return {"result": _failure("CANCELLED"), "cursor": cursor}
		if not result.ok:
			break
		if not result.has_more:
			break
		if result.cursor == cursor or guard.has(result.cursor):
			result = _failure("INVALID_RESPONSE", "comment cursor did not advance")
			break
		cursor = result.cursor
	return {"result": result, "cursor": cursor}


func refresh_unread() -> void:
	if _session.is_empty() or _unread_busy:
		return
	_unread_busy = true
	var generation := _generation
	var result := await _request("/dynamics/unread")
	if generation != _generation:
		return
	if result.ok:
		result = _read_unread_counts(result)
	if result.ok:
		await _apply_server_unread(result.data)
	_unread_busy = false
	_state.unread_code = result.code
	unread_changed.emit(_state.unread)
	latest_unread_changed.emit(get_latest_unread())
	_log("ready", result.code)


## 单条已读：只推进该动态的本地 read_activity，并立即落库。
func mark_post_read(id: String) -> void:
	if id.is_empty():
		return
	if _storage_ready:
		var marked: Dictionary = await _persistence.mark_post_read(id)
		if not marked.ok:
			_state.unread_code = marked.code
			_notify()
			return
		await _reload_all()
		return
	for index in _posts.size():
		if str(_posts[index].id) == id:
			_posts[index]["read_activity_at"] = str(_posts[index].get("last_activity_at", ""))
			_posts[index]["read_activity_id"] = str(_posts[index].get("last_activity_id", ""))
			break
	_notify()


## 全部已读：本地先行并立即刷新；服务端失败只提示网络异常，不回滚本地圆点。
func mark_read() -> void:
	if _storage_ready:
		await _persistence.mark_all_read()
		await _reload_all()
	else:
		for index in _posts.size():
			_posts[index]["read_activity_at"] = str(_posts[index].get("last_activity_at", ""))
			_posts[index]["read_activity_id"] = str(_posts[index].get("last_activity_id", ""))
		_state.unread = 0
		_latest_unread.clear()
		_notify()
	if _session.is_empty():
		return
	var result: Dictionary = await _request("/dynamics/read", HTTPClient.METHOD_POST)
	if result.ok and result.data.get("ok") != true:
		result = _failure("INVALID_RESPONSE")
	if result.ok:
		await _apply_server_unread(result.data)
	_state.unread_code = result.code
	unread_changed.emit(_state.unread)
	latest_unread_changed.emit(get_latest_unread())


func publish(content: String) -> Dictionary:
	var result: Dictionary = await _write("", content, "")
	_log_write("dynamics_post_publish", result)
	return result


func comment(id: String, content: String, parent_comment_id: String = "") -> Dictionary:
	var post := _find_post(id)
	if post.is_empty() or not post.allow_comment:
		var detail := "Post not found or comments disabled for post: %s" % id
		_log_comment_rejected("COMMENT_NOT_ALLOWED", detail)
		return _failure("COMMENT_NOT_ALLOWED", detail)
	if not parent_comment_id.is_empty():
		var found := false
		for item in get_comments(id).items:
			found = found or item.id == parent_comment_id
		if not found:
			var detail := "Parent comment not found: %s" % parent_comment_id
			_log_comment_rejected("INVALID_REPLY_TARGET", detail)
			return _failure("INVALID_REPLY_TARGET", detail)
	var result: Dictionary = await _write(id, content, parent_comment_id)
	_log_write("dynamics_comment_created", result)
	return result


func _write(id: String, content: String, parent: String) -> Dictionary:
	if content.strip_edges().is_empty():
		return _failure("INVALID_INPUT", "comment content is empty")
	if _write_blocked(id):
		return _failure("BUSY", "dynamics write is blocked by another operation")
	_writing = true
	var generation := _generation
	var data := {"content": content}
	var path := "/dynamics"
	if not id.is_empty():
		path += "/" + id.uri_encode() + "/comments"
		data.parent_comment_id = null if parent.is_empty() else parent
	var result := await _request(path, HTTPClient.METHOD_POST, data)
	_writing = false
	if generation != _generation:
		return _failure("CANCELLED", "dynamics write was cancelled")
	if result.ok and not _valid_item(result.data.get("item"), not id.is_empty(), id):
		result = _failure("INVALID_RESPONSE", "server item does not match the written post or comment")
	if result.ok:
		await _accept_written_item(id, result.data.item)
	_notify()
	return {
		"ok": result.ok, "code": result.code,
		"item_id": str(result.data.item.id) if result.ok else "",
		"detail": str(result.get("detail", "")),
	}


func _accept_written_item(id: String, item: Dictionary) -> void:
	if id.is_empty():
		await _persist_posts([item], false, false)
		return
	var state := _ensure_comments(id)
	var saved: Dictionary = await _save_comment_page(
		id, [item], state.cursor, state.has_more, false, true, state)
	if saved.ok:
		await _reload_all()


func _open_scope() -> bool:
	if _persistence == null:
		return false
	var scope := AccountScope.key(str(_session.get("server", "")), str(_session.get("username", "")))
	if scope.is_empty() or _history_root.is_empty():
		return false
	var result: Dictionary = await _persistence.open_scope(_history_root, scope)
	_storage_ready = result.ok
	return result.ok


func _reload_all() -> void:
	if not _storage_ready:
		return
	var result: Dictionary = await _persistence.load_posts()
	if not result.ok:
		_state.code = result.code
		_notify()
		return
	_apply_posts(result.data)
	_state.code = "OK"
	_notify()


func _reload_summary() -> void:
	if not _storage_ready:
		_recompute_memory_unread()
		_notify()
		return
	var result: Dictionary = await _persistence.load_summary()
	if not result.ok:
		_state.unread_code = result.code
		_notify()
		return
	_apply_summary(result.data)
	_notify()


func _apply_posts(data: Dictionary) -> void:
	_posts = _typed_posts(data.get("posts", []))
	if not _posts.is_empty():
		_feed_loaded = true
	var state: Dictionary = data.get("state", {})
	_state.last_read = str(state.get("server_read_at", ""))
	_state.has_more = bool(state.get("has_more", false))
	_state.cursor = str(state.get("posts_cursor", ""))
	_state.revision = int(state.get("revision", 0))
	_apply_summary(data)


static func _typed_posts(rows: Array) -> Array[Dictionary]:
	var result: Array[Dictionary] = []
	for row in rows:
		if row is Dictionary:
			result.append(row)
	return result


func _apply_summary(data: Dictionary) -> void:
	var state: Dictionary = data.get("state", {})
	if not state.is_empty():
		_state.last_read = str(state.get("server_read_at", ""))
		_state.has_more = bool(state.get("has_more", _state.has_more))
		_state.cursor = str(state.get("posts_cursor", _state.get("cursor", "")))
		_state.revision = int(state.get("revision", _state.revision))
	var local_unread := int(data.get("unread_count", 0))
	var local_comments := int(data.get("local_unread_comments", 0))
	_state.local_unread_comments = local_comments
	_state.unread = _badge_count(local_unread)
	_state.unread_hint = _server_unread > local_unread or _server_comment_unread > local_comments
	var latest: Dictionary = data.get("latest_unread", {})
	_latest_unread = {} if not _preview_dismissed.is_empty() else latest
	unread_changed.emit(_state.unread)
	latest_unread_changed.emit(get_latest_unread())


## 冷启动尚未拉到 feed 时用服务端总数撑住徽标；缓存存在后完全以本地水位为准。
func _badge_count(local_unread: int) -> int:
	if not _feed_loaded and local_unread == 0 and _server_unread > 0:
		return _server_unread
	return local_unread


func _write_page_state(cursor: String, has_more: bool) -> Dictionary:
	if not _storage_ready:
		_state.cursor = cursor
		_state.has_more = has_more
		return _success()
	var result: Dictionary = await _persistence.write_state({
		"posts_cursor": cursor, "has_more": has_more, "last_sync_ms": _now_ms(),
	})
	if not result.ok:
		return result
	await _reload_all()
	return _success()


func _persist_posts(items: Array, refresh: bool, prune: bool = true) -> Dictionary:
	if not _storage_ready:
		_merge_memory(items, refresh)
		return _success()
	var result: Dictionary = await _persistence.save_posts(items, {"prune": refresh and prune})
	if not result.ok:
		return result
	await _reload_all()
	return _success()


func _merge_memory(items: Array, refresh: bool) -> void:
	_posts = _merge([] if refresh else _posts, items)
	_posts.sort_custom(func(a, b):
		return (str(a.created_at) > str(b.created_at)
			or (str(a.created_at) == str(b.created_at) and str(a.id) > str(b.id))))
	_recompute_memory_unread()


func _recompute_memory_unread() -> void:
	_server_unread = _state.unread
	_state.local_unread_comments = 0
	_latest_unread = {}
	for post in _posts:
		if is_unread(post):
			_latest_unread = post.duplicate(true)
			break
	var count := 0
	for post in _posts:
		if is_unread(post):
			count += 1
	_state.unread = count
	_state.unread_hint = false


func _read_unread_counts(result: Dictionary) -> Dictionary:
	var count: Variant = result.data.get("unread_count")
	var dynamic_count: Variant = result.data.get("unread_dynamic_count", 0)
	var comment_count: Variant = result.data.get("unread_comment_count", 0)
	if not _valid_count(count) or not _valid_count(dynamic_count) or not _valid_count(comment_count):
		return _failure("INVALID_RESPONSE")
	_server_unread = int(dynamic_count)
	_server_comment_unread = int(comment_count)
	_state.unread = int(count) if not _feed_loaded else _state.unread
	return result


func _apply_server_unread(data: Dictionary) -> void:
	if not _storage_ready:
		_recompute_memory_unread()
		return
	var patch := {"last_sync_ms": _now_ms()}
	if data.get("last_read_dynamic_at") is String:
		patch["server_read_at"] = data.last_read_dynamic_at
	if data.get("last_read_comment_at") is String:
		patch["server_comment_read_at"] = data.last_read_comment_at
	var result: Dictionary = await _persistence.write_state(patch)
	if not result.ok:
		_state.unread_code = result.code
		_notify()
		return
	await _reload_summary()


func _load_cached_comments(id: String) -> void:
	if not _comments.has(id):
		_comments[id] = _empty_comments()
	var state: Dictionary = _comments[id]
	if state.loading or state.loaded or state.cache_attempted or not _storage_ready:
		return
	state.loading = true
	state.cache_attempted = true
	var result: Dictionary = await _persistence.load_comments(id)
	if not result.ok:
		state.loading = false
		state.code = result.code
		_notify()
		return
	state.items = result.data.get("comments", [])
	var meta: Dictionary = result.data.get("comment_state", {})
	state.cursor = str(meta.get("cursor", ""))
	state.has_more = bool(meta.get("has_more", false))
	state.loaded_at_ms = int(meta.get("loaded_at_ms", 0))
	state.loaded = not state.items.is_empty() or int(state.loaded_at_ms) > 0
	state.loading = false
	_notify()


func _refresh_comments_from_store(id: String) -> void:
	if not _storage_ready:
		return
	var result: Dictionary = await _persistence.load_comments(id)
	if not result.ok:
		return
	if not _comments.has(id):
		_comments[id] = _empty_comments()
	var state: Dictionary = _comments[id]
	state.items = result.data.get("comments", [])
	var meta: Dictionary = result.data.get("comment_state", {})
	state.cursor = str(meta.get("cursor", ""))
	state.has_more = bool(meta.get("has_more", false))
	state.loaded_at_ms = int(meta.get("loaded_at_ms", 0))
	state.loaded = true
	state.loading = false


func _save_comment_page(id: String, items: Array, cursor: String, has_more: bool,
		mark_synced: bool, user_written: bool, state: Dictionary) -> Dictionary:
	if not _storage_ready:
		if not items.is_empty():
			state.items = _merge(state.items, items)
			_sort_comments(state.items)
			state.loaded = true
			state.cursor = cursor
			state.has_more = has_more
		return _success()
	var saved: Dictionary = await _persistence.save_comments(id, items, {
		"cursor": cursor, "has_more": has_more,
		"mark_synced": mark_synced, "user_written": user_written,
	})
	if not saved.ok:
		return saved
	await _refresh_comments_from_store(id)
	await _reload_summary()
	return _success()


## 有界发现：只对已缓存且计数增长的动态拉尾部，用户评论过的优先。
func _schedule_comment_sync() -> void:
	if _syncing or not _storage_ready or _session.is_empty():
		return
	# 服务端评论未读数高于本地聚合时，缓存页里可能藏着未刷新的旧帖回复；
	# 只对本地前几条做有界尾部探测，找不到就保留通用提示。
	var probe_all := _server_comment_unread > int(_state.get("local_unread_comments", 0))
	var candidates: Array = []
	for post in _posts:
		if bool(post.get("needs_comment_sync", false)) or probe_all:
			candidates.append(post)
	candidates.sort_custom(func(a, b):
		if bool(a.get("user_commented", false)) != bool(b.get("user_commented", false)):
			return bool(a.get("user_commented", false))
		return str(a.get("last_activity_at", "")) > str(b.get("last_activity_at", "")))
	if candidates.size() > SYNC_CANDIDATES:
		candidates = candidates.slice(0, SYNC_CANDIDATES)
	if candidates.is_empty():
		return
	_sync_candidates(candidates)


func _sync_candidates(candidates: Array) -> void:
	_syncing = true
	for post in candidates:
		var id := str(post.id)
		_syncing_ids[id] = true
		await _sync_tail(id)
		_syncing_ids.erase(id)
	_syncing = false


func _sync_tail(id: String) -> void:
	var state := _ensure_comments(id)
	if state.busy:
		return
	if not state.loaded:
		await _load_cached_comments(id)
	state = _ensure_comments(id)
	var outcome: Dictionary = await _sync_tail_pages(id, state, str(state.cursor))
	if not outcome.ok:
		return
	var marked := await _save_comment_page(
		id, [], str(outcome.cursor), bool(outcome.has_more), not bool(outcome.has_more), false, state)
	if marked.ok:
		# feed 里的 needs_comment_sync/watermark 必须同步刷新，否则下一轮会重复探测。
		await _reload_all()


func _sync_tail_pages(id: String, state: Dictionary, start_cursor: String) -> Dictionary:
	var cursor := start_cursor
	var guard := {}
	var has_more := false
	for _page_index in MAX_REFRESH_PAGES:
		guard[cursor] = true
		var result: Dictionary = await _request(
			"/dynamics/" + id.uri_encode() + "/comments", HTTPClient.METHOD_GET,
			{}, COMMENT_PAGE_SIZE, cursor)
		if result.ok:
			result = _page(result.data, cursor, true, id)
		if not result.ok:
			return {"ok": false}
		has_more = bool(result.has_more)
		var saved := await _save_comment_page(id, result.items, result.cursor, result.has_more, false, false, state)
		if not saved.ok:
			return {"ok": false}
		if not has_more:
			return {"ok": true, "cursor": result.cursor, "has_more": false}
		if result.cursor == cursor or guard.has(result.cursor):
			return {"ok": false}
		cursor = result.cursor
	return {"ok": true, "cursor": cursor, "has_more": has_more}


func _poll() -> void:
	if _session.is_empty() or _unread_busy:
		return
	await refresh_unread()
	_schedule_comment_sync()


func _request(path: String, method: int = HTTPClient.METHOD_GET, data: Dictionary = {},
		limit: int = 0, cursor: String = "") -> Dictionary:
	if _session.is_empty() or _requests.size() >= 8:
		return _failure("BUSY")
	var http := Http.new(_timeout, 8 * 1024 * 1024, _logger)
	add_child(http)
	_requests.append(http)
	var url: String = str(_session.server) + path
	var headers: PackedStringArray = []
	if method == HTTPClient.METHOD_GET:
		url += "?username=" + str(_session.username).uri_encode()
		if limit > 0:
			url += "&limit=%s" % limit
		if not cursor.is_empty():
			url += "&cursor=" + cursor.uri_encode()
		headers.append("Authorization: Bearer " + str(_session.message_token))
	else:
		data = data.duplicate(true)
		data.merge({"username": _session.username, "token": _session.message_token}, true)
	var result: Dictionary = await http.send(url, method, data, headers)
	_requests.erase(http)
	http.queue_free()
	return result


func _page(data: Dictionary, cursor: String, comments: bool, id: String = "") -> Dictionary:
	if not _valid_page_shape(data, cursor, comments, id):
		return _failure("INVALID_RESPONSE")
	return {
		"ok": true, "code": "OK", "items": data.items,
		"has_more": data.has_more, "cursor": _page_cursor(data, cursor),
	}


func _valid_page_shape(data: Dictionary, cursor: String, comments: bool, id: String) -> bool:
	if not data.get("items") is Array or not data.get("has_more") is bool:
		return false
	if not _valid_next_cursor(data, data.get("next_cursor"), cursor):
		return false
	if data.items.size() > (COMMENT_PAGE_SIZE if comments else PAGE_SIZE):
		return false
	for item in data.items:
		if not _valid_item(item, comments, id):
			return false
	return true


func _page_cursor(data: Dictionary, cursor: String) -> String:
	if data.has_more:
		return str(data.next_cursor)
	if not data.items.is_empty() and data.items[-1].get("cursor") is String:
		return str(data.items[-1].cursor)
	return cursor


func _valid_item(item: Variant, comment: bool, id: String = "") -> bool:
	if not item is Dictionary:
		return false
	for field in ["id", "author_name", "content", "created_at", "author_type"]:
		if not item.get(field) is String:
			return false
	if str(item.id).is_empty():
		return false
	if comment:
		return item.get("dynamic_id") == id \
			and (item.get("parent_comment_id") == null or item.get("parent_comment_id") is String)
	return item.get("allow_comment") is bool


func _valid_next_cursor(data: Dictionary, next: Variant, cursor: String) -> bool:
	return not data.has_more \
		or (next is String and not str(next).is_empty() and str(next) != cursor and not data.items.is_empty())


func _comments_blocked(id: String) -> bool:
	return _session.is_empty() or _writing or _find_post(id).is_empty()


func _write_blocked(id: String) -> bool:
	return _writing or _session.is_empty() or _state.busy \
		or (not id.is_empty() and get_comments(id).busy)


func _ensure_comments(id: String) -> Dictionary:
	if not _comments.has(id):
		_comments[id] = _empty_comments()
	var state: Dictionary = _comments[id]
	if not state.loaded and not state.loading and not state.cache_attempted and _storage_ready:
		_load_cached_comments(id)
	return state


func _empty_comments() -> Dictionary:
	return {"items": [], "has_more": false, "cursor": "", "busy": false,
		"code": "", "loaded": false, "loading": false, "cache_attempted": false, "loaded_at_ms": 0}


func _merge(existing: Array, incoming: Array) -> Array[Dictionary]:
	var result: Array[Dictionary] = []
	var ids := {}
	for item in existing + incoming:
		if not ids.has(item.id):
			result.append(item.duplicate(true))
			ids[item.id] = true
	return result


func _find_post(id: String) -> Dictionary:
	for item in _posts:
		if str(item.id) == id:
			return item
	return {}


func _sort_comments(items: Array) -> void:
	items.sort_custom(func(a, b):
		return (str(a.created_at) < str(b.created_at)
			or (str(a.created_at) == str(b.created_at) and str(a.id) < str(b.id))))


func _phase() -> String:
	if _state.busy:
		return "loading"
	if str(_state.code) not in ["", "OK"] and _posts.is_empty():
		return "failed"
	return "ready"


func _notify() -> void:
	_state.phase = _phase()
	_log("ready", str(_state.code))
	changed.emit()
	unread_changed.emit(_state.unread)
	latest_unread_changed.emit(get_latest_unread())


func _log(phase: String, code: String) -> void:
	if _logger != null:
		_logger.record_as("business", "dynamics_state", {
			"phase": phase, "code": code, "reason": "dynamics",
			"count": _posts.size(), "level": "WARN" if code not in ["", "OK"] else "INFO"})


func _log_write(event: String, result: Dictionary) -> void:
	if _logger == null:
		return
	var ok: bool = result.get("ok", false)
	_logger.record_as("business", event, {
		"phase": "complete" if ok else "failed",
		"outcome": "success" if ok else "failure",
		"code": str(result.get("code", "UNKNOWN")),
		"detail": str(result.get("detail", ""))})


func _log_comment_rejected(code: String, detail: String) -> void:
	if _logger != null:
		_logger.record_as("business", "dynamics_comment_rejected", {
			"phase": "failed", "code": code, "level": "WARN", "detail": detail})


static func _valid_count(value: Variant) -> bool:
	return (value is int or value is float) and is_finite(float(value)) \
		and float(value) >= 0 and float(value) == floor(float(value))


static func _now_ms() -> int:
	@warning_ignore("narrowing_conversion")
	return int(Time.get_unix_time_from_system() * 1000.0)


static func _failure(code: String, detail: String = "") -> Dictionary:
	return {"ok": false, "code": code, "detail": detail}


static func _success() -> Dictionary:
	return {"ok": true, "code": "OK", "data": {}}


func _exit_tree() -> void:
	stop()
