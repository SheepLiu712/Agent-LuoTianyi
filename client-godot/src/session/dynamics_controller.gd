extends Node
const ServerAddress = preload("res://src/domain/server_address.gd")
signal changed
signal unread_changed(count: int)
signal latest_unread_changed(post: Dictionary)
const Http = preload("res://src/network/json_request.gd")
var _session := {}
var _logger: RefCounted
var _timeout: float
var _generation := 0
var _requests: Array[Node] = []
var _timer: Timer
var _posts: Array[Dictionary] = []
var _comments := {}
var _cursor := ""
var _unread_busy := false
var _latest_unread: Dictionary = {}
var _writing := false
var _state := {"phase":"idle","code":"","unread":0,"unread_code":"","has_more":false,"busy":false}

func _init(logger: RefCounted = null,timeout: float = 15.0) -> void:
	_logger = logger
	_timeout = timeout

func _ready() -> void:
	_timer = Timer.new()
	_timer.wait_time = 30.0
	add_child(_timer)
	_timer.timeout.connect(refresh_unread)

func start(session: Dictionary) -> void:
	stop()
	_session = session.duplicate(true)
	_session.server = ServerAddress.normalize(str(session.get("server","")))
	_state.phase = "ready"
	_timer.start()
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
	_cursor = ""
	_unread_busy = false
	_latest_unread.clear()
	_writing = false
	_state = {"phase":"idle","code":"","unread":0,"unread_code":"","has_more":false,"busy":false}
	changed.emit()
	unread_changed.emit(0)
	latest_unread_changed.emit({})

func get_state() -> Dictionary:
	return _state.duplicate()

func get_posts() -> Array[Dictionary]:
	return _posts.duplicate(true)

func get_latest_unread() -> Dictionary:
	return _latest_unread.duplicate(true)

func get_comments(id: String) -> Dictionary:
	return _comments.get(id,_empty_comments()).duplicate(true)

func refresh() -> void:
	await _load_posts(false)

func load_more() -> void:
	if _state.has_more:
		await _load_posts(true)

func _load_posts(more: bool) -> void:
	if _session.is_empty() or _state.busy or _writing:
		return
	_state.busy = true
	changed.emit()
	var cursor := _cursor if more else ""
	var generation := _generation
	var result := await _request("/dynamics",HTTPClient.METHOD_GET,{},10,cursor)
	if generation != _generation:
		return
	_state.busy = false
	if result.ok:
		result = _page(result.data,cursor,false)
	if result.ok:
		_posts = _merge(_posts,result.items) if more else _merge(result.items,_posts)
		_cursor = result.cursor
		_state.has_more = result.has_more
	_state.code = result.code
	_notify()

func load_comments(id: String,more: bool = false) -> void:
	if _comments_blocked(id):
		return
	var state := _ensure_comments(id)
	if state.busy or (more and not state.has_more):
		return
	state.busy = true
	changed.emit()
	var generation := _generation
	var cursor: String = state.cursor if more else ""
	var result := await _request("/dynamics/"+id.uri_encode()+"/comments",HTTPClient.METHOD_GET,{},20,cursor)
	if generation != _generation:
		return
	state.busy = false
	if result.ok:
		result = _page(result.data,cursor,true,id)
	if result.ok:
		state.items = _merge(state.items if more else [],result.items)
		_sort_comments(state.items)
		state.cursor = result.cursor
		state.has_more = result.has_more
		state.loaded = true
	state.code = result.code
	_notify()
func refresh_comments(id: String) -> void:
	if _comments_blocked(id):
		return
	var state := _ensure_comments(id)
	if state.busy: return
	state.busy = true
	changed.emit()
	var generation := _generation
	var cursor := ""
	var seen := {}
	var collected: Array[Dictionary] = []
	var result: Dictionary
	while true:
		seen[cursor] = true
		result = await _request("/dynamics/"+id.uri_encode()+"/comments",HTTPClient.METHOD_GET,{},20,cursor)
		if generation != _generation: return
		if result.ok: result = _page(result.data,cursor,true,id)
		if not result.ok: break
		collected = _merge(collected,result.items)
		if not result.has_more: break
		cursor = result.cursor
		if seen.has(cursor):
			result = _failure("INVALID_RESPONSE")
			break
	state.busy = false
	state.code = result.code
	if result.ok:
		state.items = _merge(collected,state.items)
		_sort_comments(state.items)
		state.has_more = false
		state.cursor = ""
		state.loaded = true
	_notify()
