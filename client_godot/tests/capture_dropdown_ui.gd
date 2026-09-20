extends SceneTree
var failures: Array[String] = []
func check(ok: bool,label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ",label)
func _initialize() -> void:
	_run.call_deferred()
func _run() -> void:
	root.size = Vector2i(520,400)
	root.content_scale_size = Vector2i.ZERO
	root.theme = load("res://theme/app_theme.tres")
	var menu = load("res://scenes/ui/unified_dropdown.tscn").instantiate()
	root.add_child(menu)
	menu.size = Vector2(220,42)
	menu.position = Vector2(260,330)
	var options: Array = []
	for i in 35: options.append({"id":str(i),"label":"用途 %02d · 模型配置"%i,"disabled":i==1})
	menu.set_items(options)
	var screen := DisplayServer.screen_get_usable_rect()
	root.position = screen.end-root.size-Vector2i(20,40)
	await create_timer(.2).timeout
	menu.open_menu()
	await create_timer(.2).timeout
	var popup: Window = menu.find_children("*","Window",true,false)[0]
	check(popup.is_embedded() and Rect2i(Vector2i.ZERO,root.size).encloses(Rect2i(popup.position,popup.size)),"long menu clamped inside owning viewport")
	check(popup.position.y < 330,"bottom edge opens upwards")
	check(absi(popup.position.x+4-260)<=1,"popup panel aligns with trigger; shadow extends outside panel")
	await RenderingServer.frame_post_draw
	popup.get_texture().get_image().save_png("res://artifacts/agentluo-011-dropdown.png")
	var key := InputEventKey.new()
	key.pressed = true
	key.keycode = KEY_DOWN
	popup.push_input(key)
	key = key.duplicate()
	key.keycode = KEY_ENTER
	popup.push_input(key)
	await process_frame
	check(menu.get_selected_id()=="2","native keyboard skips disabled row")
	menu.open_menu()
	await process_frame
	root.position -= Vector2i(20,0)
	await process_frame
	check(not menu.is_menu_open(),"moving parent closes menu")
	for factor in [1.25,1.5]:
		root.content_scale_mode = Window.CONTENT_SCALE_MODE_CANVAS_ITEMS
		root.content_scale_factor = factor
		root.size = Vector2i(Vector2(520,400)*factor)
		root.position = screen.end-root.size-Vector2i(20,40)
		await process_frame
		menu.open_menu()
		await create_timer(.2).timeout
		check(Rect2i(Vector2i.ZERO,Vector2i(root.get_visible_rect().size)).encloses(Rect2i(popup.position,popup.size)),"scaled menu stays inside viewport")
		check(popup.size.x>=int(menu.size.x),"embedded menu matches trigger logical width")
		await RenderingServer.frame_post_draw
		popup.get_texture().get_image().save_png("res://artifacts/agentluo-011-dropdown-%s.png"%int(factor*100))
		key.keycode = KEY_ESCAPE
		popup.push_input(key)
		await process_frame
		check(not menu.is_menu_open(),"Esc closes native popup")
	menu.queue_free()
	await process_frame
	print("Dropdown native screenshots: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
