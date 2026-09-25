extends SceneTree
const Chat = preload("res://src/session/chat_session.gd")
const Transport = preload("res://src/network/websocket_transport.gd")
var failures: Array[String] = []
var expressions := 0
func check(value: bool, text: String) -> void:
	if not value:
		failures.append(text)
		print("FAIL: ",text)
func until(predicate: Callable) -> bool:
	var deadline := Time.get_ticks_msec()+4000
	while not predicate.call() and Time.get_ticks_msec()<deadline:
		await process_frame
	return predicate.call()
func _initialize() -> void:
	_run.call_deferred()
func credentials(user: String) -> Dictionary:
	return {"server":OS.get_environment("GODOT_TEST_SERVER"),"username":user,"message_token":"message-test"}
func _run() -> void:
	var probe = Chat.new(Transport.new())
	check(probe.has_method("get_history_state"),"chat exposes history synchronization and send barrier")
	probe.free()
	if not failures.is_empty():
		quit(1)
		return
	var api = load("res://src/network/history_api.gd").new()
	var history = load("res://src/session/history_sync.gd").new(api)
	var chat_script: Variant = Chat
	var chat = chat_script.new(Transport.new(),null,null,history)
	root.add_child(chat)
	chat.expression_requested.connect(func(_command): expressions+=1)
	chat.start(credentials("normal"))
	var id: String = chat.send_text("queued before initial boundary")
	check(not id.is_empty() and chat.get_messages()[0].status == "waiting_history","local bubble appears immediately while send held")
	check(await until(func(): return chat.get_state().phase == "ready"),"authentication works while history pending")
	check(await until(func(): return chat.get_history_state().phase == "complete"),"loads entire fixed history")
	check(await until(func(): return chat.get_messages().any(func(m): return m.id == id and m.status == "sent")),"queued message ACK retains stable local ID")
	var messages: Array = chat.get_messages()
	check(messages.size() == 121,"UUID merges live assistant without duplicate; local user is distinct")
	check(messages[0].id == "history-0" and messages[119].id == "history-119","history is oldest first")
	check(messages[119].text == "live reply","live assistant text takes precedence")
	check(expressions == 0 and not chat.get_audio_state().playing,"history does not trigger avatar or playback")
	chat.start(credentials("first_fail"))
	id = chat.send_text("retain this")
	check(await until(func(): return chat.get_history_state().phase == "first_failed"),"initial failure reported")
	check(chat.get_messages()[0].id == id and chat.get_messages()[0].status == "waiting_history","initial failure retains pending sends")
	chat.retry_history()
	check(await until(func(): return chat.get_history_state().phase == "complete"),"retry initial failure succeeds")
	chat.start(credentials("skip"))
	id = chat.send_text("skip queued")
	await until(func(): return chat.get_history_state().phase == "first_failed")
	chat.skip_history()
	check(await until(func(): return chat.get_messages().any(func(m): return m.id == id and m.status == "sent")),"skip releases pending message")
	check(chat.get_history_state().phase == "skipped" and chat.get_messages().size() == 2,"skip doesn't import histories")
	chat.start(credentials("late_fail"))
	check(await until(func(): return chat.get_history_state().phase == "failed"),"later page failure explicit")
	check(chat.get_messages().size() == 50,"later failure keeps first page")
	id = chat.send_text("allowed after boundary")
	check(not id.is_empty() and chat.get_messages()[-1].status != "waiting_history","later error doesn't block send")
	chat.retry_history()
	check(await until(func(): return chat.get_history_state().phase == "complete"),"retry resumes fixed older boundary")
	chat.start(credentials("invalid"))
	check(await until(func(): return chat.get_history_state().phase == "first_failed"),"bad boundary rejects page")
	check(chat.get_messages().is_empty(),"bad history doesn't leak partial page")
	chat.start(credentials("duplicate"))
	check(await until(func(): return chat.get_history_state().phase == "complete"),"duplicate pagination settles")
	check(chat.get_history_state().incomplete and chat.get_messages().size() == 119,"duplicate explicit and UUID deduplicated")
	chat.start(credentials("late_cancel"))
	await create_timer(.1).timeout
	chat.stop()
	await create_timer(.35).timeout
	check(chat.get_messages().is_empty() and chat.get_history_state().phase == "idle","cancel isolates late history results")
	chat.start(credentials("old_account"))
	await create_timer(.1).timeout
	chat.start(credentials("replacement"))
	check(await until(func(): return chat.get_history_state().phase == "complete"),"new account sync completes after cancellation")
	check(not JSON.stringify(chat.get_messages()).contains("old_account"),"late previous account body never enters new account")
	chat.queue_free()
	await process_frame
	print("History sync: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
