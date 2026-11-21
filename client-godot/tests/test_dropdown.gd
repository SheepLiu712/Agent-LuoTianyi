extends SceneTree
var failures: Array[String] = []
func check(value: bool,label: String) -> void:
	if not value:
		failures.append(label)
		print("FAIL: ",label)
func _initialize() -> void:
	_run.call_deferred()
func _click(point: Vector2, double_click := false) -> void:
	for down in [true,false]:
		var event := InputEventMouseButton.new()
		event.button_index = MOUSE_BUTTON_LEFT
		event.pressed = down
		event.double_click = double_click
		event.position = point
		event.global_position = point
		root.push_input(event,true)
		await process_frame
	await create_timer(.05).timeout
func _move_pointer(point: Vector2) -> void:
	var motion := InputEventMouseMotion.new()
	motion.position = point
	root.push_input(motion,true)
	await process_frame
func _focus_is_hidden(dropdown: Variant) -> bool:
	return dropdown.has_theme_stylebox_override("focus") and dropdown.get_theme_stylebox("focus") is StyleBoxEmpty
func _focus_ring_visible(dropdown: Variant) -> bool:
	return dropdown.has_focus() and not _focus_is_hidden(dropdown)
func _run() -> void:
	if not ResourceLoader.exists("res://scenes/ui/components/unified_dropdown.tscn"):
		check(false,"shared dropdown scene available")
		quit(1)
		return
	root.size = Vector2i(700,500)
	var dropdown = load("res://scenes/ui/components/unified_dropdown.tscn").instantiate()
	dropdown.window_system = preload("res://src/platform/window_system.gd").new()
	root.add_child(dropdown)
	dropdown.position = Vector2(30,30)
	var actions: Array[String] = []
	dropdown.activated.connect(func(id): actions.append(id))
	check(dropdown.set_items([{"id":"a","label":"同名"},{"id":"off","label":"禁用","disabled":true},{"id":"b","label":"同名"}])==OK,"set stable ID items")
	check(dropdown.get_selected_id()=="a","initial first available")
	check(dropdown.set_selected_id("b") and actions.is_empty(),"programmatic selection is silent")
	check(not dropdown.set_selected_id("off"),"disabled selection refused")
	dropdown.set_items([{"id":"b","label":"改名"},{"separator":true},{"id":"a","label":"同名"},{"id":"off","label":"禁用","disabled":true}])
	check(dropdown.get_selected_id()=="b" and dropdown.text.contains("改名"),"reorder/rename keeps stable identity")
	dropdown.open_menu()
	await process_frame
	check(dropdown.is_menu_open(),"popup opens")
	# Input goes through the actual popup window, not an emitted selection signal.
	var popup: Window = dropdown.find_children("*","Window",true,false)[0]
	var key := InputEventKey.new()
	key.pressed = true
	key.keycode = KEY_DOWN
	popup.push_input(key)
	key = key.duplicate()
	key.keycode = KEY_ENTER
	popup.push_input(key)
	await process_frame
	check(actions == ["a"] and dropdown.get_selected_id()=="a","keyboard selects next enabled by stable ID")
	check(not dropdown.is_menu_open(),"selection closes popup")
	dropdown.disabled = true
	dropdown.open_menu()
	check(not dropdown.is_menu_open(),"disabled trigger does not open")
	await _check_pointer_close_and_focus()
	dropdown.queue_free()
	await process_frame
	print("Unified dropdown: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func _check_pointer_close_and_focus() -> void:
	var dropdown = load("res://scenes/ui/components/unified_dropdown.tscn").instantiate()
	dropdown.window_system = preload("res://src/platform/window_system.gd").new()
	root.add_child(dropdown)
	dropdown.position = Vector2(300,30)
	dropdown.set_items([{"id":"a","label":"A"},{"id":"b","label":"B"}])
	await process_frame
	var point: Vector2 = dropdown.get_global_rect().get_center()
	await _click(point)
	check(dropdown.is_menu_open(),"pointer opens the menu")
	await _click(point)
	check(not dropdown.is_menu_open(),"pointer closes the menu")
	check(not dropdown.button_pressed,"pointer close clears the pressed state")
	check(not _focus_ring_visible(dropdown),"pointer close suppresses the residual focus ring")
	await _click(point)
	await _click(point)
	await _click(point,true)
	check(not dropdown.is_menu_open(),"double click leaves the menu closed")
	check(not dropdown.button_pressed,"double click leaves the trigger unpressed")
	check(not _focus_ring_visible(dropdown),"double click leaves no focus ring")
	await _move_pointer(Vector2(2,root.size.y-2))
	check(not dropdown.is_hovered(),"moving out clears the pointer hover state")
	var other := Button.new()
	root.add_child(other)
	other.grab_focus()
	await process_frame
	dropdown.grab_focus()
	await process_frame
	check(_focus_ring_visible(dropdown),"keyboard focus restores the visible focus ring")
	var focus := dropdown.get_theme_stylebox("focus") as StyleBoxFlat
	check(focus != null and focus.border_width_left == 2,"keyboard focus keeps the cyan outline")
	dropdown.open_menu()
	await process_frame
	check(not _focus_ring_visible(dropdown),"open menu suppresses the trigger focus ring")
	dropdown.close_menu()
	await process_frame
	check(not dropdown.button_pressed,"programmatic close clears the pressed state")
	dropdown.grab_focus()
	await process_frame
	check(_focus_ring_visible(dropdown),"keyboard focus returns when the menu is closed")
	other.queue_free()
	dropdown.queue_free()
	await process_frame
