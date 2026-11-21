extends RefCounted
## 动态缓存：动态、评论与同步状态共用聊天同一条连接。
## 本类只负责 SQL 与行映射，不做网络、不决定刷新策略。

const Schema = preload("res://src/storage/history_schema.gd")

const POST_LIMIT := 500
const COMMENT_LIMIT := 1000
const RETENTION_DAYS := 90

var _access: RefCounted


func _init(access: RefCounted) -> void:
	_access = access


## post_id 为空：返回 feed + 全局状态 + 未读汇总；
## post_id 非空：返回该动态的评论缓存与评论游标。
func load(payload: Dictionary) -> Dictionary:
	var post_id := str(payload.get("post_id", ""))
	if not post_id.is_empty():
		return _load_comments(post_id, int(payload.get("limit", COMMENT_LIMIT)))
	var result := _summary()
	if not result.ok:
		return result
	if not bool(payload.get("summary_only", false)):
		var posts: Dictionary = _access.query(Schema.READ_POSTS, [int(payload.get("limit", POST_LIMIT))])
		if not posts.ok:
			return posts
		result.data.posts = _access.rows_of(posts).map(func(row): return _post_dto(row))
	else:
		result.data.posts = []
	return result


func save_posts(payload: Dictionary) -> Dictionary:
	var result: Dictionary = _access.transaction(
		_save_posts_in_transaction.bind(payload), "dynamics_save_posts")
	if result.ok and bool(payload.get("prune", false)):
		_access.execute(Schema.INCREMENTAL_VACUUM)
	return result


func _save_posts_in_transaction(payload: Dictionary) -> Dictionary:
	var items: Array = payload.get("rows", [])
	var read_state: Dictionary = _access.query(Schema.READ_DYNAMICS_STATE)
	if not read_state.ok:
		return read_state
	var state_row: Dictionary = _access.first_row(read_state)
	if state_row.is_empty():
		return _failure("CACHE_METADATA_INVALID")
	var server_read_at := str(state_row.server_read_at)
	var now := _now_ms()
	for item in items:
		var written := _insert_post(item, server_read_at, now)
		if not written.ok:
			return written
	if bool(payload.get("prune", false)):
		var pruned := _prune_refresh(items)
		if not pruned.ok:
			return pruned
	return _summary()


func _insert_post(item: Variant, server_read_at: String, now: int) -> Dictionary:
	if not item is Dictionary or not _valid_post(item):
		return _failure("INVALID_INPUT")
	var comment_count := int(item.get("comment_count", 0))
	var activity := _post_activity(item, server_read_at)
	return _access.execute(Schema.INSERT_POST, [
		str(item.id), str(item.created_at), str(item.author_type),
		str(item.get("author_id", "")), str(item.get("author_name", "")),
		str(item.get("content", "")), _flag(item.get("allow_comment", false)),
		comment_count, 1 if comment_count > 0 else 0,
		activity.last_at, activity.last_id, activity.last_kind,
		activity.read_at, activity.read_id,
		JSON.stringify(item), now, now,
	])


## 首次见到动态时按服务端已读基线初始化活动/已读水位。
func _post_activity(item: Dictionary, server_read_at: String) -> Dictionary:
	var created := str(item.created_at)
	var self_post := str(item.author_type) == "user"
	if self_post:
		return {
			"last_at": "", "last_id": "", "last_kind": "",
			"read_at": "", "read_id": "",
		}
	var read := created <= server_read_at
	return {
		# 非本人动态始终记录活动；是否未读只由 read_activity 与基线比较决定。
		"last_at": created,
		"last_id": str(item.id),
		"last_kind": "post",
		"read_at": created if read else "",
		"read_id": str(item.id) if read else "",
	}


## 首屏刷新：本页最旧时间之后、却不在本页里的缓存视为服务端已撤下。
## 更早缓存保留；同秒条目可能被下一页重新带回，下一次 load_more 会补齐。
func _prune_refresh(items: Array) -> Dictionary:
	if items.is_empty():
		return _success()
	var ids: Array = []
	var earliest := str(items[0].created_at)
	for item in items:
		ids.append(str(item.id))
		var created := str(item.created_at)
		if created < earliest:
			earliest = created
	var sql: String = Schema.DELETE_POSTS_SINCE % Schema.placeholders(ids.size())
	var deleted: Dictionary = _access.execute(sql, [earliest] + ids)
	if not deleted.ok:
		return deleted
	var evicted: Dictionary = _access.execute(Schema.EVICT_POSTS, [POST_LIMIT])
	if not evicted.ok:
		return evicted
	return _access.execute(Schema.EVICT_OLD_POSTS, [_days_ago(RETENTION_DAYS)])


