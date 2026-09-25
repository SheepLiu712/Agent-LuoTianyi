extends SceneTree
const Bubble = preload("res://scenes/ui/message_bubble.tscn")
var failures: Array[String] = []

func _initialize() -> void: run.call_deferred()
func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ",label)
func settle() -> void:
	for frame in 8: await process_frame
func message(text: String, own: bool = false) -> Dictionary:
	return {"id":"sample","role":"user" if own else "assistant","text":text,"status":"sent" if own else "received","code":""}
func bubble(text: String, position_y: float, own: bool = false) -> Control:
	var view: Control = Bubble.instantiate()
	root.add_child(view)
	view.size = Vector2(620,1)
	view.position.y = position_y
	view.configure(message(text,own))
	return view

func run() -> void:
	root.size = Vector2i(800,1000)
	root.content_scale_size = Vector2i.ZERO
	var short := bubble("好呀",12)
	var medium := bubble("这是一条长度适中的消息",100)
	var long := bubble("长段落应自动换行，同时保留阅读位置。".repeat(24),190)
	var own := bubble("好",720,true)
	await settle()
	var short_width: float = short.get_node("%Bubble").size.x
	var medium_width: float = medium.get_node("%Bubble").size.x
	check(short_width < medium_width and short_width < 140, "short text fits content instead of a fixed minimum")
	check(long.get_node("%Bubble").size.x <= 620*.9+1 and long.get_node("%Bubble").size.y > medium.get_node("%Bubble").size.y*3, "long text is capped at 90 percent and grows vertically")
	check(short.get_node("%Bubble").get_global_rect().position.x > short.get_node("%Avatar").get_global_rect().end.x, "assistant bubble stays next to its left avatar")
	check(own.get_node("%Bubble").get_global_rect().end.x < own.get_node("%Avatar").get_global_rect().position.x, "own bubble stays next to its right avatar")
	var own_width: float = own.get_node("%Bubble").size.x
	var update := message("好",true)
	update.status = "uncertain"
	own.update_message(update)
	await settle()
	check(is_equal_approx(own.get_node("%Bubble").size.x,own_width), "long delivery status does not widen the text panel")
	own.set_audio_state({"available":true,"code":"","status":"idle","blocked":false,"duration":2.4,"position":0.0,"waveform":PackedFloat32Array([.1,.5,.9])})
	await settle()
	check(is_equal_approx(own.get_node("%Bubble").size.x,own_width) and own.find_child("MessageAudio",true,false).size.x > own_width, "audio remains usable without widening short text")
	short.get_node("%Text").select_all()
	short.update_message(message("好呀"))
	await settle()
	check(short.get_node("%Text").get_selected_text() == "好呀", "unchanged update preserves selection")
	medium.update_message(message("iiiiiiii"))
	await settle()
	var narrow: float = medium.get_node("%Bubble").size.x
	medium.update_message(message("WWWWWWWW"))
	await settle()
	check(medium.get_node("%Bubble").size.x > narrow+20, "actual glyph width matters, not character count")
	medium.update_message(message("你好\n🙂 ok"))
	await settle()
	check(medium.get_node("%Text").get_line_count() >= 2, "manual newline and emoji remain visible")
	long.update_message(message("https://example.test/"+"abcdefghijk".repeat(100)))
	long.size.x = 360
	await settle()
	check(long.get_node("%Bubble").size.x <= 324+1 and long.get_node("%Text").get_line_count() > 2, "unbroken URL wraps within a narrow row")
	short.get_node("%Text").add_theme_font_size_override("normal_font_size",24)
	await settle()
	check(short.get_node("%Bubble").size.x > short_width, "font changes recompute natural width")
	if DisplayServer.get_name() != "headless":
		DirAccess.make_dir_recursive_absolute("res://artifacts/release-013")
		var y := 12.0
		for view in [short,medium,long,own]:
			view.position.y = y
			y += view.get_combined_minimum_size().y + 16
		root.size.y = ceili(y)
		await RenderingServer.frame_post_draw
		root.get_texture().get_image().save_png("res://artifacts/release-013/text-bubbles.png")
	for view in [short,medium,long,own]: view.queue_free()
	await process_frame
	print("Adaptive text bubbles: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
