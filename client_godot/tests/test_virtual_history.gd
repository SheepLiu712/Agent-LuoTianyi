extends SceneTree
var failures: Array[String] = []
func check(value: bool,text: String) -> void:
	if not value:
		failures.append(text)
		print("FAIL: ",text)
func _initialize() -> void:
	_run.call_deferred()
func _run() -> void:
	check(ResourceLoader.exists("res://scenes/ui/virtual_message_list.tscn"),"history has virtual message list")
	if not failures.is_empty():
		quit(1)
		return
	var list = load("res://scenes/ui/virtual_message_list.tscn").instantiate()
	root.add_child(list)
	list.size = Vector2(620,500)
	var messages: Array[Dictionary] = []
	for index in 1000:
		messages.append({"id":str(index),"role":"assistant","text":"历史记录 %s\n第二行文字"%index,"status":"received","code":""})
	list.set_messages(messages)
	for _frame in 12:
		await process_frame
	check(list.find_children("*","RichTextLabel",true,false).size() < 40,"1000 messages have bounded rendered nodes")
	check(list.get_visible_ids().has("999"),"initial history follows latest")
	check(list.scroll_to_message("500"),"can jump to real history UUID")
	for _frame in 12:
		await process_frame
	var anchor: Dictionary = list.get_reading_anchor()
	check(anchor.id == "500","jump settles on requested anchor")
	var older: Array[Dictionary] = []
	for index in 100:
		older.append({"id":"old-%s"%index,"role":"user","text":"older","status":"received","code":""})
	list.set_messages(older+messages)
	for _frame in 12:
		await process_frame
	check(list.get_reading_anchor().id == anchor.id and absf(list.get_reading_anchor().offset-anchor.offset)<2,"prepend retains exact reading anchor")
	var labels: Array = list.find_children("*","RichTextLabel",true,false)
	var selected: RichTextLabel = labels[0]
	selected.select_all()
	list.set_audio_state("500",{"available":false,"code":""})
	check(is_instance_valid(selected) and not selected.get_selected_text().is_empty(),"audio updates preserve selection")
	list.size.x = 460
	for _frame in 12:
		await process_frame
	check(list.get_reading_anchor().id == "500","resize preserves anchor")
	check(not list.scroll_to_message("missing"),"unknown ID doesn't fabricate jump")
	list.scroll_to_latest()
	for _frame in 12:
		await process_frame
	check(list.get_visible_ids().has("999"),"return latest reaches end")
	list.queue_free()
	await process_frame
	print("Virtual history list: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