func save_comments(payload: Dictionary) -> Dictionary:
	return _access.transaction(_save_comments_in_transaction.bind(payload), "dynamics_save_comments")


func _save_comments_in_transaction(payload: Dictionary) -> Dictionary:
	var post_id := str(payload.get("post_id", ""))
	var loaded := _load_post(post_id)
	if not loaded.ok:
		return loaded
	var post: Dictionary = loaded.data.post
	var marks := {
		"last_at": str(post.last_activity_at),
		"last_id": str(post.last_activity_id),
		"last_kind": str(post.last_activity_kind),
		"read_at": str(post.read_activity_at),
		"read_id": str(post.read_activity_id),
		"user_commented": int(post.user_commented) == 1,
	}
	var now := _now_ms()
	var inserted := _insert_comments(payload.get("rows", []), post_id, now, marks, str(loaded.data.baseline))
	if not inserted.ok:
		return inserted
	var flags := _apply_post_flags(post_id, post, marks)
	if not flags.ok:
		return flags
	var meta := _apply_comment_meta(post_id, post, payload, now)
	if not meta.ok:
		return meta
	return _summary()


func _load_post(post_id: String) -> Dictionary:
	var post_result: Dictionary = _access.query(Schema.READ_POST, [post_id])
	if not post_result.ok:
		return post_result
	var post: Dictionary = _access.first_row(post_result)
	if post.is_empty():
		return _failure("POST_MISSING")
	var state_result: Dictionary = _access.query(Schema.READ_DYNAMICS_STATE)
	if not state_result.ok:
		return state_result
	return _success({
		"post": post,
		"baseline": str(_access.first_row(state_result).server_comment_read_at),
	})


func _insert_comments(rows: Array, post_id: String, now: int, marks: Dictionary, baseline: String) -> Dictionary:
	for item in rows:
		var written := _insert_comment(item, post_id, now)
		if not written.ok:
			return written
		_merge_watermark(marks, item, baseline)
	return _success()


func _apply_post_flags(post_id: String, post: Dictionary, marks: Dictionary) -> Dictionary:
	var activity := _write_watermark(post_id, post, marks)
	if not activity.ok:
		return activity
	if bool(marks.user_commented) and int(post.user_commented) == 0:
		return _access.execute(Schema.MARK_USER_COMMENT_FLAG, [post_id])
	return _success()


func _apply_comment_meta(post_id: String, post: Dictionary, payload: Dictionary, now: int) -> Dictionary:
	var cursor := str(payload.get("cursor", post.comment_cursor))
	if cursor.is_empty():
		cursor = str(post.comment_cursor)
	var sync: Dictionary = _access.execute(Schema.UPDATE_POST_COMMENT_SYNC, [
		cursor, _flag(payload.get("has_more", false)), now, post_id,
	])
	if not sync.ok:
		return sync
	if bool(payload.get("mark_synced", false)):
		var marked: Dictionary = _access.execute(Schema.MARK_COMMENT_SYNCED, [post_id])
		if not marked.ok:
			return marked
	if bool(payload.get("user_written", false)):
		var own: Dictionary = _access.execute(Schema.MARK_USER_COMMENT, [post_id])
		if not own.ok:
			return own
	return _success()


func _insert_comment(item: Variant, post_id: String, now: int) -> Dictionary:
	if not item is Dictionary or not _valid_comment(item, post_id):
		return _failure("INVALID_INPUT")
	return _access.execute(Schema.INSERT_COMMENT, [
		str(item.id), post_id, _nullable_text(item.get("parent_comment_id")),
		str(item.created_at), str(item.author_type),
		str(item.get("author_id", "")), str(item.get("author_name", "")),
		str(item.get("content", "")), JSON.stringify(item), now,
	])


func _merge_watermark(marks: Dictionary, item: Dictionary, server_comment_read_at: String) -> void:
	if str(item.author_type) == "user":
		marks.user_commented = true
		return
	var created := str(item.created_at)
	var comment_id := str(item.id)
	if _tuple_gt(created, comment_id, str(marks.last_at), str(marks.last_id)):
		marks.last_at = created
		marks.last_id = comment_id
		marks.last_kind = "comment"
	if created <= server_comment_read_at and _tuple_gt(
			created, comment_id, str(marks.read_at), str(marks.read_id)):
		marks.read_at = created
		marks.read_id = comment_id


