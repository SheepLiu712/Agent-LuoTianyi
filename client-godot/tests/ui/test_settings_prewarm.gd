extends SceneTree

var failures: Array[String] = []


class ScanProbe extends "res://src/storage/python_media_migration_port.gd":
	var scan_count := 0

	func scan() -> Dictionary:
		scan_count += 1
		return {"ok":true, "audio_count":0, "image_count":0, "unmatched_count":0,
			"has_audio":false, "has_images":false}

	func get_state() -> Dictionary:
		return {"busy":false, "mode":"idle"}


func _initialize() -> void:
	_run.call_deferred()


func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)


func _run() -> void:
	var host := Control.new()
	root.add_child(host)
	var page = load("res://scenes/ui/audio_settings_page.tscn").instantiate() as Control
	host.add_child(page)
	await process_frame
	host.hide()
	var probe := ScanProbe.new()
	page.set_media_migration(probe)
	page.setup(func(_days: int) -> Error: return OK, null, "", probe)
	await process_frame
	check(probe.scan_count == 0, "hidden prewarm does not scan media")
	host.show()
	await process_frame
	check(probe.scan_count > 0, "first visible page scans media once")
	host.queue_free()
	probe.queue_free()
	await process_frame
	print("Settings prewarm: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
