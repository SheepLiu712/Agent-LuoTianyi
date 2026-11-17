extends SceneTree

var failures: Array[String] = []


class ScanProbe extends "res://src/storage/python_media_migration_port.gd":
	var scan_count := 0
	var target_path := ""

	func scan() -> Dictionary:
		scan_count += 1
		return {"ok":true, "audio_count":1, "image_count":0, "unmatched_count":0,
			"has_audio":true, "has_images":false, "has_previous_import":false,
			"pending_audio_count":1, "pending_image_count":0, "already_imported":false}

	func get_state() -> Dictionary:
		return {"busy":false, "mode":"idle"}

	func get_target_path() -> String:
		return target_path


func _initialize() -> void:
	_run.call_deferred()


func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)


func _run() -> void:
	var host := Control.new()
	root.add_child(host)
	var page = load("res://scenes/ui/settings/audio_settings_page.tscn").instantiate() as Control
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
	check(probe.scan_count == 0, "showing the page does not scan media")
	var status: Label = page.get_node("%MigrationStatus")
	var migrate: Button = page.get_node("%MigrateMedia")
	var panel: Control = page.get_node("%MigrationStatusPanel")
	check(not panel.visible and migrate.text == "开始检测", "first view starts undetected")
	probe.target_path = "C:/python-client"
	host.hide()
	await process_frame
	host.show()
	await process_frame
	check(probe.scan_count == 0 and not panel.visible, "reopening keeps a saved target for explicit detection")
	check(migrate.text == "重新检测" and not migrate.disabled, "saved target offers redetection")
	migrate.pressed.emit()
	await process_frame
	check(probe.scan_count == 1, "explicit detection scans media once")
	check(status.text.contains("可导入") and migrate.text == "导入媒体…", "detected media offers import")
	host.queue_free()
	probe.queue_free()
	await process_frame
	print("Settings prewarm: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
