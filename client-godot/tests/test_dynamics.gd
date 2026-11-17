extends SceneTree
## 动态控制器：本地缓存优先、活动水位、分页/评论增量与失败隔离。

const Worker = preload("res://src/storage/sqlite_worker.gd")
const Database = preload("res://src/storage/sqlite_history_database.gd")
const ScopeSession = preload("res://src/storage/scope_session.gd")
const DynamicsPersistence = preload("res://src/session/dynamics_persistence.gd")
const Controller = preload("res://src/session/dynamics_controller.gd")

var failures: Array[String] = []
var _root := ""
var _worker: Node
var _scope_session: RefCounted
var _persistence: RefCounted
var _controller: Node


func check(value: bool, text: String) -> void:
	if not value:
		failures.append(text)
		print("FAIL: ", text)


func _initialize() -> void:
	_run.call_deferred()


func _run() -> void:
	_root = "user://test-dynamics-%d" % Time.get_ticks_usec()
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(_root))
	_worker = Worker.new(func() -> RefCounted: return Database.new())
	root.add_child(_worker)
	_worker.start()
	_scope_session = ScopeSession.new(_worker)
	_persistence = DynamicsPersistence.new(_scope_session)
	_controller = Controller.new(null, _persistence)
	root.add_child(_controller)
	_controller.set_history_root(_root)
	await _case_cache_first()
	await _case_paging_and_comments()
	await _case_writes()
	await _case_account_scope()
	await _case_failures()
	_controller.stop()
	_worker.begin_shutdown()
	_worker.wait_to_finish()
	print("Dynamics: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func _session(username: String) -> Dictionary:
	return {
		"server": OS.get_environment("GODOT_TEST_SERVER"),
		"username": username,
		"message_token": "fixture-token",
		"history_root": _root,
	}


func _posts() -> Array:
	return _controller.get_posts()


func _post_id(index: int = 0) -> String:
	var posts: Array = _posts()
	return "" if index >= posts.size() else str(posts[index].id)


func _case_cache_first() -> void:
	await _controller.start(_session("cold"))
	var state: Dictionary = _controller.get_state()
	check(state.unread == 12, "cold start uses the server dynamic count")
	check(state.unread_hint, "cold start hints that uncached replies exist")
	check(_posts().is_empty(), "cold start does not fabricate posts")
	check(_controller.get_latest_unread().is_empty(), "cold start has no local preview")
	await _controller.refresh()
	state = _controller.get_state()
	check(_posts().size() == 10, "refresh caches the first page")
	check(state.unread == 10, "badge counts unread posts, not comments")
	check(state.unread_hint, "server reports more unread than the cached page")
	check(str(_controller.get_latest_unread().id) == "d9", "newest cached activity is the preview")
	check(_controller.is_unread(_posts()[0]), "agent post is unread")
	await _controller.mark_post_read(_post_id())
	check(_controller.get_state().unread == 9, "reading one post clears one badge unit")
	check(not _controller.is_unread(_posts()[0]), "the opened post becomes read")
	await _controller.mark_read()
	check(_controller.get_state().unread == 0, "mark all clears the local badge")
	check(_controller.get_latest_unread().is_empty(), "mark all clears the preview")


func _case_paging_and_comments() -> void:
	await _controller.start(_session("paging"))
	await _controller.refresh()
	check(_posts().size() == 10 and _controller.get_state().has_more, "first page keeps the older cursor")
	await _controller.load_more()
	check(_posts().size() == 12 and not _controller.get_state().has_more, "opaque cursor paging deduplicates posts")
	await _controller.load_comments("d0")
	var comments: Dictionary = _controller.get_comments("d0")
	check(comments.items.size() == 20 and comments.has_more, "comments first page")
	await _controller.refresh_comments("d0")
	comments = _controller.get_comments("d0")
	check(comments.items.size() == 22 and not comments.has_more, "incremental refresh reaches replies beyond the first page")
	await _controller.load_comments("d0", true)
	check(_controller.get_comments("d0").items.size() == 22, "comment page merge is idempotent")
	_check_unread_semantics()


func _check_unread_semantics() -> void:
	check(_controller.is_unread({"author_type": "agent", "created_at": "2026-09-19 10:00:00"}), "posts after the read mark are unread")
	check(not _controller.is_unread({"author_type": "agent", "created_at": "2026-09-18 09:00:00"}), "posts before the read mark are read")
	check(not _controller.is_unread({"author_type": "user", "created_at": "2026-09-19 10:00:00"}), "own posts are never unread")


func _case_writes() -> void:
	await _controller.start(_session("writer"))
	await _controller.refresh()
	await _controller.load_comments("d0")
	var published: Dictionary = await _controller.publish("published text")
	check(published.ok, "text publishing succeeds")
	check(_posts()[0].content == "published text", "published item is displayed first")
	var replied: Dictionary = await _controller.comment("d0", "reply text", "c0")
	check(replied.ok, "reply succeeds")
	check(_controller.get_comments("d0").items[-1].parent_comment_id == "c0", "reply target is preserved")
	await _controller.load_comments("d0", true)
	check(_controller.get_comments("d0").items[-1].id == "c99", "new comment stays after the cached page")
	check(not (await _controller.comment("d1", "forbidden")).ok, "read-only post refuses comment")
	check(not (await _controller.comment("d0", "wrong parent", "missing")).ok, "unknown reply target is refused")


func _case_account_scope() -> void:
	for user in ["private-a", "private-b"]:
		await _controller.start(_session(user))
		await _controller.refresh()
		await _controller.load_comments("d0")
		var expected := 2 if user == "private-a" else 1
		var comments: Dictionary = _controller.get_comments("d0")
		check(_posts()[0].comment_count == expected and comments.items.size() == expected,
			"same public post has account-scoped count")
		check(comments.items.all(func(item): return item.owner_user_id == user),
			"relogin retains no prior private comments")


func _case_failures() -> void:
	await _controller.start(_session("fail-first-page"))
	await _controller.refresh()
	check(_controller.get_state().code == "HTTP_ERROR" and _posts().is_empty(), "first page failure is explicit")
	await _controller.start(_session("fail-unread"))
	await _controller.refresh_unread()
	check(_controller.get_state().unread_code == "HTTP_ERROR", "failed unread poll is reported")
	check(_controller.get_state().unread == 12, "failed unread poll preserves the known count")
	await _controller.start(_session("fail-write"))
	await _controller.refresh()
	await _controller.mark_read()
	check(_controller.get_state().unread == 0, "local mark all stays applied when the server write fails")
	check(_controller.get_state().unread_code == "HTTP_ERROR", "failed mark-all is reported")
	check(_controller.get_latest_unread().is_empty(), "failed mark-all does not re-light the preview")
	await _controller.start(_session("comments-only"))
	check(_controller.get_state().unread == 0, "comment-only unread does not inflate the badge")
	check(_controller.get_state().unread_hint, "comment-only unread exposes the generic hint")
	await _controller.start(_session("slow-comments"))
	await _controller.refresh()
	_controller.refresh_comments("d0")
	_controller.stop()
	await create_timer(0.6).timeout
	check(_controller.get_comments("d0").items.is_empty(), "logout isolates a late comment refresh")
	_controller.start(_session("slow"))
	_controller.stop()
	await create_timer(0.6).timeout
	check(_posts().is_empty() and _controller.get_state().unread == 0, "logout isolates pending reads")
