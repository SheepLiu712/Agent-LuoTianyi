extends SceneTree

var failures: Array[String] = []


func _initialize() -> void:
	run.call_deferred()


func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)


func _check_stacked_sections(window: Window, sections: Array) -> void:
	for page in sections:
		check(page.visible, "all settings sections stay visible in one scroll")
	for index in range(1, sections.size()):
		check(sections[index - 1].position.y < sections[index].position.y, "settings sections are vertically stacked in order")
	check(window.get_node("%ProfileTab").button_pressed, "top section is selected on open")


func _check_anchor_navigation(window: Window, scroll: ScrollContainer, preferences: Control, audio: Control) -> void:
	var rendered := DisplayServer.get_name() != "headless" and scroll.size.y > 0
	if rendered:
		var bar := scroll.get_v_scroll_bar()
		var expected_bottom := maxi(0, int(bar.max_value - scroll.size.y))
		check(scroll.scroll_vertical >= expected_bottom - 2 or scroll.scroll_vertical > audio.position.y, "style anchor scrolls to the final section")
	window.select_page("profile")
	await create_timer(.25).timeout
	if rendered:
		check(scroll.scroll_vertical == 0, "profile anchor returns to the top")
	if not rendered:
		return
	scroll.scroll_vertical = int(preferences.position.y + 24)
	await create_timer(.05).timeout
	check(window.get_node("%PreferencesTab").button_pressed, "wheel scrolling syncs the selected anchor")


func run() -> void:
	var window = load("res://scenes/ui/settings_window.tscn").instantiate()
	window.setup(null, null, null, func(_days): return OK)
	root.add_child(window)
	window.open()
	await create_timer(.25).timeout
	var scroll: ScrollContainer = window.get_node("%Content")
	var profile: Control = window.get_node("%ProfilePage")
	var preferences: Control = window.get_node("%PreferencesPage")
	var models: Control = window.get_node("%ModelPage")
	var audio: Control = window.get_node("%AudioPage")
	var style: Control = window.get_node("%StylePage")
	var sections := [profile, preferences, models, audio, style]
	_check_stacked_sections(window, sections)

	window.select_page("style")
	await create_timer(.25).timeout
	check(window.get_node("%StyleTab").button_pressed, "style tab reflects its anchor")
	await _check_anchor_navigation(window, scroll, preferences, audio)
	check(window.get_node("%ProfileTab").button_pressed, "profile tab reflects the top anchor")

	window.select_page("style")
	await process_frame
	window.select_page("audio")
	await create_timer(.25).timeout
	check(window.get_node("%AudioTab").button_pressed, "rapid anchor changes settle on the latest tab")
	check(audio.visible and style.visible, "all sections remain scrollable after rapid changes")

	window.queue_free()
	await process_frame
	print("Settings page transition: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
