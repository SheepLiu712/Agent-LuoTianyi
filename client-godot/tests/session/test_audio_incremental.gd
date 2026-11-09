extends SceneTree
## 增量迁移的接线：只有「对方的消息」才会被交给迁移端口，且随登录态收口。
##
## 用假的历史控制器发同一组信号，断言的是会话层转发给端口的那批 id，
## 不依赖真实网络或磁盘。

const Session = preload("res://src/session/chat_session.gd")
const Transport = preload("res://src/network/websocket_transport.gd")

var failures: Array[String] = []


class FakeHistory:
	extends Node
	signal page_received(messages: Array[Dictionary])
	signal older_page(messages: Array[Dictionary])
	signal restore_page(messages: Array[Dictionary])
	signal reconciled(messages: Array[Dictionary], position: String)
	signal boundary_ready
	signal state_changed(state: Dictionary)

	func get_state() -> Dictionary:
		return {"storage": "closed", "count": 0, "incomplete": false}

	func start(_session: Dictionary) -> void:
		pass

	func stop() -> void:
		pass

	func load_older() -> void:
		pass

	func pause_catchup(_paused: bool) -> void:
		pass


class FakeMigration:
	extends RefCounted
	var requested: Array = []
	var stops := 0

	func request_ids(ids: Array) -> void:
		requested.append_array(ids)

	func stop() -> void:
		stops += 1

	func get_state() -> Dictionary:
		return {"mode": "idle", "busy": false}

	func is_busy() -> bool:
		return false


func _initialize() -> void:
	run.call_deferred()


func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)


func run() -> void:
	var history := FakeHistory.new()
	var session = Session.new(Transport.new(), null, null, history)
	root.add_child(session)
	var migration := FakeMigration.new()
	session.set_audio_migration(migration)
	var page: Array[Dictionary] = [
		{"id": "agent-1", "role": "assistant", "text": "一", "type": "text", "timestamp": 1.0},
		{"id": "user-1", "role": "user", "text": "二", "type": "text", "timestamp": 2.0},
		{"id": "agent-2", "role": "assistant", "text": "三", "type": "text", "timestamp": 3.0},
	]
	history.page_received.emit(page)
	check(migration.requested == ["agent-1", "agent-2"], "first page forwards assistant ids only")
	migration.requested.clear()
	history.older_page.emit(page)
	check(migration.requested == ["agent-1", "agent-2"], "scrolling up forwards the older page")
	migration.requested.clear()
	history.restore_page.emit(page)
	check(migration.requested == ["agent-1", "agent-2"], "restored window also asks for its audio")
	session.stop()
	check(migration.stops == 1, "logging out stops the migrator before the scope changes")
	session.queue_free()
	await process_frame
	print("Audio incremental: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
