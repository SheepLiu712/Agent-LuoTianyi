extends SceneTree
var failures: Array[String] = []
class BrowserStub extends RefCounted:
	var calls := 0
	func open_project() -> Error:
		calls += 1
		return ERR_CANT_OPEN

func _initialize() -> void: run.call_deferred()
func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)
func until(predicate: Callable) -> bool:
	var deadline := Time.get_ticks_msec() + 5000
	while not predicate.call() and Time.get_ticks_msec() < deadline: await process_frame
	return predicate.call()
func press(view: Node, name: String) -> void:
	view.get_node("%" + name).pressed.emit()
func capture(label: String) -> void:
	if DisplayServer.get_name() == "headless": return
	await create_timer(.15).timeout
	await RenderingServer.frame_post_draw
	var pixels := root.get_texture().get_image()
	check(pixels.save_png("res://artifacts/release-013/" + label + ".png") == OK, "capture " + label)

func run() -> void:
	var scene: PackedScene = load("res://scenes/ui/account_view.tscn")
	var candidate := scene.instantiate()
	for name in ["MenuButton","CloseLogin","RegisterLink","ResetLink","AutoLogin","Remember","SavedLogin","UsePassword","HistoryButton","ServerDialog","ServerSave","ServerCancel","Feedback","FeedbackAddress"]:
		check(candidate.get_node_or_null("%" + name) != null, "scene authors " + name)
	check(candidate.has_method("select_mode") and candidate.has_signal("feedback_requested"), "account view exposes navigation and feedback")
	check(candidate.get_node_or_null("%AccountMode") == null, "old account-mode dropdown is removed")
	candidate.free()
	if not failures.is_empty():
		quit(1)
		return
	DirAccess.make_dir_recursive_absolute("res://artifacts/release-013")
	var path := "user://login-ui-%s" % Time.get_ticks_usec()
	var security = ClassDB.instantiate("WindowsSecurity")
	var storage = load("res://src/storage/godot_storage_service.gd").new(path+"/account.cfg",load("res://src/storage/credential_store.gd").new(security,path+"/tokens"))
	var session = load("res://src/session/account_session.gd").new(load("res://src/network/account_api.gd").new(security),storage)
	var browser := BrowserStub.new()
	var app = load("res://scenes/main.tscn").instantiate()
	app.setup(session,path+"/window.cfg",browser)
	root.add_child(app)
	app.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	await create_timer(.1).timeout
	var view: Control = app.get_node("%AccountForm")
	check(not view.get_node("%Server").is_visible_in_tree(), "server address is not part of the login form")
	check(view.get_node("%RegisterLink").visible and view.get_node("%ResetLink").visible, "bottom register and forgotten-password links are visible")
	await capture("login-default")
	if DisplayServer.get_name() != "headless":
		check(root.borderless and root.transparent and root.transparent_bg and root.unresizable, "login uses a fixed transparent native window")
		check(root.size == Vector2i(480,690), "compact login has the approved default dimensions")
		var pixels := root.get_texture().get_image()
		check(pixels.get_pixel(0,0).a < .1 and pixels.get_pixel(12,100).is_equal_approx(Color.WHITE), "rounded outside is transparent and body is white")
	press(view,"MenuButton")
	check(view.get_node("%MenuPopup").visible, "menu opens below the trigger")
	await capture("login-menu")
	press(view,"SetServer")
	check(view.get_node("%ServerDialog").visible, "server settings is an owned temporary window")
	view.get_node("%Server").text = OS.get_environment("GODOT_TEST_SERVER")
	press(view,"ServerSave")
	check(await until(func(): return not view.get_node("%ServerDialog").visible), "successful verification closes server editor")
	check(session.get_login_defaults().server == OS.get_environment("GODOT_TEST_SERVER"), "validated address becomes current")
	press(view,"MenuButton")
	press(view,"Logs")
	var logs = app.find_child("LogWindow",true,false)
	check(logs.visible, "pre-login log action opens the existing log window")
	press(view,"MenuButton")
	press(view,"Feedback")
	check(browser.calls == 1 and view.get_node("%FeedbackAddress").visible, "external-link failure is reported without platform calls in the view")
	check(view.get_node("%FeedbackAddress").text == "https://github.com/SheepLiu712/Agent-LuoTianyi", "feedback uses the approved project URL")
	view.get_node("%AutoLogin").button_pressed = true
	check(view.get_node("%Remember").button_pressed, "automatic login enables remember")
	view.get_node("%Remember").button_pressed = false
	check(not view.get_node("%AutoLogin").button_pressed, "forget disables automatic login")
	press(view,"ResetLink")
	view.get_node("%Username").text = "test"
	view.get_node("%Password").text = "secret draft"
	view.get_node("%Invite").text = "private invite"
	press(view,"BackToLogin")
	check(view.get_node("%Username").text == "test" and view.get_node("%Password").text.is_empty() and view.get_node("%Invite").text.is_empty(), "back keeps name and clears secrets")
	view.get_node("%Password").text = "synthetic-password"
	view.get_node("%Remember").button_pressed = true
	press(view,"Submit")
	check(await until(func(): return not session.get_session().is_empty()), "login publishes the real session")
	await process_frame
	if DisplayServer.get_name() != "headless":
		check(not root.borderless and not root.transparent and not root.transparent_bg and not root.unresizable, "signed-in workspace restores the system frame")
	check(logs.visible, "logs survive login")
	session.logout()
	await process_frame
	check(logs.visible and view.get_node("%Password").text.is_empty(), "logout restores login without closing logs or keeping passwords")
	press(view,"HistoryButton")
	check(view.get_node("%HistoryPopup").visible, "account history opens from its arrow")
	check(not view.get_node("%HistoryEmpty").visible, "successful account is listed")
	view.get_node("%HistoryPopup").hide()
	if DisplayServer.get_name() != "headless":
		check(root.borderless and root.unresizable, "logout restores compact presentation")
		for factor in [1.0,1.25,1.5,2.0]:
			root.content_scale_mode = Window.CONTENT_SCALE_MODE_CANVAS_ITEMS
			root.content_scale_factor = factor
			root.size = Vector2i(Vector2(480,690)*factor)
			await capture("login-scale-%s" % int(factor*100))
			var area := Rect2(Vector2.ZERO, root.get_visible_rect().size)
			for name in ["MenuButton","CloseLogin","Submit","ResetLink","RegisterLink"]:
				check(area.encloses(view.get_node("%"+name).get_global_rect()), "login action fits scale %s: %s" % [factor,name])
	app.queue_free()
	await process_frame
	remove_folder(path)
	print("Login presentation: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
func remove_folder(path: String) -> void:
	for folder in DirAccess.get_directories_at(path): remove_folder(path.path_join(folder))
	for file in DirAccess.get_files_at(path): DirAccess.remove_absolute(path.path_join(file))
	DirAccess.remove_absolute(path)
