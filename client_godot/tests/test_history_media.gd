extends SceneTree
const VIEW_SCENE := "res://scenes/ui/chat_view.tscn"
var failures: Array[String] = []
func check(value: bool,text: String) -> void:
	if not value:
		failures.append(text)
		print("FAIL: ",text)
func until(predicate: Callable) -> bool:
	var end := Time.get_ticks_msec()+2500
	while not predicate.call() and Time.get_ticks_msec()<end:
		await process_frame
	return predicate.call()
func _initialize() -> void:
	_run.call_deferred()
func _run() -> void:
	check(ResourceLoader.exists("res://src/storage/history_images.gd"),"history images recover by UUID")
	if not failures.is_empty():
		quit(1)
		return
	var directory := "user://images-test-%s"%Time.get_ticks_usec()
	var script = load("res://src/storage/history_images.gd")
	var images = script.new(directory)
	root.add_child(images)
	var scope := {"server":OS.get_environment("GODOT_TEST_SERVER"),"username":"images","message_token":"message-test"}
	images.start(scope)
	check(images.get_state("sample").status == "idle","nothing downloaded before visibility")
	images.ensure("sample")
	check(await until(func(): return images.get_state("sample").status == "ready"),"actual image HTTP bytes decode")
	check(images.get_state("sample").get("original_size") == Vector2i(2,2), "download carries original pixel size")
	check(images.preview("sample").get_size() == Vector2(2,2),"in-client preview uses original image")
	images.stop()
	images.start(scope)
	images.ensure("sample")
	check(await until(func(): return images.get_state("sample").status == "ready"),"scope restart restores disk image without request")
	check(images.get_state("sample").get("original_size") == Vector2i(2,2), "disk restore recovers original pixel size")
	images.ensure("broken")
	check(await until(func(): return images.get_state("broken").status == "error"),"bad image explicit failure")
	images.retry("broken")
	check(await until(func(): return images.get_state("broken").status == "ready"),"explicit retry recovers image")
	images.ensure("slow")
	await create_timer(.05).timeout
	images.stop()
	var other := scope.duplicate()
	other.username = "other"
	images.start(other)
	images.ensure("sample")
	check(await until(func(): return images.get_state("sample").status == "ready"),"new account fetches own image")
	await create_timer(.35).timeout
	check(images.get_state("slow").status == "idle","old account late image ignored")
	images.queue_free()
	await process_frame
	var cache = load("res://src/storage/audio_cache.gd").new(directory+"/audio")
	cache.set_scope(scope.server,scope.username)
	var bytes: PackedByteArray = load("res://tests/support/audio_samples.gd").tone(.2)
	var decoder = ClassDB.instantiate("PcmStreamDecoder")
	decoder.append(bytes)
	decoder.finish()
	cache.begin("history-119")
	cache.append("history-119",bytes)
	check(cache.commit("history-119",decoder.get_status(),decoder.get_waveform(24)) == OK,"seed actual complete voice cache")
	var history = load("res://src/session/history_sync.gd").new(load("res://src/network/history_api.gd").new())
	var chat = load("res://src/session/chat_session.gd").new(load("res://src/network/websocket_transport.gd").new(),null,load("res://tests/support/native_reply_audio.gd").new(null,Callable(),cache),history,null,script.new(directory+"/chat_images"))
	root.add_child(chat)
	chat.start(scope)
	check(await until(func(): return chat.get_history_state().phase == "complete"),"media messages restored from real history")
	check(not JSON.stringify(chat.get_messages()).contains("old-device"),"old absolute image paths discarded")
	check(chat.get_message_audio("history-119").available and not chat.get_message_audio("history-117").available,"history exposes only actual new-client voice cache")
	check(not chat.get_audio_state().playing,"cached history never auto-plays")
	root.size = Vector2i(1200,800)
	check(ResourceLoader.exists(VIEW_SCENE),"chat view scene exists")
	if not ResourceLoader.exists(VIEW_SCENE):
		quit(1)
		return
	var view = load(VIEW_SCENE).instantiate()
	var presenter = load("res://src/ui/image_presenter.gd").new(load("res://src/storage/window_geometry.gd").new(directory+"/geometry.cfg"),load("res://src/platform/godot_window_system.gd").new())
	root.add_child(presenter)
	view.image_requested.connect(func(provider): presenter.open_image(root,provider))
	view.setup(chat)
	root.add_child(view)
	view.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	await process_frame
	var list: Node = view.find_children("*","ScrollContainer",true,false).filter(func(n): return n.has_method("scroll_to_message"))[0]
	list.scroll_to_message("history-116")
	check(await until(func(): return chat.get_message_image("history-116").status == "ready"),"visible history image downloads through chat boundary")
	var preview_buttons: Array = view.find_children("*","Button",true,false).filter(func(n): return n.text == "打开原图")
	check(not preview_buttons.is_empty(),"real thumbnail offers preview")
	if not preview_buttons.is_empty():
		preview_buttons[0].pressed.emit()
		check(root.find_children("ImageWindow","Window",true,false).any(func(n): return n.visible),"image preview opens in the shared window")
	presenter.queue_free()
	view.queue_free()
	chat.queue_free()
	await process_frame
	cache.set_scope(scope.server,scope.username)
	cache.clear()
	for category in ["audio","chat_images"]:
		for child in DirAccess.get_directories_at(directory+"/"+category):
			for file in DirAccess.get_files_at(directory+"/"+category+"/"+child):
				DirAccess.remove_absolute(directory+"/"+category+"/"+child+"/"+file)
			DirAccess.remove_absolute(directory+"/"+category+"/"+child)
		DirAccess.remove_absolute(directory+"/"+category)
	for folder in DirAccess.get_directories_at(directory):
		for file in DirAccess.get_files_at(directory.path_join(folder)):
			DirAccess.remove_absolute(directory.path_join(folder).path_join(file))
		DirAccess.remove_absolute(directory.path_join(folder))
	DirAccess.remove_absolute(directory)
	print("History media: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
