extends SceneTree
const VIEW_SCENE := "res://scenes/ui/account_view.tscn"
const Session = preload("res://src/session/account_session.gd")
const Store = preload("res://src/storage/credential_store.gd")
const Api = preload("res://src/network/account_api.gd")
var failures: Array[String] = []

func check(value: bool, description: String) -> void:
	if not value:
		failures.append(description)
		print("FAIL: ", description)

func input(view: Control, hint: String) -> LineEdit:
	for node in view.find_children("*", "LineEdit", true, false):
		if node.placeholder_text == hint:
			return node
	return null

func press(view: Control, caption: String) -> void:
	for node in view.find_children("*", "Button", true, false):
		if node.text == caption and node.is_visible_in_tree():
			node.pressed.emit()
			return
	check(false, "visible action: " + caption)

func has_text(view: Control, text: String) -> bool:
	for label in view.find_children("*", "Label", true, false):
		if label.is_visible_in_tree() and label.text.contains(text):
			return true
	return false

func _initialize() -> void:
	call_deferred("run")

func run() -> void:
	check(ResourceLoader.exists(VIEW_SCENE),"account view scene exists")
	if not ResourceLoader.exists(VIEW_SCENE):
		print("Account view: ","FAIL")
		quit(1)
		return
	var folder := "user://account-view-test-%s" % Time.get_ticks_usec()
	DirAccess.make_dir_recursive_absolute(folder)
	var security = ClassDB.instantiate("WindowsSecurity")
	var session = Session.new(Api.new(security), load("res://src/storage/godot_storage_service.gd").new(folder + "/account.cfg", Store.new(security, folder + "/tokens")))
	root.add_child(session)
	var view = load(VIEW_SCENE).instantiate()
	view.setup(session)
	root.add_child(view)
	view.size = Vector2(500, 650)
	await process_frame
	var server := input(view, "服务器地址")
	var username := input(view, "用户名")
	var password := input(view, "密码")
	check(server != null and username != null and password != null, "account form is available")
	if server != null and username != null and password != null:
		server.text = OS.get_environment("GODOT_TEST_SERVER")
		username.text = "reject"
		password.text = "synthetic-password"
		press(view, "登录")
		await create_timer(0.4).timeout
		check(has_text(view, "用户名或密码错误"), "authentication rejection visible")
		check(password.text == "synthetic-password", "failed login preserves draft")
		var mode = view.find_child("AccountMode",true,false)
		mode.set_selected_id("register")
		mode.activated.emit("register")
		username.text = "test"
		input(view, "确认密码").text = "different"
		input(view, "邀请码").text = "invite-test"
		press(view, "注册")
		check(has_text(view, "两次输入的密码不一致"), "password confirmation checked locally")
		input(view, "确认密码").text = "synthetic-password"
		press(view, "注册")
		await create_timer(0.4).timeout
		check(has_text(view, "注册成功"), "registration success returns to login")
		check(password.text.is_empty() and input(view, "邀请码").text.is_empty(), "success clears sensitive fields")
		password.text = "synthetic-password"
		press(view, "登录")
		await create_timer(0.4).timeout
		check(not session.get_session().is_empty() and password.text.is_empty(), "successful login publishes session and clears password")
		press(view, "退出登录")
		check(session.get_session().is_empty() and server.is_visible_in_tree(), "logout restores account form")
	view.queue_free()
	session.queue_free()
	await process_frame
	DirAccess.remove_absolute(folder + "/account.cfg")
	DirAccess.remove_absolute(folder)
	print("Account view: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
