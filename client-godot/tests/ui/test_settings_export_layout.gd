extends SceneTree
## Run with --script <absolute path> against the exported EXE as well as source.
var failures: Array[String] = []
func _initialize() -> void: run.call_deferred()
func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)
func run() -> void:
	var window = load("res://scenes/ui/settings_window.tscn").instantiate()
	window.setup(null, null, null, func(_days): return OK)
	root.add_child(window)
	window.open()
	for dimensions in [Vector2i(880,760), Vector2i(720,640)]:
		window.size = dimensions
		for entry in [["preferences","PreferencesPage"],["models","ModelPage"],["audio","AudioPage"]]:
			window.select_page(entry[0])
			await create_timer(.2).timeout
			var page: Control = window.get_node("%"+entry[1])
			check(page.size.x > 400 and page.size.y > 400, "source/export page fills content: " + entry[0])
			if DisplayServer.get_name() != "headless":
				check(page.is_visible_in_tree(), "selected page is visible: " + entry[0])
				var title: Label = page.find_child("Title",true,false)
				check(page.get_global_rect().encloses(title.get_global_rect()), "page title is inside visible content: " + entry[0])
				var output := OS.get_environment("GODOT_ARTIFACT_DIR")
				if not output.is_empty():
					await RenderingServer.frame_post_draw
					window.get_texture().get_image().save_png(output.path_join("settings-%s-%s.png" % [entry[0],dimensions.x]))
		var logout: Control = window.get_node("%LogoutButton")
		var sidebar: Control = window.get_node("%Sidebar")
		# 导航项缩进后不再和底栏同缘；对齐目标改为侧栏列本身。
		check(is_equal_approx(logout.size.x,sidebar.size.x) and is_equal_approx(logout.global_position.x,sidebar.global_position.x), "logout aligns with the sidebar column")
	window.queue_free()
	await process_frame
	print("Settings exported layout: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
