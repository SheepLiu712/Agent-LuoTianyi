extends SceneTree

const Ring = preload("res://src/ui/storage_usage_ring.gd")
const Store = preload("res://src/storage/godot_settings_store.gd")
const APP_DIRECTORY := "user://usage-ring-app"
const ACCOUNT_DIRECTORY := "user://usage-ring-account"
const SCOPE := "http://usage-ring.test\nalice"

var failures: Array[String] = []
var _store_path := ""


class FakeStorage extends "res://src/storage/storage_service.gd":
	var values: Dictionary = {}
	var queries: Array[String] = []

	func query_directory(path: String) -> Dictionary:
		queries.append(path)
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


func _clear_callable() -> Callable:
	return func(_days: int) -> Error: return OK


func _check_unscanned(page: Control, ring: Control) -> void:
	check(ring.get_script() == Ring, "usage ring uses the authored multi-segment control")
	check(page.get_node_or_null("%UsageProgress") == null, "legacy single-value progress bar is removed")
	check(ring.get_segments().is_empty(), "unscanned ring has no segments")
	check(not ring.has_marker(), "unscanned ring has no marker")
	check(page.get_node("%UsagePercent").text == "--%", "unscanned state keeps the percentage unloaded")
	check(page.get_node("%UsageState").text == "尚未扫描", "unscanned state is explicit")
	check(page.get_node("%StorageTotal").text == "整盘 --", "unscanned state keeps the disk total unloaded")
	check(page.get_node("%ClientValue").text == "--" and page.get_node("%OtherValue").text == "--" and page.get_node("%FreeValue").text == "--", "unscanned legend never fabricates values")
	check(page.get_node("%AccountNote").text.contains("--"), "unscanned account note stays unknown")
	check(page.get_node("%LastScan").text == "尚未扫描", "unscanned page has no scan time")
	check(page.get_node("%RefreshUsage").text == "开始扫描", "unscanned page starts with the scan action")
	check(not page.get_node("%RefreshUsage").disabled, "unscanned page allows the first scan")


func _check_loaded(page: Control, ring: Control) -> void:
	check(page.get_node("%UsagePercent").text == "12.00%", "center shows the client share of the whole disk")
	check(page.get_node("%UsageState").text == "客户端占磁盘", "center caption explains the percentage")
	check(page.get_node("%StorageTotal").text == "整盘 1000 bytes", "disk total is visible")
	check(page.get_node("%ClientValue").text == "120 bytes" and page.get_node("%ClientPercent").text == "12.00%", "client legend is synchronized")
	check(page.get_node("%OtherValue").text == "480 bytes" and page.get_node("%OtherPercent").text == "48.00%", "other used excludes the client")
	check(page.get_node("%FreeValue").text == "400 bytes" and page.get_node("%FreePercent").text == "40.00%", "free legend is synchronized")
	check(page.get_node("%AccountNote").text.contains("20 bytes"), "current account voice cache is noted under the client row")
	check(page.get_node("%LastScan").text.begins_with("上次扫描："), "completed scan shows its timestamp")
	check(page.get_node("%RefreshUsage").text == "重新扫描", "completed scan offers a rescan")
	check(not page.get_node("%RefreshUsage").disabled, "completed scan re-enables the action")

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


