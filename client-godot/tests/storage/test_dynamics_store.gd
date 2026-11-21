extends SceneTree
## 动态缓存：独立活动水位、已读推进、同秒仲裁、评论游标与页内清理。

const Database = preload("res://src/storage/sqlite_history_database.gd")

var failures: Array[String] = []
var _root := ""


func _initialize() -> void:
	run.call_deferred()


func run() -> void:
	_root = "user://test-dynamics-store-%d" % Time.get_ticks_usec()
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(_root))
	_case_unread_watermarks()
	_case_comment_activity()
	_case_same_second_order()
	_case_prebaseline_activity()
	_case_cursor_and_sync()
	_case_baseline_monotonic()
	_case_page_prune()
	print("Dynamics store: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func check(ok: bool, label: String) -> void:
	if ok:
		return
	failures.append(label)
	print("FAIL: ", label)


func _scope(tag: String) -> String:
	return (tag + "0".repeat(64)).substr(0, 64)


func _open(scope: String) -> RefCounted:
	var database = Database.new()
	var opened: Dictionary = database.open(_root, scope)
	check(opened.ok, "open scope (%s)" % opened.code)
	return database


func _execute(database: RefCounted, operation: String, scope: String, extra: Dictionary = {}) -> Dictionary:
	var payload := {"scope": scope}
	payload.merge(extra, true)
	return database.execute(operation, payload)


func _post(id: String, created: String, author_type: String = "agent", count: int = 0) -> Dictionary:
	return {
		"id": id, "created_at": created, "author_type": author_type,
		"author_id": "luotianyi" if author_type == "agent" else "u1",
		"author_name": "洛天依" if author_type == "agent" else "用户",
		"content": "post " + id, "allow_comment": true, "comment_count": count,
		"source_type": "diary",
	}


func _comment(id: String, post_id: String, created: String, author_type: String = "agent") -> Dictionary:
	return {
		"id": id, "dynamic_id": post_id, "created_at": created,
		"author_type": author_type, "author_id": "a1", "author_name": "洛天依",
		"content": "comment " + id, "parent_comment_id": null,
	}


func _case_unread_watermarks() -> void:
	var scope := _scope("a")
	var database := _open(scope)
	var saved: Dictionary = _execute(database, "dynamics_save_posts", scope, {
		"rows": [
			_post("d0", "2026-09-19 10:00:00", "agent", 0),
			_post("d1", "2026-09-19 10:01:00", "agent", 0),
			_post("d2", "2026-09-19 10:02:00", "user", 0),
		],
	})
	check(saved.ok, "seed posts")
	check(int(saved.data.unread_count) == 2, "agent/system posts start unread")
	check(str(saved.data.latest_unread.id) == "d1", "latest unread is the newest activity")
	var posts: Dictionary = _execute(database, "dynamics_load", scope)
	check(posts.data.posts.size() == 3, "feed order is returned")
	check(str(posts.data.posts[0].id) == "d2", "feed is newest first")
	check(str(posts.data.posts[2].id) == "d0", "oldest post is last")
	var one: Dictionary = _execute(database, "dynamics_mark_read", scope, {"post_id": "d1"})
	check(int(one.data.unread_count) == 1, "single read clears one post")
	var all: Dictionary = _execute(database, "dynamics_mark_read", scope, {})
	check(int(all.data.unread_count) == 0 and all.data.latest_unread.is_empty(), "mark all clears the badge and preview")
	var user_only: Dictionary = _execute(database, "dynamics_save_posts", scope, {
		"rows": [_post("d3", "2026-09-19 10:03:00", "user", 0)],
	})
	check(int(user_only.data.unread_count) == 0, "own posts never become unread")
	database.close()


func _case_comment_activity() -> void:
	var scope := _scope("b")
	var database := _open(scope)
	_execute(database, "dynamics_save_posts", scope, {
		"rows": [
			_post("d0", "2026-09-19 10:00:00", "agent", 2),
			_post("d1", "2026-09-19 10:01:00", "agent", 0),
		],
	})
	_execute(database, "dynamics_mark_read", scope, {})
	var comment: Dictionary = _execute(database, "dynamics_save_comments", scope, {
		"post_id": "d0",
		"rows": [_comment("c1", "d0", "2026-09-19 10:05:00")],
		"cursor": "c1",
		"has_more": false,
	})
	check(comment.ok, "comment page saves")
	check(int(comment.data.unread_count) == 1, "a reply to an old post makes it unread again")
	var loaded: Dictionary = _execute(database, "dynamics_load", scope, {"post_id": "d0"})
	check(str(loaded.data.comments[0].id) == "c1", "comment is cached")
	check(str(loaded.data.comments[0].dynamic_id) == "d0", "comment carries its post id")
	# 用户自评不推进活动水位。
	var own: Dictionary = _execute(database, "dynamics_save_comments", scope, {
		"post_id": "d0",
		"rows": [_comment("c2", "d0", "2026-09-19 10:06:00", "user")],
		"cursor": "c2",
		"has_more": false,
		"user_written": true,
	})
	check(own.ok, "user comment saves")
	var post: Array = _execute(database, "dynamics_load", scope, {"post_id": "d0"}).data.comments
	check(post.size() == 2, "user comment is cached")
	var row: Dictionary = database._access.first_row(database._access.query("SELECT * FROM dynamic_posts WHERE id='d0'"))
	check(int(row.user_commented) == 1, "user participation is recorded")
	check(str(row.last_activity_id) == "c1", "user comment does not move the activity watermark")
	check(int(row.comment_count) == 3 and int(row.comment_synced_count) == 1, "user comment increments both counters")
	# Agent 回复用户评论 → 重新未读。
	var reply: Dictionary = _execute(database, "dynamics_save_comments", scope, {
		"post_id": "d0",
		"rows": [_comment("c3", "d0", "2026-09-19 10:07:00")],
		"cursor": "c3",
		"has_more": false,
	})
	check(int(reply.data.unread_count) == 1, "agent reply keeps the post unread")
	_execute(database, "dynamics_mark_read", scope, {"post_id": "d0"})
	var read_row: Dictionary = database._access.first_row(database._access.query("SELECT * FROM dynamic_posts WHERE id='d0'"))
	check(str(read_row.read_activity_id) == "c3", "reading the detail clears the activity watermark")
	database.close()


func _case_cursor_and_sync() -> void:
	var scope := _scope("c")
	var database := _open(scope)
	_execute(database, "dynamics_save_posts", scope, {"rows": [_post("d0", "2026-09-19 10:00:00", "agent", 5)]})
	var first: Dictionary = _execute(database, "dynamics_save_comments", scope, {
		"post_id": "d0",
		"rows": [_comment("c1", "d0", "2026-09-19 10:01:00")],
		"cursor": "page-2",
		"has_more": true,
	})
	check(first.ok, "first comment page")
	var loaded: Dictionary = _execute(database, "dynamics_load", scope, {"post_id": "d0"})
	check(str(loaded.data.comment_state.cursor) == "page-2" and bool(loaded.data.comment_state.has_more), "cursor and has_more persist")
	var second: Dictionary = _execute(database, "dynamics_save_comments", scope, {
		"post_id": "d0",
		"rows": [_comment("c2", "d0", "2026-09-19 10:02:00")],
		"cursor": "page-3",
		"has_more": false,
		"mark_synced": true,
	})
	check(second.ok, "second comment page")
	var row: Dictionary = database._access.first_row(database._access.query("SELECT * FROM dynamic_posts WHERE id='d0'"))
	check(str(row.comment_cursor) == "page-3" and int(row.comment_has_more) == 0, "final cursor is retained even without more pages")
	check(int(row.comment_synced_count) == int(row.comment_count), "mark_synced aligns the counters")
	check(int(row.needs_comment_sync) == 0, "mark_synced clears the flag")
	database.close()


func _case_same_second_order() -> void:
	var scope := _scope("6")
	var database := _open(scope)
	_execute(database, "dynamics_save_posts", scope, {
		"rows": [_post("same", "2026-09-19 10:00:00", "agent", 2)],
	})
	_execute(database, "dynamics_mark_read", scope, {})
	_execute(database, "dynamics_save_comments", scope, {
		"post_id": "same",
		"rows": [
			_comment("c8", "same", "2026-09-19 10:10:00"),
			_comment("c9", "same", "2026-09-19 10:10:00"),
		],
		"cursor": "c9",
		"has_more": false,
	})
	var row: Dictionary = database._access.first_row(
		database._access.query("SELECT * FROM dynamic_posts WHERE id='same'"))
	check(str(row.last_activity_id) == "c9", "same-second activity uses the larger id")
	_execute(database, "dynamics_mark_read", scope, {"post_id": "same"})
	var read: Dictionary = database._access.first_row(
		database._access.query("SELECT * FROM dynamic_posts WHERE id='same'"))
	check(str(read.read_activity_id) == "c9", "same-second read watermark matches activity")
	var next: Dictionary = _execute(database, "dynamics_save_comments", scope, {
		"post_id": "same",
		"rows": [_comment("z0", "same", "2026-09-19 10:10:00")],
		"cursor": "z0",
		"has_more": false,
	})
	check(int(next.data.unread_count) == 1, "same-second reply after reading is unread again")
	check(int(next.data.local_unread_comments) == 1, "local unread comments use the id tie-break")
	var last: Dictionary = database._access.first_row(
		database._access.query("SELECT * FROM dynamic_posts WHERE id='same'"))
	check(str(last.last_activity_id) == "z0" and str(last.read_activity_id) == "c9",
		"same-second activity and read watermarks stay distinct")
	database.close()


## 基线之前的非本人动态：活动水位仍记录该动态，只是已读水位同步到基线。
func _case_prebaseline_activity() -> void:
	var scope := _scope("7")
	var database := _open(scope)
	_execute(database, "dynamics_state", scope, {
		"patch": {"server_read_at": "2026-09-19 12:00:00"},
	})
	var saved: Dictionary = _execute(database, "dynamics_save_posts", scope, {
		"rows": [_post("old", "2026-09-19 10:00:00", "agent", 0)],
	})
	check(saved.ok and int(saved.data.unread_count) == 0, "pre-baseline post starts read")
	var row: Dictionary = database._access.first_row(
		database._access.query("SELECT * FROM dynamic_posts WHERE id='old'"))
	check(str(row.last_activity_at) == "2026-09-19 10:00:00",
		"pre-baseline post still records its activity")
	check(str(row.last_activity_id) == "old" and str(row.last_activity_kind) == "post",
		"pre-baseline activity carries the composite tuple")
	check(str(row.read_activity_at) == str(row.last_activity_at)
		and str(row.read_activity_id) == str(row.last_activity_id),
		"pre-baseline activity is already read")
	database.close()


func _case_baseline_monotonic() -> void:
	var scope := _scope("d")
	var database := _open(scope)
	_execute(database, "dynamics_save_posts", scope, {
		"rows": [
			_post("d0", "2026-09-19 10:00:00", "agent", 0),
			_post("d1", "2026-09-19 11:00:00", "agent", 0),
		],
	})
	var forward: Dictionary = _execute(database, "dynamics_state", scope, {
		"patch": {"server_read_at": "2026-09-19 10:30:00", "server_comment_read_at": "2026-09-19 10:30:00"},
	})
	check(int(forward.data.unread_count) == 1, "server baseline clears older activity")
	check(str(forward.data.state.server_read_at) == "2026-09-19 10:30:00", "server baseline is stored")
	var backward: Dictionary = _execute(database, "dynamics_state", scope, {
		"patch": {"server_read_at": "2026-09-19 09:00:00"},
	})
	check(str(backward.data.state.server_read_at) == "2026-09-19 10:30:00", "server baseline never moves backward")
	check(int(backward.data.unread_count) == 1, "re-lighting on an old response is impossible")
	database.close()


func _case_page_prune() -> void:
	var scope := _scope("e")
	var database := _open(scope)
	_execute(database, "dynamics_save_posts", scope, {
		"rows": [
			_post("d0", "2026-09-19 10:00:00"),
			_post("d1", "2026-09-19 10:01:00"),
			_post("d2", "2026-09-19 10:02:00"),
		],
	})
	var refreshed: Dictionary = _execute(database, "dynamics_save_posts", scope, {
		"rows": [
			_post("d0", "2026-09-19 10:00:00"),
			_post("d2", "2026-09-19 10:02:00"),
		],
		"prune": true,
	})
	check(refreshed.ok, "refresh page saves")
	var posts: Dictionary = _execute(database, "dynamics_load", scope)
	var ids: Array = posts.data.posts.map(func(post): return str(post.id))
	check(ids == ["d2", "d0"], "posts missing from the refreshed range are removed")
	database.close()
