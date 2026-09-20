extends SceneTree
var failures: Array[String] = []
func check(value: bool,label: String) -> void:
	if not value:
		failures.append(label)
		print("FAIL: ",label)
func _initialize() -> void:
	_run.call_deferred()
func _run() -> void:
	if not ResourceLoader.exists("res://scenes/ui/unified_dropdown.tscn"):
		check(false,"shared dropdown scene available")
		quit(1)
		return
	root.size = Vector2i(700,500)
	var dropdown = load("res://scenes/ui/unified_dropdown.tscn").instantiate()
	root.add_child(dropdown)
	dropdown.position = Vector2(30,30)
	var actions: Array[String] = []
	dropdown.activated.connect(func(id): actions.append(id))
	check(dropdown.set_items([{"id":"a","label":"同名"},{"id":"off","label":"禁用","disabled":true},{"id":"b","label":"同名"}])==OK,"set stable ID items")
	check(dropdown.get_selected_id()=="a","initial first available")
	check(dropdown.set_selected_id("b") and actions.is_empty(),"programmatic selection is silent")
	check(not dropdown.set_selected_id("off"),"disabled selection refused")
	dropdown.set_items([{"id":"b","label":"改名"},{"id":"a","label":"同名"},{"id":"off","label":"禁用","disabled":true}])
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
	dropdown.queue_free()
	await process_frame
	print("Unified dropdown: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