func _check_states(page: Control, ring: Control, storage: FakeStorage) -> void:
	var tiny: Dictionary = storage.values[APP_DIRECTORY]
	tiny["directory_bytes"] = 1
	tiny["total_bytes"] = 1000000
	tiny["free_bytes"] = 0
	storage.values[APP_DIRECTORY] = tiny
	page.setup(_clear_callable(), storage, ACCOUNT_DIRECTORY, null, APP_DIRECTORY)
	await create_timer(0.05).timeout
	await _scan(page)
	check(page.get_node("%UsagePercent").text == "<0.01%", "small nonzero usage never rounds to a false zero")

	tiny["directory_bytes"] = 0
	storage.values[APP_DIRECTORY] = tiny
	page.setup(_clear_callable(), storage, ACCOUNT_DIRECTORY, null, APP_DIRECTORY)
	await create_timer(0.05).timeout
	await _scan(page)
	check(page.get_node("%UsagePercent").text == "0%", "zero client usage is displayed as zero")
	check(not ring.has_marker(), "zero client usage hides the marker")
	var zero_probe = Ring.new()
	root.add_child(zero_probe)
	zero_probe.size = Vector2(232, 232)
	zero_probe.set_usage(0, 1000, 400)
	check(not zero_probe.has_marker(), "direct zero state hides the marker")
	zero_probe.queue_free()

	var unavailable = load("res://src/storage/storage_service.gd").new()
	page.setup(_clear_callable(), unavailable, ACCOUNT_DIRECTORY, null, APP_DIRECTORY)
	await create_timer(0.05).timeout
	await _scan(page)
	check(page.get_node("%UsagePercent").text == "--%", "unavailable capacity is not displayed as zero percent")
	check(page.get_node("%UsageState").text == "容量数据暂不可用", "unavailable state is explicit")
	check(page.get_node("%ClientValue").text == "--" and page.get_node("%OtherValue").text == "--" and page.get_node("%FreeValue").text == "--", "legend never fabricates values")
	check(ring.get_segments().is_empty(), "unavailable data clears ring segments")
	check(not ring.has_marker(), "unavailable data hides the marker")


func _scan(page: Control) -> void:
	page.get_node("%RefreshUsage").pressed.emit()
	await create_timer(0.1).timeout