func _write_watermark(post_id: String, post: Dictionary, marks: Dictionary) -> Dictionary:
	if str(marks.last_at) == str(post.last_activity_at) \
			and str(marks.last_id) == str(post.last_activity_id) \
			and str(marks.read_at) == str(post.read_activity_at) \
			and str(marks.read_id) == str(post.read_activity_id):
		return _success()
	return _access.execute(Schema.UPDATE_POST_ACTIVITY, [
		str(marks.last_at), str(marks.last_id), str(marks.last_kind),
		str(marks.read_at), str(marks.read_id), post_id,
	])


func mark_read(payload: Dictionary) -> Dictionary:
	return _access.transaction(_mark_read_in_transaction.bind(payload), "dynamics_mark_read")


func _mark_read_in_transaction(payload: Dictionary) -> Dictionary:
	var post_id := str(payload.get("post_id", ""))
	var updated: Dictionary
	if post_id.is_empty():
		updated = _access.execute(Schema.MARK_ALL_READ)
	else:
		updated = _access.execute(Schema.MARK_ONE_READ, [post_id])
	if not updated.ok:
		return updated
	return _summary()


## patch 为空只读；非空按「服务端基线单调递增」合并。
func state(payload: Dictionary) -> Dictionary:
	var patch: Dictionary = payload.get("patch", {})
	if patch.is_empty():
		return _state_only()
	return _access.transaction(_write_state_in_transaction.bind(patch), "dynamics_state")


func _write_state_in_transaction(patch: Dictionary) -> Dictionary:
	var result: Dictionary = _access.query(Schema.READ_DYNAMICS_STATE)
	if not result.ok:
		return result
	var row: Dictionary = _access.first_row(result)
	if row.is_empty():
		return _failure("CACHE_METADATA_INVALID")
	var old_read := str(row.server_read_at)
	var old_comment := str(row.server_comment_read_at)
	var server_read := _max_text(old_read, str(patch.get("server_read_at", old_read)))
	var server_comment := _max_text(old_comment, str(patch.get("server_comment_read_at", old_comment)))
	var written: Dictionary = _access.execute(Schema.WRITE_DYNAMICS_STATE, [
		str(row.scope_key), server_read, server_comment,
		str(patch.get("posts_cursor", row.posts_cursor)),
		_flag(patch.get("has_more", int(row.has_more) == 1)),
		int(patch.get("refresh_version", row.refresh_version)),
		int(patch.get("last_sync_ms", row.last_sync_ms)),
	])
	if not written.ok:
		return written
	if server_read > old_read:
		var read: Dictionary = _access.execute(Schema.APPLY_SERVER_READ_BASELINE, [server_read])
		if not read.ok:
			return read
	if server_comment > old_comment:
		var comment: Dictionary = _access.execute(Schema.APPLY_SERVER_COMMENT_BASELINE, [server_comment])
		if not comment.ok:
			return comment
	return _summary()


func _state_only() -> Dictionary:
	var result: Dictionary = _access.query(Schema.READ_DYNAMICS_STATE)
	if not result.ok:
		return result
	var row: Dictionary = _access.first_row(result)
	if row.is_empty():
		return _failure("CACHE_METADATA_INVALID")
	return _success({"state": _state_dto(row)})


func _load_comments(post_id: String, limit: int) -> Dictionary:
	var post_result: Dictionary = _access.query(Schema.READ_POST, [post_id])
	if not post_result.ok:
		return post_result
	var post: Dictionary = _access.first_row(post_result)
	if post.is_empty():
		return _failure("POST_MISSING")
	var result: Dictionary = _access.query(Schema.READ_COMMENTS, [post_id, limit])
	if not result.ok:
		return result
	return _success({
		"comments": _access.rows_of(result).map(func(row): return _comment_dto(row)),
		"comment_state": {
			"cursor": str(post.comment_cursor),
			"has_more": int(post.comment_has_more) == 1,
			"loaded_at_ms": int(post.comment_loaded_at_ms),
		},
	})


func _summary() -> Dictionary:
	var count_result: Dictionary = _access.query(Schema.UNREAD_POST_COUNT)
	if not count_result.ok:
		return count_result
	var latest_result: Dictionary = _access.query(Schema.LATEST_UNREAD_POST)
	if not latest_result.ok:
		return latest_result
	var comments_result: Dictionary = _access.query(Schema.LOCAL_UNREAD_COMMENTS)
	if not comments_result.ok:
		return comments_result
	var state_result: Dictionary = _access.query(Schema.READ_DYNAMICS_STATE)
	if not state_result.ok:
		return state_result
	var latest_row: Dictionary = _access.first_row(latest_result)
	return _success({
		"state": _state_dto(_access.first_row(state_result)),
		"unread_count": int(_access.first_row(count_result).get("count", 0)),
		"local_unread_comments": int(_access.first_row(comments_result).get("count", 0)),
		"latest_unread": _post_dto(latest_row) if not latest_row.is_empty() else {},
	})


