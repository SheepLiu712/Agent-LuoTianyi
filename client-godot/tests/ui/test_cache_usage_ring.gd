extends SceneTree

const Ring = preload("res://src/ui/storage_usage_ring.gd")
const APP_DIRECTORY := "user://usage-ring-app"
const ACCOUNT_DIRECTORY := "user://usage-ring-account"

var failures: Array[String] = []


class FakeStorage extends "res://src/storage/storage_service.gd":
	var values: Dictionary = {}

	func query_directory(path: String) -> Dictionary:
		return values.get(path, {
			"directory_bytes":-1,
			"total_bytes":-1,
			"free_bytes":-1,
			"file_count":-1,
			"code":"STORAGE_UNAVAILABLE",
		})


func _initialize() -> void:
	run.call_deferred()


func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)


func _check_initial(page: Control, ring: Control) -> void:
	check(ring.get_script() == Ring, "usage ring uses the authored multi-segment control")
	check(page.get_node_or_null("%UsageProgress") == null, "legacy single-value progress bar is removed")
	check(page.get_node("%UsagePercent").text == "12.00%", "center shows the client share of the whole disk")
	check(page.get_node("%UsageState").text == "客户端占磁盘", "center caption explains the percentage")
	check(page.get_node("%StorageTotal").text == "整盘 1000 bytes", "disk total is visible")
	check(page.get_node("%ClientValue").text == "120 bytes" and page.get_node("%ClientPercent").text == "12.00%", "client legend is synchronized")
	check(page.get_node("%OtherValue").text == "480 bytes" and page.get_node("%OtherPercent").text == "48.00%", "other used excludes the client")
	check(page.get_node("%FreeValue").text == "400 bytes" and page.get_node("%FreePercent").text == "40.00%", "free legend is synchronized")
	check(page.get_node("%AccountNote").text.contains("20 bytes"), "current account voice cache is noted under the client row")

	var segments: Array[Dictionary] = ring.get_segments()
	check(segments.size() == 3, "ring has three segments")
	check(_segment(segments, "client") == 120 and _segment(segments, "other") == 480 and _segment(segments, "free") == 400, "ring bytes are proportional to the disk")
	check(_segment(segments, "client") + _segment(segments, "other") + _segment(segments, "free") == 1000, "all segments add up to the disk total")
	check(segments[0].color.is_equal_approx(Ring.CLIENT_COLOR), "client segment keeps the current blue")
	check(segments[1].color.is_equal_approx(Ring.OTHER_COLOR), "other-used segment uses the configured gray")
	check(segments[2].color.is_equal_approx(Ring.FREE_COLOR), "free segment uses white")
	check(ring.has_marker(), "old-style blue marker stays at the client endpoint")
	check(Ring.BACKDROP_COLOR.is_equal_approx(Color(0.921569, 0.956863, 0.984314, 1)), "old pale-blue ring backdrop is restored")
	_check_swatch(page, "ClientSwatch", Ring.CLIENT_COLOR)
	_check_swatch(page, "OtherSwatch", Ring.OTHER_COLOR)
	_check_swatch(page, "FreeSwatch", Ring.FREE_COLOR)
	var probe = Ring.new()
	root.add_child(probe)
	probe.size = Vector2(232, 232)
	probe.set_usage(120, 1000, 400)
	var marker_distance: float = probe.get_marker_position().distance_to(Vector2(116, 116))
	check(probe.has_marker() and marker_distance > 80 and marker_distance < 112, "restored marker follows the client share around the ring")
	probe.queue_free()


func _check_states(window: Window, page: Control, ring: Control, storage: FakeStorage) -> void:
	var tiny: Dictionary = storage.values[APP_DIRECTORY]
	tiny["directory_bytes"] = 1
	tiny["total_bytes"] = 1000000
	tiny["free_bytes"] = 0
	storage.values[APP_DIRECTORY] = tiny
	page.setup(func(): return OK, storage, ACCOUNT_DIRECTORY, null, APP_DIRECTORY)
	await create_timer(0.1).timeout
	check(page.get_node("%UsagePercent").text == "<0.01%", "small nonzero usage never rounds to a false zero")

	tiny["directory_bytes"] = 0
	storage.values[APP_DIRECTORY] = tiny
	page.setup(func(): return OK, storage, ACCOUNT_DIRECTORY, null, APP_DIRECTORY)
	await create_timer(0.1).timeout
	check(page.get_node("%UsagePercent").text == "0%", "zero client usage is displayed as zero")
	check(not ring.has_marker(), "zero client usage hides the marker")
	var zero_probe = Ring.new()
	root.add_child(zero_probe)
	zero_probe.size = Vector2(232, 232)
	zero_probe.set_usage(0, 1000, 400)
	check(not zero_probe.has_marker(), "direct zero state hides the marker")
	zero_probe.queue_free()

	var unavailable = load("res://src/storage/storage_service.gd").new()
	page.setup(func(): return OK, unavailable, ACCOUNT_DIRECTORY, null, APP_DIRECTORY)
	await create_timer(0.1).timeout
	check(page.get_node("%UsagePercent").text == "--%", "unavailable capacity is not displayed as zero percent")
	check(page.get_node("%UsageState").text == "容量数据暂不可用", "unavailable state is explicit")
	check(page.get_node("%ClientValue").text == "--" and page.get_node("%OtherValue").text == "--" and page.get_node("%FreeValue").text == "--", "legend never fabricates values")
	check(ring.get_segments().is_empty(), "unavailable data clears ring segments")
	check(not ring.has_marker(), "unavailable data hides the marker")


func run() -> void:
	var window = load("res://scenes/ui/windows/settings_window.tscn").instantiate()
	var page = window.get_node("%AudioPage")
	var ring = page.get_node("%UsageRing")
	var storage := FakeStorage.new()
	storage.values[APP_DIRECTORY] = {
		"directory_bytes":120,
		"total_bytes":1000,
		"free_bytes":400,
		"file_count":3,
		"code":"OK",
	}
	storage.values[ACCOUNT_DIRECTORY] = {
		"directory_bytes":20,
		"total_bytes":-1,
		"free_bytes":-1,
		"file_count":2,
		"code":"OK",
	}
	window.setup(null, null, null, func(): return OK, storage, ACCOUNT_DIRECTORY, APP_DIRECTORY)
	root.add_child(window)
	window.open()
	window.select_page("audio")
	await create_timer(0.2).timeout
	_check_initial(page, ring)
	if DisplayServer.get_name() != "headless":
		await RenderingServer.frame_post_draw
		window.get_texture().get_image().save_png("res://artifacts/cache-usage-ring.png")
	await _check_states(window, page, ring, storage)
	window.queue_free()
	await process_frame
	print("Cache usage ring: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func _segment(segments: Array[Dictionary], kind: String) -> int:
	for segment in segments:
		if str(segment.get("kind", "")) == kind:
			return int(segment.get("bytes", 0))
	return -1


func _check_swatch(page: Node, name: String, expected: Color) -> void:
	var swatch := page.find_child(name, true, false) as Panel
	check(swatch != null, "legend swatch exists: " + name)
	if swatch == null:
		return
	var style := swatch.get_theme_stylebox("panel") as StyleBoxFlat
	check(style != null and style.bg_color.is_equal_approx(expected), "legend swatch matches its ring segment: " + name)