func run() -> void:
	_store_path = "user://usage-ring-store-%s.cfg" % Time.get_ticks_usec()
	var store = Store.new(_store_path)
	store.load_settings()
	var storage := FakeStorage.new()
	_seed_storage(storage)
	var window := _mount_window(storage, store, SCOPE)
	var page = window.get_node("%AudioPage")
	var ring = page.get_node("%UsageRing")
	await create_timer(0.2).timeout
	check(storage.queries.is_empty(), "opening the page never loads capacity data")
	_check_unscanned(page, ring)
	await _check_first_scan(page, ring, storage, store)
	await _check_rescan(page, ring, storage)
	await _check_restored_snapshot(store)
	await _check_scope_isolation(store)
	await _check_clear_invalidation(page, storage, store)
	_check_marker()
	await _check_states(page, ring, storage)
	window.queue_free()
	await process_frame
	DirAccess.remove_absolute(ProjectSettings.globalize_path(_store_path))
	print("Cache usage ring: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func _seed_storage(storage: FakeStorage) -> void:
	storage.values[APP_DIRECTORY] = {
		"directory_bytes":120, "total_bytes":1000, "free_bytes":400, "file_count":3, "code":"OK",
	}
	storage.values[ACCOUNT_DIRECTORY] = {
		"directory_bytes":20, "total_bytes":-1, "free_bytes":-1, "file_count":2, "code":"OK",
	}


func _mount_window(storage: FakeStorage, store: Resource, scope: String) -> Window:
	var window = load("res://scenes/ui/windows/settings_window.tscn").instantiate()
	window.setup(null, null, null, _clear_callable(), storage, ACCOUNT_DIRECTORY, APP_DIRECTORY, store, scope)
	root.add_child(window)
	window.open()
	window.select_page("audio")
	return window


func _check_first_scan(page: Control, ring: Control, storage: FakeStorage, store: Resource) -> void:
	page.get_node("%RefreshUsage").pressed.emit()
	check(page.get_node("%RefreshUsage").disabled and page.get_node("%RefreshUsage").text == "正在扫描…", "first scan shows a disabled scanning action")
	check(page.get_node("%UsageState").text == "扫描中…", "first scan shows the scanning caption")
	await create_timer(0.1).timeout
	check(storage.queries.size() == 2, "one scan queries the app and account directories")
	_check_loaded(page, ring)
	var saved_at: Variant = store.get_value("storage", "last_scan_at", 0)
	var snapshot: Variant = store.get_value("storage", "usage_snapshot", {})
	check(int(saved_at) > 0, "completed scan stores its timestamp")
	check(snapshot is Dictionary and snapshot.get("scope") == SCOPE and int(snapshot.get("app_bytes", -1)) == 120, "completed scan stores a scoped snapshot")


func _check_rescan(page: Control, ring: Control, storage: FakeStorage) -> void:
	storage.values[APP_DIRECTORY] = {
		"directory_bytes":240, "total_bytes":1000, "free_bytes":400, "file_count":4, "code":"OK",
	}
	page.get_node("%RefreshUsage").pressed.emit()
	check(ring.get_segments().size() == 3, "rescan keeps the previous distribution visible")
	check(page.get_node("%UsageState").text == "扫描中…" and page.get_node("%RefreshUsage").text == "正在扫描…", "rescan exposes the scanning state")
	check(storage.queries.size() == 2, "rescan does not query before the next frame")
	await create_timer(0.1).timeout
	check(storage.queries.size() == 4, "rescan queries again")
	check(page.get_node("%ClientValue").text == "240 bytes", "rescan replaces the old values")
	check(page.get_node("%RefreshUsage").text == "重新扫描", "rescan stays available")


func _check_restored_snapshot(store: Resource) -> void:
	var storage := FakeStorage.new()
	var window := _mount_window(storage, store, SCOPE)
	var page = window.get_node("%AudioPage")
	var ring = page.get_node("%UsageRing")
	await create_timer(0.2).timeout
	check(storage.queries.is_empty(), "restoring a snapshot never reads the disk")
	check(ring.get_segments().size() == 3 and page.get_node("%ClientValue").text == "240 bytes", "restored snapshot keeps the saved distribution")
	check(page.get_node("%RefreshUsage").text == "重新扫描", "restored snapshot offers a rescan")
	check(page.get_node("%LastScan").text.begins_with("上次扫描："), "restored snapshot keeps the saved timestamp")
	window.queue_free()


func _check_scope_isolation(store: Resource) -> void:
	var storage := FakeStorage.new()
	var window := _mount_window(storage, store, "http://usage-ring.test\nbob")
	var page = window.get_node("%AudioPage")
	await create_timer(0.2).timeout
	check(storage.queries.is_empty(), "another account never loads the previous snapshot")
	check(page.get_node("%UsageState").text == "尚未扫描" and page.get_node("%RefreshUsage").text == "开始扫描", "another account starts unscanned")
	window.queue_free()


func _check_clear_invalidation(page: Control, storage: FakeStorage, store: Resource) -> void:
	page.get_node("%OlderThanDays").value = 0
	page.get_node("%ClearCache").pressed.emit()
	await create_timer(0.05).timeout
	page.get_node("%ClearDialog").get_ok_button().pressed.emit()
	await create_timer(0.1).timeout
	check(page.get_node("%UsageState").text == "尚未扫描", "clearing the cache invalidates the displayed usage")
	check(page.get_node("%RefreshUsage").text == "开始扫描", "clearing the cache returns to the first scan action")
	check(storage.queries.size() == 4, "clearing the cache never scans automatically")
	check(int(store.get_value("storage", "last_scan_at", -1)) == 0, "clearing the cache removes the saved timestamp")
	var cleared: Variant = store.get_value("storage", "usage_snapshot", {})
	check(cleared is Dictionary and cleared.is_empty(), "clearing the cache removes the saved snapshot")


func _check_marker() -> void:
	var probe = Ring.new()
	root.add_child(probe)
	probe.size = Vector2(232, 232)
	probe.set_usage(120, 1000, 400)
	var marker_distance: float = probe.get_marker_position().distance_to(Vector2(116, 116))
	check(probe.has_marker() and marker_distance > 80 and marker_distance < 112, "restored marker follows the client share around the ring")
	probe.queue_free()


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
