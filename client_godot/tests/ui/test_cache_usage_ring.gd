extends SceneTree
var failures: Array[String] = []
func _initialize() -> void: run.call_deferred()
func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ",label)
func run() -> void:
	var window = load("res://scenes/ui/settings_window.tscn").instantiate()
	var page = window.get_node("%AudioPage")
	check(page.get_node_or_null("%UsageProgress") is TextureProgressBar, "usage ring is authored as a Godot control")
	if failures.is_empty():
		var directory := "user://usage-ring-%s" % Time.get_ticks_usec()
		DirAccess.make_dir_recursive_absolute(directory)
		var data := PackedByteArray()
		data.resize(2048)
		var file := FileAccess.open(directory+"/audio",FileAccess.WRITE)
		file.store_buffer(data)
		file.close()
		var storage = load("res://src/storage/godot_storage_service.gd").new()
		window.setup(null,null,null,func(): return OK,storage,directory)
		root.add_child(window)
		window.open()
		window.select_page("audio")
		await create_timer(0.2).timeout
		check(page.get_node("%UsagePercent").text == "<0.01%", "small nonzero usage never rounds to a false zero")
		check(page.get_node("%UsageDetails").text.contains("2.00 KiB"), "cache byte size is visible")
		if DisplayServer.get_name() != "headless":
			await RenderingServer.frame_post_draw
			window.get_texture().get_image().save_png("res://artifacts/cache-usage-ring.png")
		var unavailable = load("res://src/storage/storage_service.gd").new()
		page.setup(func(): return OK, unavailable, directory)
		await create_timer(0.1).timeout
		check(page.get_node("%UsagePercent").text == "--%", "unavailable capacity is not displayed as zero percent")
		window.queue_free()
		await process_frame
		DirAccess.remove_absolute(directory+"/audio")
		DirAccess.remove_absolute(directory)
	else: window.free()
	print("Cache usage ring: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
