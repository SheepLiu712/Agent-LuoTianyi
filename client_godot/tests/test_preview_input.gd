extends SceneTree
var failures: Array[String] = []

func check(value: bool, label: String) -> void:
	if not value:
		failures.append(label)
		print("FAIL: ", label)

func _initialize() -> void:
	call_deferred("run")

func key(shift: bool) -> void:
	var event := InputEventKey.new()
	event.keycode = KEY_ENTER
	event.pressed = true
	event.shift_pressed = shift
	Input.parse_input_event(event)
	await process_frame
	event.pressed = false
	Input.parse_input_event(event)
	await process_frame

func run() -> void:
	const SCENE := "res://scenes/preview/chat_preview.tscn"
	check(ResourceLoader.exists(SCENE), "offline preview has a scene in its module")
	if not failures.is_empty():
		quit(1)
		return
	var scene = load(SCENE).instantiate()
	for name in ["Split", "AvatarPanel", "Expressions", "Scenarios", "Messages", "Empty", "Input", "ImagePicker"]:
		check(scene.get_node_or_null("%" + name) != null, "preview layout exists before ready: " + name)
	root.add_child(scene)
	await process_frame
	await process_frame
	var inputs: Array[Node] = scene.find_children("*", "TextEdit", true, false)
	check(inputs.size() == 1, "single visible composer")
	if inputs.size() == 1:
		var editor: TextEdit = inputs[0]
		editor.grab_focus()
		editor.text = "界面输入回归"
		await key(false)
		check(editor.text.is_empty(), "Enter submits and clears composer")
		await process_frame
		var found := false
		for label in scene.find_children("*", "RichTextLabel", true, false):
			found = found or label.get_parsed_text() == "界面输入回归"
		check(found, "submitted text visible in bubble")
		editor.text = "第一行"
		editor.set_caret_column(3)
		await key(true)
		check(editor.text.contains("\n"), "Shift Enter inserts newline")
		editor.text = " \n "
		await key(false)
		check(not editor.text.is_empty(), "blank input retained")
		var scenarios: OptionButton = scene.get_node("%Scenarios")
		for index in [1, 2, 3, 4, 0]:
			scenarios.select(index)
			scenarios.item_selected.emit(index)
			await process_frame
			await process_frame
			check(scene.get_node("%Empty").visible == (index in [1, 2, 3]), "empty state visibility for scenario " + str(index))
			if index in [2, 3]:
				editor.text = "失败时保留草稿"
				await key(false)
				check(editor.text == "失败时保留草稿", "unavailable scenario retains draft")
		var image := Image.create(8, 8, false, Image.FORMAT_RGBA8)
		image.fill(Color.BLUE)
		editor.image_pasted.emit(image)
		await process_frame
		var overlays: Array[Node] = root.find_children("ImageWindow", "Window", true, false)
		check(overlays.size() == 1, "pasted image opens one preview")
		if overlays.size() == 1:
			var close: Button = overlays[0].get_node("%CloseImage")
			check(close.text == "取消", "pending image can be canceled")
			close.pressed.emit()
			await process_frame
			check(not overlays[0].visible, "cancel hides the reusable image preview")
	await create_timer(1.0).timeout
	scene.queue_free()
	await process_frame
	print("Preview input: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
