extends SceneTree
var failures: Array[String] = []
func check(ok: bool,label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ",label)
func _initialize() -> void:
	run.call_deferred()
func run() -> void:
	check(ResourceLoader.exists("res://scenes/ui/image_window.tscn"),"independent image scene exists")
	if not failures.is_empty():
		quit(1)
		return
	var path := "user://image-window-test-%s.cfg" % Time.get_ticks_usec()
	var presenter = load("res://src/ui/image_presenter.gd").new(path)
	root.add_child(presenter)
	var first = load("res://scenes/ui/dynamics_window.tscn").instantiate()
	var second = load("res://scenes/ui/dynamics_window.tscn").instantiate()
	root.add_child(first)
	root.add_child(second)
	first.open()
	second.open()
	var texture: Texture2D = load("res://assets/ui/bg2.jpg")
	var image_window = presenter.open_image(first,func(): return texture)
	check(image_window is Window and image_window.get_parent() == first,"image belongs to its source")
	var same_window = presenter.open_image(second,func(): return texture)
	check(same_window == image_window and image_window.get_parent() == second,"new source reuses singleton and transfers ownership")
	first.queue_free()
	await process_frame
	check(is_instance_valid(image_window),"closing former source does not close transferred image")
	var attempts: Array[int] = [0]
	presenter.open_image(second,func():
		attempts[0] += 1
		return null if attempts[0] == 1 else texture)
	check(image_window.get_node("%ImageError").visible,"failed load shows retryable error")
	image_window.get_node("%RetryImage").pressed.emit()
	check(not image_window.get_node("%ImageError").visible and image_window.get_node("%Picture").texture == texture,"retry loads through the same source")
	if DisplayServer.get_name() != "headless":
		second.mode = Window.MODE_MINIMIZED
		await create_timer(.2).timeout
		check(not image_window.visible,"image hides when current source minimizes")
		second.open()
		await create_timer(.2).timeout
		check(image_window.visible,"image returns when source restores")
	image_window.get_node("%OriginalSize").pressed.emit()
	check(image_window.get_node("%Picture").custom_minimum_size == texture.get_size(),"original size uses image pixels")
	image_window.close_requested.emit()
	check(not image_window.visible and image_window.get_node("%Picture").texture == null,"close releases image and hides window")
	presenter.open_image(second,func(): return texture)
	second.queue_free()
	await process_frame
	check(not is_instance_valid(image_window),"closing current source releases image window")
	presenter.queue_free()
	await process_frame
	DirAccess.remove_absolute(path)
	print("Image window: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
