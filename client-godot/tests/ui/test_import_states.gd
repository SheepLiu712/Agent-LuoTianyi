extends SceneTree

var failures: Array[String] = []


class ImportProbe extends "res://src/storage/python_media_migration_port.gd":
	var target := ""
	var result: Dictionary = {}
	var scan_count := 0
	var import_requests := 0

	func scan() -> Dictionary:
		scan_count += 1
		return result

	func set_target(path: String) -> Dictionary:
		target = path
		return result

	func get_target_path() -> String:
		return target

	func get_state() -> Dictionary:
		return {"busy":false, "mode":"idle", "mismatch":false, "scan":result, "imported":0}

	func request_import() -> void:
		import_requests += 1
		result = make_result(0, 0, true, 52, 2)
		progress.emit({"busy":false, "mode":"done", "imported":1, "skipped":0, "failed":0, "code":"",
			"total":1, "done":1, "audio_total":52, "image_total":2, "audio_done":52, "image_done":2})

	func make_result(pending_audio: int, pending_images: int, previous: bool,
			audio: int = 52, images: int = 2) -> Dictionary:
		return {
			"ok":true, "code":"OK", "root":target,
			"audio_count":audio, "image_count":images,
			"pending_audio_count":pending_audio, "pending_image_count":pending_images,
			"has_previous_import":previous,
			"already_imported":previous and pending_audio + pending_images == 0 and audio + images > 0,
			"unmatched_count":0, "has_audio":true, "has_images":true, "account":{},
		}


class UsageProbe extends "res://src/storage/storage_service.gd":
	var query_count := 0

	func query_directory(_path: String) -> Dictionary:
		query_count += 1
		return {"directory_bytes":10, "total_bytes":1000, "free_bytes":500, "file_count":1, "code":"OK"}


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
	var probe := ImportProbe.new()
	var usage := UsageProbe.new()
	page.set_media_migration(probe)
	page.setup(func(_days: int) -> Error: return OK, usage, "user://import-cache-account", probe, "user://import-cache-app")
	await process_frame
	var status_panel: Control = page.get_node("%MigrationStatusPanel")
	var status: Label = page.get_node("%MigrationStatus")
	var migrate: Button = page.get_node("%MigrateMedia")
	await _check_initial(host, page, probe, status_panel, status, migrate)
	page.get_node("%RefreshUsage").pressed.emit()
	await create_timer(0.1).timeout
	check(usage.query_count == 2, "manual scan queries the cache once per directory")
	await _check_import(page, probe, usage, status, migrate)
	await _check_new_media(host, probe, status_panel, status, migrate)
	await _check_no_new(host, probe, status_panel, status, migrate)
	await _check_failure(host, probe, status_panel, migrate)
	host.queue_free()
	probe.queue_free()
	await process_frame
	print("Import states: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func _check_initial(host: Control, page: Control, probe: ImportProbe,
		status_panel: Control, status: Label, migrate: Button) -> void:
	check(not status_panel.visible and migrate.text == "开始检测", "no target starts undetected")
	check(not migrate.disabled, "start detection is available")
	migrate.pressed.emit()
	await process_frame
	check(page.get_node("%PythonPicker").visible, "start detection opens the client picker")
	page.get_node("%PythonPicker").hide()
	probe.target = "C:/python-client"
	await _reopen(host)
	check(not status_panel.visible and migrate.text == "重新检测", "reopen hides the old result")
	check(probe.scan_count == 0, "reopen does not scan")
	probe.result = probe.make_result(2, 1, false)
	migrate.pressed.emit()
	await process_frame
	check(status_panel.visible and status.text.begins_with("可导入"), "first detection reports importable media")
	check(migrate.text == "导入媒体…" and not migrate.disabled, "first detection offers import")


func _check_import(page: Control, probe: ImportProbe, usage: UsageProbe, status: Label, migrate: Button) -> void:
	migrate.pressed.emit()
	await process_frame
	page.get_node("%MigrationDialog").get_ok_button().pressed.emit()
	await process_frame
	check(probe.import_requests == 1, "import action requests a migration")
	check(status.text.begins_with("已导入") and migrate.disabled, "successful import stays imported until reopen")
	check(page.get_node("%UsageRing").get_segments().is_empty() and page.get_node("%RefreshUsage").text == "开始扫描", "successful import invalidates the old capacity snapshot")
	check(usage.query_count == 2, "successful import never rescans capacity automatically")


func _check_new_media(host: Control, probe: ImportProbe, status_panel: Control,
		status: Label, migrate: Button) -> void:
	await _reopen(host)
	check(not status_panel.visible and migrate.text == "重新检测" and not migrate.disabled, "reopen clears the green result")
	probe.result = probe.make_result(2, 0, true, 54, 2)
	migrate.pressed.emit()
	await process_frame
	check(status.text.begins_with("新增") and not migrate.disabled, "redetection reports only uncached media")


func _check_no_new(host: Control, probe: ImportProbe, status_panel: Control,
		status: Label, migrate: Button) -> void:
	await _reopen(host)
	probe.result = probe.make_result(0, 0, true, 54, 2)
	migrate.pressed.emit()
	await process_frame
	check(status.text.begins_with("已导入") and migrate.disabled, "redetection with no new media stays imported")


func _check_failure(host: Control, probe: ImportProbe, status_panel: Control, migrate: Button) -> void:
	await _reopen(host)
	probe.result = {"ok":false, "code":"TARGET_MISSING"}
	migrate.pressed.emit()
	await process_frame
	check(status_panel.visible and migrate.text == "重新检测" and not migrate.disabled, "failed detection offers redetection")


func _reopen(host: Control) -> void:
	host.hide()
	await process_frame
	host.show()
	await process_frame
