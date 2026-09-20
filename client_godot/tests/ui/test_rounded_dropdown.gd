extends SceneTree
func _initialize() -> void: run.call_deferred()
func run() -> void:
	if DisplayServer.get_name() == "headless":
		quit(2)
		return
	root.size = Vector2i(600, 480)
	root.gui_embed_subwindows = true
	var dropdown = load("res://scenes/ui/unified_dropdown.tscn").instantiate()
	root.add_child(dropdown)
	dropdown.position = Vector2(40, 40)
	dropdown.set_items([{"id":"one","label":"圆角菜单"},{"id":"two","label":"Godot 原生控件"}])
	dropdown.open_menu()
	await create_timer(0.3).timeout
	var popup: Window = dropdown.get_node("%Menu")
	var ok: bool = popup.is_embedded() and popup.transparent_bg
	await RenderingServer.frame_post_draw
	var pixels := popup.get_texture().get_image()
	ok = ok and pixels.get_pixel(0,0).a < 0.2 and pixels.get_pixel(16,16).a > 0.8
	ok = ok and Rect2i(Vector2i.ZERO, root.size).encloses(Rect2i(popup.position,popup.size))
	pixels.save_png("res://artifacts/godot-rounded-dropdown.png")
	dropdown.queue_free()
	await process_frame
	print("Godot rounded dropdown: ", "PASS" if ok else "FAIL")
	quit(0 if ok else 1)
