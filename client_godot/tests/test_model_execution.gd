extends SceneTree
var failures: Array[String] = []
var responses := {}
func check(value: bool,text: String) -> void:
	if not value:
		failures.append(text)
		print("FAIL: ",text)
func _initialize() -> void:
	_run.call_deferred()
func wait_for(id: String) -> void:
	for tick in 400:
		if responses.has(id):
			return
		await create_timer(0.01).timeout
	check(false,"response timeout: "+id)
func _run() -> void:
	if not ResourceLoader.exists("res://src/session/model_executor.gd"):
		check(false,"model delegation executor available")
		quit(1)
		return
	var directory := "user://executor-test-%s"%Time.get_ticks_usec()
	var settings = load("res://src/session/model_settings.gd").new(load("res://src/network/json_request.gd").new(),load("res://src/storage/model_store.gd").new(ClassDB.instantiate("WindowsSecurity"),directory))
	root.add_child(settings)
	var base := OS.get_environment("GODOT_TEST_SERVER")
	await settings.start({"server":base,"username":"executor"})
	var config: Dictionary = settings.get_config("text-purpose")
	config.merge({"enabled":true,"base_url":base+"/v1","api_key":"SYNTHETIC_KEY","model":"snapshot","params":{"temperature":0.25,"model":"cannot-override","messages":[]}},true)
	config.model_capabilities = {"can_use_json":true,"can_enable_thinking":true}
	check(settings.save("text-purpose",config).ok,"executor config saved")
	var vision: Dictionary = settings.copy_config(config,"vision-purpose")
	check(settings.save("vision-purpose",vision).ok,"vision config saved")
	var executor = load("res://src/session/model_executor.gd").new(settings,null,0.2)
	root.add_child(executor)
	executor.start()
	executor.completed.connect(func(result): responses[result.request_id] = result)
	var request := {"request_id":"one","type":"text-purpose","model_kind":"llm","prompt":"fixed-private-prompt","params":{"temperature":0.9,"stop":["END"]},"use_json":true,"enable_thinking":true}
	executor.submit(request)
	executor.submit(request)
	config.model = "changed"
	settings.save("text-purpose",config)
	await wait_for("one")
	check(responses.one.get("content") == '{"answer":"ok"}',"JSON content returned")
	check(responses.one.get("usage") == {"total_tokens":3},"only token usage metrics returned")
	executor.submit(request)
	var image_request := request.duplicate(true)
	var fixture_image := Image.create(2, 2, false, Image.FORMAT_RGB8)
	fixture_image.fill(Color("66ccff"))
	image_request.merge({"request_id":"image","type":"vision-purpose","model_kind":"vlm","image_base64":"data:image/png;base64," + Marshalls.raw_to_base64(fixture_image.save_png_to_buffer())},true)
	executor.submit(image_request)
	await wait_for("image")
	var external_image := image_request.duplicate(true)
	external_image.request_id = "external-image"
	external_image.image_base64 = "https://example.invalid/image.png"
	executor.submit(external_image)
	await wait_for("external-image")
	check(responses["external-image"].get("error") == "IMAGE_FORMAT", "model rejects external image URL")
	var malformed_image := image_request.duplicate(true)
	malformed_image.request_id = "malformed-image"
	malformed_image.image_base64 = "data:image/png;base64,not-base64!"
	executor.submit(malformed_image)
	await wait_for("malformed-image")
	check(responses["malformed-image"].get("error") == "IMAGE_FORMAT", "model rejects malformed image data URI")
	var http = load("res://src/network/json_request.gd").new()
	root.add_child(http)
	var stats: Dictionary = await http.send(base+"/provider-stats",HTTPClient.METHOD_GET)
	check(stats.data.calls.size()==2,"duplicate ID never repeats supplier request")
	check(stats.data.calls[0].model == "snapshot" and stats.data.calls[0].temperature == 0.25,"inflight snapshot and local parameter precedence")
	check(stats.data.calls[0].messages == [{"role":"system","content":"fixed-private-prompt"}],"advanced parameters cannot override prompt")
	check(stats.data.calls[0].stop == ["END"] and stats.data.calls[0].response_format.type == "json_object","request parameters and JSON enforcement")
	check(stats.data.calls[1].messages[0].content[1].image_url.detail == "auto","VLM image payload")
	for scenario in ["bad-json","error","slow"]:
		config.model = scenario
		settings.save("text-purpose",config)
		request.request_id = scenario
		executor.submit(request)
		await wait_for(scenario)
		check(responses[scenario].get("error") == {"bad-json":"INVALID_JSON","error":"HTTP_ERROR","slow":"TIMEOUT"}[scenario],"safe error: "+scenario)
	request.request_id = "cancel"
	executor.submit(request)
	executor.stop()
	await create_timer(0.3).timeout
	check(not responses.has("cancel"),"logout isolates late callback")
	executor.start()
	config.model = "manual"
	var tested: Dictionary = await executor.test_config("text-purpose",config)
	check(tested.ok and not tested.has("content"),"manual fixed probe returns status only")
	settings.save("text-purpose",config)
	var chat = load("res://src/session/chat_session.gd").new(load("res://src/network/websocket_transport.gd").new(),null,null,null,null,null,load("res://src/session/model_executor.gd").new(settings))
	root.add_child(chat)
	chat.start({"server":base,"username":"executor","message_token":"message-test"})
	for tick in 200:
		if chat.get_state().phase == "ready":
			break
		await create_timer(0.01).timeout
	check(not chat.send_text("fixture user text").is_empty(),"chat sends with enabled purpose advertisement")
	for tick in 200:
		stats = await http.send(base+"/provider-stats",HTTPClient.METHOD_GET)
		if not stats.data.delegated.is_empty():
			break
		await create_timer(0.01).timeout
	check(stats.data.delegated.size()==1 and stats.data.delegated[0].get("request_id")=="ws-delegate" and stats.data.delegated[0].has("content"),"real WS request executes and returns llm_response")
	chat.queue_free()
	executor.queue_free()
	settings.queue_free()
	http.queue_free()
	await process_frame
	for folder in DirAccess.get_directories_at(directory):
		for file in DirAccess.get_files_at(directory.path_join(folder)):
			DirAccess.remove_absolute(directory.path_join(folder).path_join(file))
		DirAccess.remove_absolute(directory.path_join(folder))
	DirAccess.remove_absolute(directory)
	print("Model execution: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
