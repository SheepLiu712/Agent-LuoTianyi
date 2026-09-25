extends Node
const ServerAddress = preload("res://src/domain/server_address.gd")
signal changed
signal unread_changed(count: int)
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
	_writing = false
	_state = {"phase":"idle","code":"","unread":0,"unread_code":"","has_more":false,"busy":false}
	changed.emit()
	unread_changed.emit(0)

func get_state() -> Dictionary:
	return _state.duplicate()

func get_posts() -> Array[Dictionary]:
	return _posts.duplicate(true)

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
	if _session.is_empty() or _writing or not _find_post(id).size():
		return
	if not _comments.has(id):
		_comments[id] = _empty_comments()
	var state: Dictionary = _comments[id]
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
	if _session.is_empty() or _writing or _find_post(id).is_empty(): return
	if not _comments.has(id): _comments[id] = _empty_comments()
	var state: Dictionary = _comments[id]
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
	_unread_busy = false
	if result.ok:
		var count: Variant = result.data.get("unread_count")
		if (count is int or count is float) and is_finite(float(count)) and count >= 0 and count == floor(count):
			_state.unread = int(count)
		else:
			result = _failure("INVALID_RESPONSE")
	_state.unread_code = result.code
	unread_changed.emit(_state.unread)
	_log("ready",result.code)

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
	if _writing or _session.is_empty() or _state.busy or (not id.is_empty() and get_comments(id).busy):
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
		if id.is_empty():
			_posts = _merge([result.data.item],_posts)
		else:
			if not _comments.has(id):
				_comments[id] = _empty_comments()
			_comments[id].items = _merge(_comments[id].items,[result.data.item])
			_sort_comments(_comments[id].items)
			var post := _find_post(id)
			post.comment_count = int(post.get("comment_count",0))+1
	_state.code = result.code
	_notify()
	return {"ok":result.ok,"code":result.code,"item_id":result.data.item.id if result.ok else ""}

func _page(data: Dictionary,cursor: String,comments: bool,id: String = "") -> Dictionary:
	if not data.get("items") is Array or not data.get("has_more") is bool:
		return _failure("INVALID_RESPONSE")
	var next: Variant = data.get("next_cursor")
	if data.has_more and (not next is String or next.is_empty() or next == cursor or data.items.is_empty()):
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
