extends SceneTree
## #189：图片入口必须能用键盘到达并激活，预览关闭后焦点回到来源。
const Bubble = preload("res://scenes/ui/message_bubble.tscn")
const SourceScene = preload("res://scenes/ui/dynamics_window.tscn")
var failures: Array[String] = []

func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)

func _initialize() -> void:
	run.call_deferred()

func run() -> void:
	var path := "user://image-keyboard-%s.cfg" % Time.get_ticks_usec()
	var presenter = load("res://src/ui/image_presenter.gd").new(
		load("res://src/storage/window_geometry.gd").new(path), load("res://src/platform/godot_window_system.gd").new())
	root.add_child(presenter)
	var source: Window = SourceScene.instantiate()
	root.add_child(source)
	source.open()
	var texture := ImageTexture.create_from_image(Image.create(40, 20, false, Image.FORMAT_RGBA8))
	var bubble: Control = Bubble.instantiate()
	source.add_child(bubble)
	bubble.size = Vector2(620, 420)
	bubble.configure({"id":"keyboard","role":"user","text":"","status":"sent"}, texture)
	await settle()
	_check_entries_take_focus(bubble)
	await _check_keys_match_the_mouse(source, bubble, texture)
	_check_focus_is_visible(bubble.get_node("%Picture"))
	var image_window = await _check_escape_returns_focus(presenter, source, bubble.get_node("%Picture"), texture)
	_check_failure_keeps_a_keyboard_exit(presenter, source, image_window, texture)
	presenter.queue_free()
	source.queue_free()
	await process_frame
	DirAccess.remove_absolute(path)
	print("Image keyboard: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func settle() -> void:
	for frame in 10: await process_frame

func press(window: Window, keycode: Key) -> void:
	for pressed in [true, false]:
		var event := InputEventKey.new()
		event.keycode = keycode
		event.physical_keycode = keycode
		event.pressed = pressed
		window.push_input(event, true)
		await process_frame
	await process_frame

func click(window: Window, control: Control) -> void:
	var point := control.get_global_rect().get_center()
	for pressed in [true, false]:
		var event := InputEventMouseButton.new()
		event.button_index = MOUSE_BUTTON_LEFT
		event.position = point
		event.global_position = point
		event.pressed = pressed
		window.push_input(event, true)
		await process_frame

func _check_entries_take_focus(bubble: Control) -> void:
	for name in ["HistoryPicture", "Picture"]:
		check(bubble.get_node("%" + name).focus_mode == Control.FOCUS_ALL, "image entry is keyboard focusable: " + name)

## 鼠标点击、Enter、Space 必须走同一条激活路径。
func _check_keys_match_the_mouse(source: Window, bubble: Control, texture: Texture2D) -> void:
	var picture: TextureRect = bubble.get_node("%Picture")
	var opened: Array[Texture2D] = []
	bubble.image_opened.connect(func(value): opened.append(value))
	await click(source, picture)
	check(opened.size() == 1 and opened[0] == texture, "mouse click opens the picture")
	picture.grab_focus()
	await settle()
	await press(source, KEY_ENTER)
	check(opened.size() == 2, "Enter opens the picture")
	await press(source, KEY_SPACE)
	check(opened.size() == 3, "Space opens the picture")
	var history: TextureRect = bubble.get_node("%HistoryPicture")
	var actions: Array[String] = []
	bubble.image_action.connect(func(value): actions.append(value))
	history.show()
	history.grab_focus()
	await settle()
	await press(source, KEY_ENTER)
	check(actions == ["preview"], "history thumbnail previews from the keyboard")

func _check_focus_is_visible(picture: TextureRect) -> void:
	var style := picture.get_theme_stylebox("focus", "ImageEntry")
	check(style is StyleBoxFlat, "image entry has a focus surface")
	if style is StyleBoxFlat:
		check(style.border_width_left > 0 and style.border_width_right > 0, "focus ring is visible on the entry")
		check(style.border_color.is_equal_approx(Color("66ccff")), "focus ring uses the accent colour")

func _check_escape_returns_focus(presenter: Node, source: Window, picture: TextureRect, texture: Texture2D) -> Window:
	picture.grab_focus()
	await settle()
	check(picture.has_focus(), "image entry really holds focus before opening")
	var image_window: Window = presenter.open_image(source, func(): return texture)
	await settle()
	check(image_window.visible, "preview opens from the image entry")
	await press(image_window, KEY_ESCAPE)
	check(not image_window.visible, "Esc closes the preview")
	check(picture.has_focus(), "closing the preview returns focus to its entry")
	return image_window

## 失败态也必须能用键盘退出：重试成功或直接关闭。
func _check_failure_keeps_a_keyboard_exit(presenter: Node, source: Window, image_window: Window, texture: Texture2D) -> void:
	var attempts: Array[int] = [0]
	presenter.open_image(source, func():
		attempts[0] += 1
		return null if attempts[0] == 1 else texture)
	await settle()
	check(image_window.get_node("%ImageError").visible, "failed load reports the state")
	check(image_window.get_node("%RetryImage").has_focus(), "failure puts keyboard focus on retry")
	await press(image_window, KEY_ENTER)
	check(image_window.get_node("%Picture").texture == texture, "Enter retries the image")
	check(image_window.get_node("%CloseImage").has_focus(), "retry leaves focus on a usable action")
	await press(image_window, KEY_ESCAPE)
	check(not image_window.visible, "Esc closes a preview that was retried")