func refresh_unread() -> void:
	if _session.is_empty() or _unread_busy:
		return
	_unread_busy = true
	var generation := _generation
	var result := await _request("/dynamics/unread")
	if generation != _generation:
		return
	if result.ok:
		result = _read_unread_count(result)
	if result.ok:
		var latest := await _unread_preview(result, generation)
		if generation != _generation: return
		_latest_unread = latest
		latest_unread_changed.emit(get_latest_unread())
	_unread_busy = false
	_state.unread_code = result.code
	unread_changed.emit(_state.unread)
	_log("ready",result.code)
func _load_latest_unread(generation: int, last_read: String) -> Dictionary:
	var cursor := ""
	var seen := {}
	while generation == _generation:
		seen[cursor] = true
		var result := await _request("/dynamics", HTTPClient.METHOD_GET, {}, 10, cursor)
		if generation != _generation: return _failure("CANCELLED")
		if result.ok: result = _page(result.data, cursor, false)
		if not result.ok: return result
		var preview := _first_unread_post(result.items, last_read)
		if not preview.is_empty():
			return preview
		if not result.has_more: return {"ok":true, "post":{}}
		if seen.has(result.cursor): return _failure("INVALID_RESPONSE")
		cursor = result.cursor
	return _failure("CANCELLED")
func mark_read() -> void:
	if _session.is_empty() or _unread_busy:
		return
	_unread_busy = true
	var generation := _generation
	var result := await _request("/dynamics/read",HTTPClient.METHOD_POST)
	if generation != _generation:
		return
	_unread_busy = false
	if result.ok and result.data.get("ok") != true:
		result = _failure("INVALID_RESPONSE")
	if result.ok:
		_state.unread = 0
		_latest_unread.clear()
		latest_unread_changed.emit({})
	_state.unread_code = result.code
	unread_changed.emit(_state.unread)
	_log("ready",result.code)

func _request(path: String,method: int = HTTPClient.METHOD_GET,data: Dictionary = {},limit: int = 0,cursor: String = "") -> Dictionary:
	if _session.is_empty() or _requests.size() >= 8:
		return _failure("BUSY")
	var http := Http.new(_timeout)
	add_child(http)
	_requests.append(http)
	var url: String = _session.server+path
	var headers: PackedStringArray = []
	if method == HTTPClient.METHOD_GET:
		url += "?username="+str(_session.username).uri_encode()
		if limit > 0:
			url += "&limit=%s"%limit
		if not cursor.is_empty():
			url += "&cursor="+cursor.uri_encode()
		headers.append("Authorization: Bearer "+str(_session.message_token))
	else:
		data = data.duplicate(true)
		data.merge({"username":_session.username,"token":_session.message_token},true)
	var result: Dictionary = await http.send(url,method,data,headers)
	_requests.erase(http)
	http.queue_free()
	return result

func publish(content: String) -> Dictionary:
	return await _write("",content,"")

func comment(id: String,content: String,parent_comment_id: String = "") -> Dictionary:
	var post := _find_post(id)
	if post.is_empty() or not post.allow_comment:
		return _failure("COMMENT_NOT_ALLOWED")
	if not parent_comment_id.is_empty():
		var found := false
		for item in get_comments(id).items:
			found = found or item.id == parent_comment_id
		if not found:
			return _failure("INVALID_REPLY_TARGET")
	return await _write(id,content,parent_comment_id)

func _write(id: String,content: String,parent: String) -> Dictionary:
	if content.strip_edges().is_empty():
		return _failure("INVALID_INPUT")
	if _write_blocked(id):
		return _failure("BUSY")
	_writing = true
	var generation := _generation
	var data := {"content":content}
	var path := "/dynamics"
	if not id.is_empty():
		path += "/"+id.uri_encode()+"/comments"
		data.parent_comment_id = null if parent.is_empty() else parent
	var result := await _request(path,HTTPClient.METHOD_POST,data)
	if generation != _generation:
		return _failure("CANCELLED")
	_writing = false
	if result.ok and not _valid_item(result.data.get("item"),not id.is_empty(),id):
		result = _failure("INVALID_RESPONSE")
	if result.ok:
		_accept_written_item(id, result.data.item)
	_state.code = result.code
	_notify()
	return {"ok":result.ok,"code":result.code,"item_id":result.data.item.id if result.ok else ""}
