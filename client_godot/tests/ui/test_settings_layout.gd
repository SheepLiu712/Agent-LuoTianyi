extends SceneTree

var failures: Array[String] = []

func _initialize() -> void:
	run.call_deferred()

func run() -> void:
	var window: Window = load("res://scenes/ui/settings_window.tscn").instantiate()
	root.add_child(window)
	window.select_page("preferences")
	window.size = window.min_size
	window.show()
	await create_timer(0.2).timeout
	var page: Control = window.get_node("%PreferencesPage")
	var reload: Button = page.get_node("%Reload")
	var scrolls: Array[Node] = page.find_children("*", "ScrollContainer", true, false).filter(func(node): return node.is_ancestor_of(reload))
	if not scrolls.is_empty():
		var scroll: ScrollContainer = scrolls[0]
		scroll.ensure_control_visible(reload)
		await process_frame
	var footer: Control = window.get_node("%SaveAll").get_parent()
	if reload.get_global_rect().end.y > footer.get_global_rect().position.y:
		failures.append("minimum settings size must keep the reachable reload button above the fixed footer")
	if not Rect2(Vector2.ZERO, Vector2(window.size)).encloses(footer.get_global_rect()):
		failures.append("save and close actions stay inside the minimum window")
	if DisplayServer.get_name() != "headless":
		await RenderingServer.frame_post_draw
		window.get_texture().get_image().save_png("res://artifacts/agentluo-redesign-settings-minimum.png")
	window.queue_free()
	await process_frame
	print("Settings minimum layout: ", "PASS" if failures.is_empty() else "FAIL: " + str(failures))
	quit(0 if failures.is_empty() else 1)