func _post_dto(row: Dictionary) -> Dictionary:
	var dto := _parsed(row.payload_json)
	dto["id"] = str(row.id)
	dto["created_at"] = str(row.created_at)
	dto["author_type"] = str(row.author_type)
	dto["author_id"] = str(row.author_id)
	dto["author_name"] = str(row.author_name)
	dto["content"] = str(row.content)
	dto["allow_comment"] = int(row.allow_comment) == 1
	dto["comment_count"] = int(row.comment_count)
	dto["comment_synced_count"] = int(row.comment_synced_count)
	dto["user_commented"] = int(row.user_commented) == 1
	dto["needs_comment_sync"] = int(row.needs_comment_sync) == 1
	dto["comment_cursor"] = str(row.comment_cursor)
	dto["comment_has_more"] = int(row.comment_has_more) == 1
	dto["comment_loaded_at_ms"] = int(row.comment_loaded_at_ms)
	dto["last_activity_at"] = str(row.last_activity_at)
	dto["last_activity_id"] = str(row.last_activity_id)
	dto["last_activity_kind"] = str(row.last_activity_kind)
	dto["read_activity_at"] = str(row.read_activity_at)
	dto["read_activity_id"] = str(row.read_activity_id)
	return dto


func _comment_dto(row: Dictionary) -> Dictionary:
	var dto := _parsed(row.payload_json)
	dto["id"] = str(row.id)
	dto["dynamic_id"] = str(row.post_id)
	dto["parent_comment_id"] = null if row.parent_comment_id == null else str(row.parent_comment_id)
	dto["created_at"] = str(row.created_at)
	dto["author_type"] = str(row.author_type)
	dto["author_id"] = str(row.author_id)
	dto["author_name"] = str(row.author_name)
	dto["content"] = str(row.content)
	return dto


func _state_dto(row: Dictionary) -> Dictionary:
	return {
		"scope_key": str(row.get("scope_key", "")),
		"server_read_at": str(row.get("server_read_at", "")),
		"server_comment_read_at": str(row.get("server_comment_read_at", "")),
		"posts_cursor": str(row.get("posts_cursor", "")),
		"has_more": int(row.get("has_more", 0)) == 1,
		"refresh_version": int(row.get("refresh_version", 0)),
		"last_sync_ms": int(row.get("last_sync_ms", 0)),
		"revision": int(row.get("revision", 0)),
	}


static func _parsed(raw: Variant) -> Dictionary:
	if raw is String and not str(raw).is_empty():
		var parsed: Variant = JSON.parse_string(raw)
		if parsed is Dictionary:
			return parsed
	return {}


static func _valid_post(item: Dictionary) -> bool:
	for field in ["id", "created_at", "author_type"]:
		if not item.get(field) is String or str(item.get(field, "")).is_empty():
			return false
	return true


static func _valid_comment(item: Dictionary, post_id: String) -> bool:
	for field in ["id", "created_at", "author_type"]:
		if not item.get(field) is String or str(item.get(field, "")).is_empty():
			return false
	if item.get("dynamic_id") is String and str(item.dynamic_id) != post_id:
		return false
	return not item.has("parent_comment_id") or item.parent_comment_id == null or item.parent_comment_id is String


static func _nullable_text(value: Variant) -> Variant:
	if value == null:
		return null
	var text := str(value)
	return null if text.is_empty() else text


static func _tuple_gt(left_at: String, left_id: String, right_at: String, right_id: String) -> bool:
	if left_at != right_at:
		return left_at > right_at
	return left_id > right_id


static func _max_text(left: String, right: String) -> String:
	return left if left >= right else right


static func _flag(value: Variant) -> int:
	return 1 if value == true else 0


static func _now_ms() -> int:
	@warning_ignore("narrowing_conversion")
	return int(Time.get_unix_time_from_system() * 1000.0)


static func _days_ago(days: int) -> String:
	@warning_ignore("narrowing_conversion")
	var wall: int = int(Time.get_unix_time_from_system()
		+ Time.get_time_zone_from_system().bias * 60) - days * 86400
	return Time.get_datetime_string_from_unix_time(wall).replace("T", " ")


static func _failure(code: String) -> Dictionary:
	return {"ok": false, "code": code, "data": {}}


static func _success(data: Dictionary = {}) -> Dictionary:
	return {"ok": true, "code": "OK", "data": data}
