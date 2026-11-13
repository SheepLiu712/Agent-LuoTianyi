extends SceneTree
## Run with --script <absolute path> against the exported EXE as well as source.
var failures: Array[String] = []
const Style = preload("res://src/application/ui_style.gd")
const Store = preload("res://src/storage/godot_settings_store.gd")
func _initialize() -> void: run.call_deferred()
func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)


func _check_audio_page(window: Window, page: Control, dimensions: Vector2i) -> void:
	var scroll: ScrollContainer = window.get_node("%Content")
	var column: Control = page.get_node("Scroll")
	check(column.size.x <= scroll.size.x + 1, "cache page never overflows horizontally: " + str(dimensions.x))
	check(page.get_node("%StorageCard").get_global_rect().size.x > 300, "storage card remains readable: " + str(dimensions.x))
	if DisplayServer.get_name() == "headless":
		return
	var ring: Control = page.get_node("%UsageRing")
	var legend: Control = page.get_node("%UsageLegend")
	check(page.get_node("%StorageCard").get_global_rect().encloses(ring.get_global_rect()), "storage ring stays inside its card")
	check(page.get_node("%StorageCard").get_global_rect().encloses(legend.get_global_rect()), "storage legend stays inside its card")


func _capture_page(window: Window, page: Control, entry: Array, dimensions: Vector2i) -> void:
	if DisplayServer.get_name() == "headless":
		return
	check(page.is_visible_in_tree(), "selected page is visible: " + entry[0])
	var title: Label = page.find_child("Title",true,false)
	check(page.get_global_rect().encloses(title.get_global_rect()), "page title is inside visible content: " + entry[0])
	check(title.get_theme_type_variation() == &"SettingsPageTitle", "page title uses the shared settings type: " + entry[0])
	var output := OS.get_environment("GODOT_ARTIFACT_DIR")
	if output.is_empty():
		return
	await RenderingServer.frame_post_draw
	window.get_texture().get_image().save_png(output.path_join("settings-%s-%s.png" % [entry[0],dimensions.x]))
	if entry[0] != "audio":
		return
	var audio_scroll: ScrollContainer = window.get_node("%Content")
	audio_scroll.scroll_vertical = int(audio_scroll.get_v_scroll_bar().max_value)
	await create_timer(.1).timeout
	await RenderingServer.frame_post_draw
	window.get_texture().get_image().save_png(output.path_join("settings-audio-%s-bottom.png" % dimensions.x))
	audio_scroll.scroll_vertical = 0


func _check_page(window: Window, page: Control, entry: Array, dimensions: Vector2i) -> void:
	check(page.size.x > 400 and page.size.y > 100, "source/export section fills content width: " + entry[0])
	if entry[0] == "audio":
		_check_audio_page(window, page, dimensions)
	await _capture_page(window, page, entry, dimensions)


func run() -> void:
	var style_path := "user://settings-layout-style-%s.cfg" % Time.get_ticks_usec()
	var style = Style.new()
	style.configure(Store.new(style_path))
	var window = load("res://scenes/ui/windows/settings_window.tscn").instantiate()
	window.setup(null, null, null, func(_days): return OK)
	window.set_ui_style(style)
	root.add_child(window)
	window.open()
	for dimensions in [Vector2i(880,760), Vector2i(720,640)]:
		window.size = dimensions
		for entry in [["profile","ProfilePage"],["preferences","PreferencesPage"],["models","ModelPage"],["audio","AudioPage"],["style","StylePage"]]:
			window.select_page(entry[0])
			await create_timer(.2).timeout
			var page: Control = window.get_node("%"+entry[1])
			await _check_page(window, page, entry, dimensions)
		var logout: Control = window.get_node("%LogoutButton")
		var sidebar: Control = window.get_node("%Sidebar")
		# 导航项缩进后不再和底栏同缘；对齐目标改为侧栏列本身。
		check(is_equal_approx(logout.size.x,sidebar.size.x) and is_equal_approx(logout.global_position.x,sidebar.global_position.x), "logout aligns with the sidebar column")
	window.queue_free()
	style.save_preferences("flat", "svg")
	await process_frame
	DirAccess.remove_absolute(style_path)
	print("Settings exported layout: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
