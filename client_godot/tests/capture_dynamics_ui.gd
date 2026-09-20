extends SceneTree
const WINDOW_SCENE := "res://scenes/ui/dynamics_window.tscn"
var failures: Array[String] = []
func check(ok: bool,label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ",label)
func _initialize() -> void:
	_run.call_deferred()
func _run() -> void:
	var controller = load("res://src/session/dynamics_controller.gd").new()
	root.add_child(controller)
	await controller.start({"server":OS.get_environment("GODOT_TEST_SERVER"),"username":"visual","message_token":"fixture-token"})
	await controller.refresh()
	var path := "user://dynamics-visual-%s.cfg"%Time.get_ticks_usec()
	if not ResourceLoader.exists(WINDOW_SCENE):
		check(false,"dynamics window scene exists")
		controller.queue_free()
		await process_frame
		quit(1)
		return
	var window = load(WINDOW_SCENE).instantiate()
	window.setup(controller,path)
	root.add_child(window)
	window.open()
	window.position = Vector2i(100,100)
	await capture(window,"list")
	var split: HSplitContainer = window.find_children("*","HSplitContainer",true,false)[0]
	check(absf(split.get_child(0).size.x/split.size.x-.45)<.02,"default split 45:55")
	window.select_post("d0")
	await create_timer(.3).timeout
	await capture(window,"detail")
	for button in window.find_children("*","Button",true,false):
		if button.text == "回复" and button.is_visible_in_tree():
			button.pressed.emit()
			break
	window.find_child("ReplyDraft",true,false).text = "这段旋律很好听，期待你下次分享。"
	await process_frame
	# The selected detail's public scroll interface exposes the entire inline composer.
	for scroll in window.find_children("*","ScrollContainer",true,false):
		if scroll.has_method("update_comments") and scroll.is_visible_in_tree(): scroll.scroll_vertical = 260
	await capture(window,"reply")
	for button in window.find_children("*","Button",true,false):
		if button.text == "发布动态": button.pressed.emit()
	await process_frame
	var publisher: Control = window.find_child("PublishOverlay",true,false)
	check(publisher != null and publisher.get_window() == window,"publisher is an in-window overlay")
	await capture(window,"publish")
	publisher.hide()
	window.size = Vector2i(900,640)
	await capture(window,"minimum")
	for factor in [1.25,1.5]:
		window.content_scale_mode = Window.CONTENT_SCALE_MODE_CANVAS_ITEMS
		window.content_scale_factor = factor
		window.size = Vector2i(Vector2(1000,780)*factor)
		await capture(window,"scale-%s"%int(factor*100))
	window.content_scale_factor = 1
	window.size = Vector2i(1000,780)
	window.mode = Window.MODE_MINIMIZED
	await create_timer(.15).timeout
	check(root.mode != Window.MODE_MINIMIZED,"minimizing dynamics leaves main window open")
	window.open()
	await create_timer(.15).timeout
	root.mode = Window.MODE_MINIMIZED
	await create_timer(.3).timeout
	var output: Array = []
	var code := OS.execute(OS.get_environment("GODOT_TEST_PYTHON"),[ProjectSettings.globalize_path("res://tests/verify_native_dynamics.py"),str(DisplayServer.window_get_native_handle(DisplayServer.WINDOW_HANDLE,root.get_window_id())),str(DisplayServer.window_get_native_handle(DisplayServer.WINDOW_HANDLE,window.get_window_id()))],output,true)
	print(output)
	check(code == 0,"Windows independent taskbar window")
	window.queue_free()
	controller.queue_free()
	await process_frame
	DirAccess.remove_absolute(path)
	print("Dynamics native screenshots: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
func capture(window: Window,suffix: String) -> void:
	await create_timer(.25).timeout
	await RenderingServer.frame_post_draw
	check(window.get_texture().get_image().save_png("res://artifacts/agentluo-011-dynamics-"+suffix+".png")==OK,"capture "+suffix)
