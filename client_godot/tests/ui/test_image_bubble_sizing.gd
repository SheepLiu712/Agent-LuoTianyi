extends SceneTree
var failures: Array[String] = []
const Bubble = preload("res://scenes/ui/message_bubble.tscn")
func _initialize() -> void: run.call_deferred()
func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ",label)
func settle() -> void:
	for frame in 10: await process_frame
func run() -> void:
	var path := "user://image-layout-%s" % Time.get_ticks_usec()
	var images = load("res://src/storage/history_images.gd").new(path)
	root.add_child(images)
	images.start({"server":"https://image-layout.test","username":"alice","message_token":"synthetic"})
	for dimensions in [Vector2i(24,12),Vector2i(1600,900),Vector2i(100,2400)]:
		var id := str(dimensions)
		var image := Image.create(dimensions.x,dimensions.y,false,Image.FORMAT_RGBA8)
		image.fill(Color("66ccff"))
		check(images.store_local(id,image.save_png_to_buffer()) == OK, "real image cache accepts fixture")
		var state: Dictionary = images.get_state(id)
		check(state.get("original_size",Vector2i.ZERO) == dimensions, "cache exposes original size independently of thumbnail")
		check(state.texture.get_width() <= 480 and state.texture.get_height() <= 480, "thumbnail budget remains unchanged")
		var row: Control = Bubble.instantiate()
		root.add_child(row)
		row.size = Vector2(620,1)
		row.configure({"id":id,"role":"assistant","text":"","type":"image","status":"received"})
		row.set_image_state(state)
		await settle()
		var picture: TextureRect = row.get_node("%HistoryPicture")
		var expected := Vector2(dimensions) * minf(1, (620*.9-32)/dimensions.x)
		check(picture.size.distance_to(expected) <= 1.5, "image uses original ratio, width limit and no upscaling: " + id)
		check(row.get_node("%Bubble").size.x <= 620*.9+1, "image panel fits its row")
		if dimensions.y == 2400: check(picture.size.y >= 2399, "long image has no height cap")
		row.queue_free()
		await process_frame
	var direct: Control = Bubble.instantiate()
	root.add_child(direct)
	direct.size = Vector2(620,1)
	var small := Image.create(40,20,false,Image.FORMAT_RGBA8)
	small.fill(Color.WHITE)
	direct.configure({"id":"demo","role":"user","text":"","status":"sent"},ImageTexture.create_from_image(small))
	await settle()
	check(direct.get_node("%Picture").size == Vector2(40,20), "offline direct texture follows the same no-upscale rule")
	direct.queue_free()
	# A late image above the current reading point must not move that point.
	var list = load("res://scenes/ui/virtual_message_list.tscn").instantiate()
	root.add_child(list)
	list.size = Vector2(620,500)
	var messages: Array[Dictionary] = []
	for index in 40:
		messages.append({"id":str(index),"role":"assistant","text":"" if index == 19 else "历史消息 %s" % index,"type":"image" if index == 19 else "text","status":"received"})
	list.set_messages(messages)
	await settle()
	list.scroll_to_message("20")
	await settle()
	var anchor: Dictionary = list.get_reading_anchor()
	list.set_image_state("19",images.get_state(str(Vector2i(100,2400))))
	await settle()
	check(list.get_reading_anchor().id == anchor.id and absf(list.get_reading_anchor().offset-anchor.offset) < 2, "late long image preserves the reading anchor below it")
	list.queue_free()
	images.queue_free()
	await process_frame
	remove_folder(path)
	print("Adaptive image bubbles: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
func remove_folder(path: String) -> void:
	for folder in DirAccess.get_directories_at(path): remove_folder(path.path_join(folder))
	for file in DirAccess.get_files_at(path): DirAccess.remove_absolute(path.path_join(file))
	DirAccess.remove_absolute(path)
