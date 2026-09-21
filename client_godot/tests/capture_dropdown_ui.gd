extends SceneTree
var failures: Array[String] = []
func check(ok: bool,label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ",label)
func _initialize() -> void:
	_run.call_deferred()
func click(point: Vector2) -> void:
	for down in [true,false]:
		var event := InputEventMouseButton.new()
		event.button_index = MOUSE_BUTTON_LEFT
		event.pressed = down
		event.position = point
		event.global_position = point
		root.push_input(event,true)
		await process_frame
	await create_timer(.15).timeout
func _run() -> void:
	if DisplayServer.get_name() == "headless":
		print("Dropdown visual checks require a GPU window")
		quit(2)
		return
	root.size = Vector2i(520,400)
	root.content_scale_size = Vector2i.ZERO
	root.theme = load("res://theme/app_theme.tres")
	var menu = load("res://scenes/ui/unified_dropdown.tscn").instantiate()
	root.add_child(menu)
	menu.position = Vector2(30,30)
	menu.set_items([{"id":"a","label":"选项 A"},{"id":"b","label":"选项 B"}])
	await create_timer(.2).timeout
	for expected in [true,false,true,false]:
		await click(Vector2(70,50))
		check(menu.is_menu_open() == expected, "repeated trigger clicks alternate open and closed")
	check(menu.get_selected_id() == "a", "trigger toggling never activates an item")
	await click(Vector2(70,50))
	await click(Vector2(480,300))
	check(not menu.is_menu_open(), "outside click closes menu")
	await click(Vector2(70,50))
	check(menu.is_menu_open(), "click after outside dismissal opens normally")
	var escape := InputEventKey.new()
	escape.pressed = true
	escape.keycode = KEY_ESCAPE
	menu.get_node("%Menu").push_input(escape)
	await process_frame
	await click(Vector2(70,50))
	check(menu.is_menu_open(), "click after Esc opens normally")
	menu.close_menu()
	await process_frame
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
	var pixels := popup.get_texture().get_image()
	check(popup.transparent_bg, "embedded menu has a transparent background")
	check(pixels.get_pixel(0, 0).a < .2 and pixels.get_pixel(16, 16).a > .8, "Godot rounded corners are transparent and the panel is solid")
	check(pixels.save_png("res://artifacts/agentluo-011-dropdown.png") == OK, "dropdown screenshot saved")
	check(pixels.save_png("res://artifacts/godot-rounded-dropdown.png") == OK, "rounded-corner evidence saved")
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
