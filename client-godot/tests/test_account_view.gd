extends SceneTree
const VIEW_SCENE := "res://scenes/ui/pages/account_view.tscn"
const Session = preload("res://src/session/account_session.gd")
const Store = preload("res://src/storage/credential_store.gd")
const Api = preload("res://src/network/account_api.gd")
const AccountView = preload("res://src/ui/account_view.gd")
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

func has_text(view: Node, text: String) -> bool:
	for label in view.find_children("*", "Label", true, false):
		if label.is_visible_in_tree() and label.text.contains(text):
			return true
	return false

func focused_name(view: Control) -> String:
	var focused := view.get_viewport().gui_get_focus_owner()
	return "" if focused == null else String(focused.name)

func press_tab() -> void:
	var event := InputEventKey.new()
	event.keycode = KEY_TAB
	event.physical_keycode = KEY_TAB
	event.pressed = true
	root.push_input(event)

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
	_check_account_form_is_available(server, username, password)
	_check_probe_controls(view)
	_check_tls_messages()
	await _check_probe_rejects_empty_address(view)
	if server != null and username != null and password != null:
		await check_focus_order(view, username)
		await session.set_server(OS.get_environment("GODOT_TEST_SERVER"))
		username.text = "reject"
		password.text = "synthetic-password"
		press(view, "登录")
		check(view.get_node("%Submit").text == "登录中", "submit button shows 登录中 while busy")
		await create_timer(0.4).timeout
		check(view.get_node("%Submit").text == "登录", "submit button restores 登录 text after busy")
		check(has_text(view.get_window(), "用户名或密码错误"), "authentication rejection visible in error dialog")
		check(not has_text(view, "用户名或密码错误"), "authentication rejection not duplicated in form")
		check(password.text == "synthetic-password", "failed login preserves draft")
		view.select_mode("register")
		username.text = "test"
		password.text = "synthetic-password"
		input(view, "确认密码").text = "different"
		input(view, "邀请码").text = "invite-test"
		press(view, "注册")
		check(has_text(view.get_window(), "两次输入的密码不一致"), "password confirmation checked locally")
		check(not has_text(view, "两次输入的密码不一致"), "password mismatch not duplicated in form")
		input(view, "确认密码").text = "synthetic-password"
		press(view, "注册")
		await create_timer(0.4).timeout
		check(has_text(view, "注册成功"), "registration success returns to login")
		check(password.text.is_empty() and input(view, "邀请码").text.is_empty(), "success clears sensitive fields")
		password.text = "synthetic-password"
		press(view, "登录")
		await create_timer(0.4).timeout
		check(not session.get_session().is_empty() and password.text.is_empty(), "successful login publishes session and clears password")
		session.logout()
		check(session.get_session().is_empty() and username.is_visible_in_tree(), "logout restores account form")
	view.queue_free()
	session.queue_free()
	await process_frame
	DirAccess.remove_absolute(folder + "/account.cfg")
	DirAccess.remove_absolute(folder)
	print("Account view: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func _check_account_form_is_available(server: Variant, username: Variant, password: Variant) -> void:
	check(server != null and username != null and password != null, "account form is available")

func _check_probe_controls(view: Control) -> void:
	var button := view.get_node_or_null("%ServerProbe") as Button
	var result := view.get_node_or_null("%ProbeResult") as Label
	check(button != null and button.text == "测试连通性", "server probe control exists")
	check(result != null and not result.visible, "probe result starts hidden")

func _check_tls_messages() -> void:
	var tls := AccountView._error_text("NETWORK_ERROR", 0, "RESULT_TLS_HANDSHAKE_ERROR")
	check(tls.contains("证书校验失败") and tls.contains("代理"), "tls certificate failure has a specific message")
	check(AccountView._error_text("PUBLIC_KEY_ERROR", 0, "RESULT_TLS_HANDSHAKE_ERROR") == tls,
		"tls detail overrides public key generic text")
	check(AccountView._is_tls_failure("TLS handshake error: -9984 (MBEDTLS_ERR_X509_CERT_VERIFY_FAILED)"),
		"engine certificate detail is recognized")
	check(not AccountView._is_tls_failure("RESULT_CANT_CONNECT"), "non-tls transport failure is not misclassified")
	check(AccountView._error_text("NETWORK_ERROR", 0, "RESULT_CANT_CONNECT") == "无法连接服务器，请检查地址和网络。",
		"non-tls network message is unchanged")
	var result := {"ok":false, "baseline":{"ok":true, "stage":"HTTP"}, "target":{"ok":false, "stage":"TLS"}}
	var hint := AccountView._probe_status_text(result, "fallback")
	check(hint.contains("公网正常") and hint.contains("TLS"), "probe result refines the tls hint")
	var both := {"ok":false, "baseline":{"ok":false, "stage":"DNS"}, "target":{"ok":false, "stage":"TLS"}}
	check(AccountView._probe_status_text(both, "fallback").contains("TLS 证书校验失败"),
		"tls hint without baseline is still specific")
	check(AccountView._probe_text({"stage":"TLS", "duration_ms":533}) == "TLS 证书校验失败 533ms",
		"probe line names the tls stage")

func _check_probe_rejects_empty_address(view: Control) -> void:
	view.get_node("%Server").text = ""
	view.get_node("%ServerProbe").pressed.emit()
	await process_frame
	var result := view.get_node("%ProbeResult") as Label
	check(result.visible and result.text.contains("地址无效"), "empty server address is rejected without network")

func check_focus_order(view: Control, username: LineEdit) -> void:
	username.focus_next = NodePath()
	username.grab_focus()
	await process_frame
	check(focused_name(view) == "Username", "login focus starts at the account field")
	press_tab()
	await process_frame
	check(focused_name(view) == "Password", "Tab moves from the account field directly to password")
	press_tab()
	await process_frame
	check(focused_name(view) == "AutoLogin", "Tab reaches automatic login after password")
	press_tab()
	await process_frame
	check(focused_name(view) == "Remember", "Tab reaches remember login after automatic login")
