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
		check(state.get("original_size",Vector2i.ZERO) == dimensions, "cache exposes the decoded original size")
		_check_preview_texture_bounds(state, dimensions)
		var row: Control = Bubble.instantiate()
		root.add_child(row)
		row.size = Vector2(620,1)
		row.configure({"id":id,"role":"assistant","text":"","type":"image","status":"received"})
		row.set_image_state(state)
		await settle()
		var picture: TextureRect = row.get_node("%HistoryPicture")
		_check_preview_fits_the_row(picture, row, dimensions)
		_check_preview_uses_fixed_bounds(picture, dimensions)
		var settled_size := picture.size
		row.size.x = 360
		await settle()
		_check_preview_fits_the_row(picture, row, dimensions)
		check(picture.size.distance_to(settled_size) <= 1.0, "narrower row keeps the fixed preview size")
		row.size.x = 820
		await settle()
		_check_preview_fits_the_row(picture, row, dimensions)
		check(picture.size.distance_to(settled_size) <= 1.0, "wider row never rescales the fixed preview")
		row.set_image_state({"status":"error","texture":null,"original_size":Vector2i.ZERO,"code":"NETWORK_ERROR"})
		await settle()
		_check_failure_retains_a_reachable_retry_action(picture, row)
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
	_check_tall_image_is_reachable(list)
	list.scroll_to_message("20")
	await settle()
	check(list.get_reading_anchor().id == anchor.id and absf(list.get_reading_anchor().offset-anchor.offset) < 2, "late long image preserves the reading anchor below it")
	check(list.get_visible_ids().has(anchor.id) and not list.get_visible_ids().has("19"), "visible rows agree with the restored anchor")
	await _check_partially_visible_image_keeps_stable_anchor(list, messages)
	await _check_pending_image_layout_does_not_capture_prepend_anchor(list, messages)
	await _check_latest_scroll_beats_stale_image_anchor(list)
	await _check_image_load_at_bottom_keeps_follow(list)
	list.queue_free()
	images.queue_free()
	await process_frame
	remove_folder(path)
	print("Image bubble layout: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
func remove_folder(path: String) -> void:
	for folder in DirAccess.get_directories_at(path): remove_folder(path.path_join(folder))
	for file in DirAccess.get_files_at(path): DirAccess.remove_absolute(path.path_join(file))
	DirAccess.remove_absolute(path)

func _check_tall_image_is_reachable(list: Variant) -> void:
	check(list.scroll_to_message("19"), "tall image row can be scrolled to")
	check(list.get_visible_ids().has("19"), "tall image row is reachable inside the visible window")

## 图片正在视口内加载时，稳定锚点必须保留用户看到的像素偏移，而不是跳到图片顶部。
func _check_partially_visible_image_keeps_stable_anchor(list: Variant, messages: Array[Dictionary]) -> void:
	list.set_messages(messages)
	await settle()
	list.scroll_to_message("20")
	await settle()
	var target := int(list._offsets[19] + 80.0)
	list.scroll_vertical = target
	await process_frame
	var before: Dictionary = list.get_stable_anchor()
	check(before.id == "19" and absf(float(before.offset) - 80.0) < 3, "partially visible image becomes the stable anchor")
	var image := Image.create(100, 2400, false, Image.FORMAT_RGBA8)
	image.fill(Color("66ccff"))
	list.set_image_state("19", {"status":"ready", "texture":ImageTexture.create_from_image(image), "code":"", "original_size":Vector2i(100,2400)})
	await settle()
	var after: Dictionary = list.get_stable_anchor()
	check(after.id == before.id and absf(float(after.offset) - float(before.offset)) < 3, "image growth keeps the partially visible anchor offset")
	check(float(after.offset) > 1.0, "image growth never snaps the anchor to the image top")

## 图片重排的 pending 锚点不能被历史前插复用；否则会被拉回图片顶部。
func _check_pending_image_layout_does_not_capture_prepend_anchor(list: Variant, messages: Array[Dictionary]) -> void:
	list.set_messages(messages)
	await settle()
	list.scroll_to_message("20")
	await settle()
	var stable: Dictionary = list.get_stable_anchor()
	list._layout({"id":"19", "offset":0.0}, false)
	var older: Array[Dictionary] = []
	for index in 30:
		older.append({"id":"older-%s" % index, "role":"user", "text":"更早历史", "status":"received", "code":""})
	list.set_messages(older + messages)
	await settle()
	var after: Dictionary = list.get_stable_anchor()
	check(after.id == stable.id and absf(float(after.offset) - float(stable.offset)) < 3, "prepend ignores pending image anchor")
	check(after.id != "19" or float(after.offset) > 1.0, "prepend never snaps to the pending image top")

## 延迟捕获尚未执行时，图片重排必须采用当前滚动位置，而不是上一帧的图片顶部锚点。
func _check_latest_scroll_beats_stale_image_anchor(list: Variant) -> void:
	var local: Array[Dictionary] = []
	for index in 40:
		local.append({"id":"race-%s" % index, "role":"assistant", "text":"" if index == 19 else "历史消息 %s" % index, "type":"image" if index == 19 else "text", "status":"received"})
	list.set_messages(local)
	await settle()
	list.scroll_to_message("race-20")
	await settle()
	var target := int(list._offsets[19] + 80.0)
	list._stable_anchor = {"id":"race-19", "offset":0.0}
	list._stable_follow = false
	list._stable_ready = true
	list._restore_pending = true
	list.scroll_vertical = target
	list._restore_pending = false
	var image := Image.create(100, 2400, false, Image.FORMAT_RGBA8)
	image.fill(Color("66ccff"))
	list.set_image_state("race-19", {"status":"ready", "texture":ImageTexture.create_from_image(image), "code":"", "original_size":Vector2i(100,2400)})
	await settle()
	var after: Dictionary = list.get_stable_anchor()
	check(after.id == "race-19" and absf(float(after.offset) - 80.0) < 3, "latest scroll wins over a stale image-top anchor")
	check(float(list.scroll_vertical) > float(list._offsets[19]) + 10.0, "image growth never snaps the viewport to its top")

## 用户原本贴底时图片加载继续贴底；上翻后同一操作不改变阅读位置。
func _check_image_load_at_bottom_keeps_follow(list: Variant) -> void:
	var local: Array[Dictionary] = []
	for index in 40:
		local.append({"id":"bottom-%s" % index, "role":"assistant", "text":"" if index == 39 else "历史消息 %s" % index, "type":"image" if index == 39 else "text", "status":"received"})
	list.set_messages(local)
	await settle()
	list.scroll_to_latest()
	await settle()
	var image := Image.create(100, 2400, false, Image.FORMAT_RGBA8)
	image.fill(Color("66ccff"))
	list.set_image_state("bottom-39", {"status":"ready", "texture":ImageTexture.create_from_image(image), "code":"", "original_size":Vector2i(100,2400)})
	await settle()
	check(list.is_at_latest(), "image load at the bottom keeps follow")

func _check_failure_retains_a_reachable_retry_action(picture: Variant, row: Variant) -> void:
	check(not picture.visible and not row.get_node("%ImageButton").disabled and row.get_node("%ImageButton").text.contains("重试"), "failure retains a reachable retry action")

## 预览纹理只允许缩、不允许放大，并且必须保持原始宽高比。
func _check_preview_texture_bounds(state: Variant, original: Vector2i) -> void:
	var texture: Texture2D = state.texture
	check(texture != null and texture.get_width() <= original.x and texture.get_height() <= original.y, "preview texture never upscales the original")
	if texture == null or original.y <= 0:
		return
	var ratio := float(original.x) / float(original.y)
	var preview := float(texture.get_width()) / maxf(float(texture.get_height()), 1.0)
	check(absf(preview - ratio) <= 0.02, "preview texture keeps the original aspect ratio")

## 观察点：不超出行宽、不放大原始像素、保持比例，面板不越界。
func _check_preview_fits_the_row(picture: Variant, row: Variant, original: Vector2i) -> void:
	var source := Vector2(original)
	check(picture.size.x <= row.size.x + 1, "preview never exceeds the row width")
	check(picture.size.x <= source.x + 1 and picture.size.y <= source.y + 1, "small images are never upscaled")
	check(absf(picture.size.x / maxf(picture.size.y, 1.0) - source.x / source.y) <= 0.03, "preview keeps the original aspect ratio")
	check(row.get_node("%Bubble").size.x <= row.size.x + 1, "image panel fits its row")

## 缩略图只由原图决定：严格落在 250×250 内，小图不放大。
func _check_preview_uses_fixed_bounds(picture: Variant, original: Vector2i) -> void:
	var scale := minf(1.0, minf(250.0 / float(original.x), 250.0 / float(original.y)))
	var expected := Vector2(original) * scale
	check(picture.size.x <= 250.0 + 1.0 and picture.size.y <= 250.0 + 1.0, "preview stays inside the fixed 250x250 bounds")
	check(picture.size.distance_to(expected) <= 1.0, "preview uses the fixed original-size-derived bounds")
