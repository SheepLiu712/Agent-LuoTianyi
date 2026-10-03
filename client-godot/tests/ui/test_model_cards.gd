extends SceneTree
var failures: Array[String] = []
func _initialize() -> void: run.call_deferred()
func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)
func run() -> void:
	var path := "user://model-cards-%s" % Time.get_ticks_usec()
	var settings = load("res://src/session/model_settings.gd").new(load("res://src/network/json_request.gd").new(), load("res://src/storage/model_store.gd").new(ClassDB.instantiate("WindowsSecurity"), path))
	root.add_child(settings)
	await settings.start({"server":OS.get_environment("GODOT_TEST_SERVER"), "username":"cards", "message_token":"test"})
	var window = load("res://scenes/ui/settings_window.tscn").instantiate()
	window.setup(null, settings)
	root.add_child(window)
	window.open()
	var page = window.get_node("%ModelPage")
	var cards = page.get_node_or_null("%Cards")
	check(cards != null and cards.get_child_count() == 2, "every server purpose has its own card")
	if failures.is_empty():
		if DisplayServer.get_name() != "headless":
			await create_timer(0.2).timeout
			await RenderingServer.frame_post_draw
			window.get_texture().get_image().save_png("res://artifacts/model-purpose-cards.png")
		var first = cards.get_child(0)
		var second = cards.get_child(1)
		_check_disabled_purposes_begin_collapsed(first, second)
		first.get_node("%Enabled").button_pressed = true
		_check_checkbox_expands_only_its_own_purpose(first, second)
		first.get_node("%ModelName").text = "draft-kept"
		first.get_node("%ModelName").text_changed.emit("draft-kept")
		first.get_node("%Enabled").button_pressed = false
		first.get_node("%Enabled").button_pressed = true
		_check_collapsing_retains_unsaved_fields(first, window)
		var result: Dictionary = await window.save_changes()
		_check_invalid_enabled_card_is_located_before_any_write(result, first)
		var config: Dictionary = settings.get_config("vision-purpose")
		config.merge({"enabled":true,"provider":"","base_url":"https://example.test/v1","api_key":"synthetic","model":"vision"},true)
		check(not settings.validate("vision-purpose",config).ok, "provider is required like the original client")
		if DisplayServer.get_name() != "headless":
			await create_timer(0.2).timeout
			await RenderingServer.frame_post_draw
			window.get_texture().get_image().save_png("res://artifacts/model-purpose-expanded.png")
		first.get_node("%Enabled").button_pressed = false
		result = await window.save_changes()
		check(result.ok and not window.is_dirty(), "whole-window save commits disabled draft without provider traffic")
		page.get_node("%RefreshTypes").pressed.emit()
		var deadline := Time.get_ticks_msec() + 2500
		while settings.get_state().phase == "loading" and Time.get_ticks_msec() < deadline: await process_frame
		_check_refresh_rebuilds_requirements_and_retains_saved_configuration(cards, settings, window)
	window.queue_free()
	settings.queue_free()
	await process_frame
	remove_folder(path)
	print("Model purpose cards: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
func remove_folder(path: String) -> void:
	if not DirAccess.dir_exists_absolute(path): return
	for folder in DirAccess.get_directories_at(path): remove_folder(path.path_join(folder))
	for file in DirAccess.get_files_at(path): DirAccess.remove_absolute(path.path_join(file))
	DirAccess.remove_absolute(path)

func _check_refresh_rebuilds_requirements_and_retains_saved_configuration(cards: Variant, settings: Variant, window: Variant) -> void:
	check(cards.get_child_count() == 2 and settings.get_config("text-purpose").model == "draft-kept" and not window.is_dirty(), "refresh rebuilds requirements and retains saved configuration")

func _check_disabled_purposes_begin_collapsed(first: Variant, second: Variant) -> void:
	check(not first.get_node("%Fields").visible and not second.get_node("%Fields").visible, "disabled purposes begin collapsed")

func _check_checkbox_expands_only_its_own_purpose(first: Variant, second: Variant) -> void:
	check(first.get_node("%Fields").visible and not second.get_node("%Fields").visible, "checkbox expands only its own purpose")

func _check_collapsing_retains_unsaved_fields(first: Variant, window: Variant) -> void:
	check(first.get_node("%ModelName").text == "draft-kept" and window.is_dirty(), "collapsing retains unsaved fields")

func _check_invalid_enabled_card_is_located_before_any_write(result: Variant, first: Variant) -> void:
	check(not result.ok and first.get_node("%CardStatus").text.contains("MODEL_FIELDS_REQUIRED"), "invalid enabled card is located before any write")
