extends SceneTree
var failures: Array[String] = []
const ARTIFACTS := "res://artifacts/ui-refinement"
func _initialize() -> void: run.call_deferred()
func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ",label)
func until(predicate: Callable) -> bool:
	var deadline := Time.get_ticks_msec()+4000
	while not predicate.call() and Time.get_ticks_msec()<deadline: await process_frame
	return predicate.call()
func capture(window: Window, label: String) -> void:
	if DisplayServer.get_name() == "headless": return
	await create_timer(.1).timeout
	await RenderingServer.frame_post_draw
	window.get_texture().get_image().save_png(ARTIFACTS + "/" + label + ".png")
func readonly_fields(window: Window, label: String) -> void:
	for name in ["RelationshipField","SpeakingStyleField","PersonalityField","CustomContextField"]:
		var field: Control = window.get_node("%PreferencesPage").get_node("%"+name)
		check(not field.editable,label+" keeps editing disabled: "+name)
		var style: StyleBox = field.get_theme_stylebox("read_only")
		check(style is StyleBoxFlat and style.bg_color.is_equal_approx(Color.WHITE),label+" keeps the same white surface while read-only: "+name)
		if DisplayServer.get_name() != "headless":
			var image := window.get_texture().get_image()
			var point := window.get_final_transform() * field.get_global_transform_with_canvas() * Vector2(field.size.x-24,field.size.y*.5)
			point = point.clamp(Vector2.ZERO,Vector2(image.get_size())-Vector2.ONE)
			check(image.get_pixelv(Vector2i(point)).get_luminance() > .99,label+" actually renders a white field: "+name)
	for name in ["RelationshipPresets","SpeakingStylePresets","Reload"]:
		var button: Button = window.get_node("%PreferencesPage").get_node("%"+name)
		check(button.disabled == (name != "Reload" or label != "failed load"), label+" preserves action availability: "+name)
		check(button.get_theme_stylebox("disabled").bg_color.is_equal_approx(button.get_theme_stylebox("normal").bg_color), label+" does not gray the action background: "+name)