func _page(data: Dictionary,cursor: String,comments: bool,id: String = "") -> Dictionary:
	if not data.get("items") is Array or not data.get("has_more") is bool:
		return _failure("INVALID_RESPONSE")
	var next: Variant = data.get("next_cursor")
	if not _valid_next_cursor(data, next, cursor):
		return _failure("INVALID_RESPONSE")
	if data.items.size() > (20 if comments else 10):
		return _failure("INVALID_RESPONSE")
	for item in data.items:
		if not _valid_item(item,comments,id):
			return _failure("INVALID_RESPONSE")
	return {"ok":true,"code":"OK","items":data.items,"has_more":data.has_more,"cursor":next if data.has_more else ""}
func _valid_item(item: Variant,comment: bool,id: String = "") -> bool:
	if not item is Dictionary:
		return false
	for field in ["id","author_name","content","created_at","author_type"]:
		if not item.get(field) is String:
			return false
	if item.id.is_empty():
		return false
	if comment:
		return item.get("dynamic_id") == id and (item.get("parent_comment_id") == null or item.get("parent_comment_id") is String)
	return item.get("allow_comment") is bool

func _merge(existing: Array,incoming: Array) -> Array[Dictionary]:
	var result: Array[Dictionary] = []
	var ids := {}
	for item in existing+incoming:
		if not ids.has(item.id):
			result.append(item.duplicate(true))
			ids[item.id] = true
	return result

func _find_post(id: String) -> Dictionary:
	for item in _posts:
		if item.id == id:
			return item
	return {}

func _empty_comments() -> Dictionary:
	return {"items":[],"has_more":false,"cursor":"","busy":false,"code":"","loaded":false}

func _sort_comments(items: Array) -> void:
	items.sort_custom(func(a,b): return a.created_at < b.created_at or (a.created_at == b.created_at and a.id < b.id))

func _failure(code: String) -> Dictionary:
	return {"ok":false,"code":code}

func _notify() -> void:
	_log("ready",_state.code)
	changed.emit()

func _log(phase: String,code: String) -> void:
	if _logger != null:
		_logger.record("dynamics_state",{"phase":phase,"code":code,"count":_posts.size()})

func _exit_tree() -> void:
	stop()

func _comments_blocked(id: String) -> bool:
	return _session.is_empty() or _writing or _find_post(id).is_empty()

func _ensure_comments(id: String) -> Dictionary:
	if not _comments.has(id):
		_comments[id] = _empty_comments()
	return _comments[id]

func _read_unread_count(result: Dictionary) -> Dictionary:
	var count: Variant = result.data.get("unread_count")
	if (count is int or count is float) and is_finite(float(count)) and count >= 0 and count == floor(count):
		_state.unread = int(count)
	else:
		result = _failure("INVALID_RESPONSE")
	return result

func _unread_preview(result: Dictionary, generation: int) -> Dictionary:
	var latest: Dictionary = {}
	var dynamic_count: Variant = result.data.get("unread_dynamic_count", 0)
	if _has_unread_dynamics(dynamic_count):
		var last_read: Variant = result.data.get("last_read_dynamic_at")
		var preview := await _load_latest_unread(generation, last_read if last_read is String else "")
		if preview.ok:
			latest = preview.post
		else:
			result.code = preview.code
			if not _latest_unread.is_empty() and (not last_read is String or _latest_unread.created_at >= last_read):
				latest = get_latest_unread()
	return latest
func _first_unread_post(items: Array, last_read: String) -> Dictionary:
	for post in items:
		if post.author_type == "user": continue
		if not last_read.is_empty() and post.created_at < last_read: return {"ok":true, "post":{}}
		return {"ok":true, "post":post.duplicate(true)}
	return {}

func _write_blocked(id: String) -> bool:
	return _writing or _session.is_empty() or _state.busy or (not id.is_empty() and get_comments(id).busy)

func _accept_written_item(id: String, item: Dictionary) -> void:
	if id.is_empty():
		_posts = _merge([item],_posts)
	else:
		if not _comments.has(id):
			_comments[id] = _empty_comments()
		_comments[id].items = _merge(_comments[id].items,[item])
		_sort_comments(_comments[id].items)
		var post := _find_post(id)
		post.comment_count = int(post.get("comment_count",0))+1

func _valid_next_cursor(data: Dictionary, next: Variant, cursor: String) -> bool:
	return not data.has_more or (next is String and not next.is_empty() and next != cursor and not data.items.is_empty())

func _has_unread_dynamics(count: Variant) -> bool:
	return (count is int or count is float) and is_finite(float(count)) and count > 0 and count == floor(count)