func run() -> void:
	DirAccess.make_dir_recursive_absolute(ARTIFACTS)
	FileAccess.open(ARTIFACTS+"/.gdignore",FileAccess.WRITE).close()
	var theme: Theme = load("res://theme/app_theme.tres")
	for kind in ["LineEdit","TextEdit"]: check(theme.has_stylebox("read_only",kind),kind+" declares read-only styling")
	for state in ["normal","pressed","hover","hover_pressed","disabled","focus"]:
		check(theme.has_stylebox(state,"CheckBox"),"checkbox declares "+state)
	for state in ["font_color","font_pressed_color","font_hover_color","font_hover_pressed_color","font_focus_color","font_disabled_color"]:
		check(theme.has_color(state,"CheckBox"),"checkbox declares "+state)
	var path := "user://control-states-%s" % Time.get_ticks_usec()
	var scope := {"server":OS.get_environment("GODOT_TEST_SERVER"),"username":"ui_retry","message_token":"message-test"}
	var models = load("res://src/session/model_settings.gd").new(load("res://src/network/json_request.gd").new(),load("res://src/storage/model_store.gd").new(ClassDB.instantiate("WindowsSecurity"),path))
	root.add_child(models)
	await models.start(scope)
	var prefs = load("res://src/session/preferences_controller.gd").new(load("res://src/network/json_request.gd").new())
	var window = load("res://scenes/ui/settings_window.tscn").instantiate()
	window.setup(prefs,models)
	root.add_child(window)
	window.open()
	prefs.start(scope)
	await capture(window,"settings-loading")
	check(prefs.get_state().phase == "loading","fixture holds the initial loading state")
	readonly_fields(window,"loading")
	check(await until(func(): return prefs.get_state().phase == "error"),"loading failure settles")
	await capture(window,"settings-load-failed")
	readonly_fields(window,"failed load")
	var page = window.get_node("%PreferencesPage")
	check(page.get_node("%Status").text.contains("加载失败") and not page.get_node("%Reload").disabled,"failure explains how to retry")
	page.get_node("%Reload").pressed.emit()
	check(await until(func(): return prefs.get_state().phase == "ready"),"retry restores editing")
	check(page.get_node("%CustomContextField").editable,"loaded form becomes editable")
	for pair in [["RelationshipField","RelationshipPresets"],["SpeakingStyleField","SpeakingStylePresets"]]:
		var preset: Button = page.get_node("%"+pair[1])
		check(preset.text.is_empty() and preset.icon != null, "preference current value is shown only in the input: " + pair[0])
		check(not preset.tooltip_text.is_empty(), "icon-only preset has an accessible description")
		check(not preset.get_items().any(func(item): return item.id == "custom" or item.label == "自定义"), "preference menus contain presets only: " + pair[0])
		check(not page.get_node("%"+pair[0]).editable, "ready relationship and style reject manual input: " + pair[0])
	page.get_node("%RelationshipPresets").activated.emit("friend")
	page.get_node("%SpeakingStylePresets").activated.emit("gentle")
	check(page.get_node("%RelationshipField").text == "朋友" and page.get_node("%SpeakingStyleField").text == "温柔可人" and prefs.get_state().dirty, "preset choices still update readonly values and the draft")
	page.get_node("%CustomContextField").text = "control state fixture"
	page.get_node("%CustomContextField").text_changed.emit()
	window.get_node("%SaveAll").pressed.emit()
	await capture(window,"settings-saving")
	check(window.is_saving() and window.get_node("%Result").visible,"saving retains visible progress")
	readonly_fields(window,"saving")
	check(not window.get_node("%BusyBlocker").get_global_rect().intersects(window.get_node("%LogoutButton").get_global_rect()),"busy blocker never covers footer actions")
	check(await until(func(): return not window.is_saving()),"save completes")
	window.select_page("models")
	var card = window.get_node("%ModelPage").get_node("%Cards").get_child(0)
	card.get_node("%Enabled").button_pressed = true
	await process_frame
	var checkbox: CheckBox = card.get_node("%Enabled")
	for state in ["normal","pressed","hover","hover_pressed","disabled","focus"]:
		checkbox.disabled = state == "disabled"
		checkbox.button_pressed = state in ["pressed","hover_pressed","disabled","focus"]
		checkbox.release_focus()
		var motion := InputEventMouseMotion.new()
		motion.position = checkbox.get_global_rect().get_center() if state in ["hover","hover_pressed"] else Vector2(2,2)
		window.push_input(motion,true)
		if state == "focus" and DisplayServer.get_name() != "headless": checkbox.grab_focus()
		await capture(window,"checkbox-"+state)
	check(checkbox.get_theme_color("font_hover_pressed_color").is_equal_approx(Color("304553")),"checked hover text stays dark")
	if theme.has_stylebox("focus","CheckBox"):
		check(checkbox.get_theme_stylebox("focus").border_color.is_equal_approx(Color("168ac2")),"keyboard focus uses the stronger blue outline")
	checkbox.disabled = false
	for name in ["Enabled","Json","Thinking"]:
		check(card.get_node("%"+name).get_theme_color("font_pressed_color").is_equal_approx(Color("304553")),"API and capability toggles share legible selected text")
	if DisplayServer.get_name() != "headless":
		for factor in [1.0,1.25,1.5,2.0]:
			for logical in [Vector2i(880,760),Vector2i(720,640)]:
				window.content_scale_mode = Window.CONTENT_SCALE_MODE_CANVAS_ITEMS
				window.content_scale_factor = factor
				window.size = Vector2i(Vector2(logical)*factor)
				await capture(window,"settings-%s-%s" % [logical.x,int(factor*100)])
				var area := Rect2(Vector2.ZERO,window.get_visible_rect().size)
				for name in ["LogoutButton","CloseSettings","SaveAll"]:
					check(area.encloses(window.get_node("%"+name).get_global_rect()),"footer action fits at scale %s: %s" % [factor,name])
				if logical.x == 720:
					await check_minimum_preferences(window, factor)
	window.queue_free()
	models.queue_free()
	await process_frame
	remove_folder(path)
	print("Settings control states: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func check_minimum_preferences(window: Window, factor: float) -> void:
	window.select_page("preferences")
	# Switching a hidden page queues its nested containers for layout, as in the
	# original standalone layout check; scroll only after that layout is settled.
	await create_timer(.2).timeout
	var page: Control = window.get_node("%PreferencesPage")
	var reload: Button = page.get_node("%Reload")
	var scrolls := page.find_children("*", "ScrollContainer", true, false).filter(func(node): return node.is_ancestor_of(reload))
	check(not scrolls.is_empty(), "minimum preferences has a scrollable form")
	if not scrolls.is_empty():
		var scroll: ScrollContainer = scrolls[0]
		scroll.ensure_control_visible(reload)
		await create_timer(.1).timeout
		check(scroll.get_global_rect().encloses(reload.get_global_rect()), "reload is reachable at minimum size and scale %s" % factor)
	var actions: Control = window.get_node("%SaveAll").get_parent()
	check(reload.get_global_rect().end.y <= actions.get_global_rect().position.y, "scrolled form does not overlap fixed actions at scale %s" % factor)
	check(Rect2(Vector2.ZERO, window.get_visible_rect().size).encloses(actions.get_global_rect()), "fixed actions fit minimum window at scale %s" % factor)
	await capture(window, "settings-minimum-preferences-%s" % int(factor * 100))
	window.select_page("models")
	await process_frame

func remove_folder(path: String) -> void:
	if not DirAccess.dir_exists_absolute(path): return
	for directory in DirAccess.get_directories_at(path): remove_folder(path.path_join(directory))
	for file in DirAccess.get_files_at(path): DirAccess.remove_absolute(path.path_join(file))
	DirAccess.remove_absolute(path)
