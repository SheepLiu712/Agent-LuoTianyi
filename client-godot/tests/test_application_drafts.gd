extends SceneTree
const APP_SCENE := "res://scenes/main.tscn"
var failures: Array[String] = []
var _step := "start"
func check(value: bool,text: String) -> void:
	if not value:
		failures.append(text)
		print("FAIL: ",text)
func _initialize() -> void:
	_run.call_deferred()
func _run() -> void:
	_watchdog()
	if not _scene_available():
		return
	var path := "user://draft-app-test-%s"%Time.get_ticks_usec()
	DirAccess.make_dir_recursive_absolute(path)
	var security = ClassDB.instantiate("WindowsSecurity")
	var session = load("res://src/session/account_session.gd").new(load("res://src/network/account_api.gd").new(security), load("res://src/storage/godot_storage_service.gd").new(path+"/account.cfg", load("res://src/storage/credential_store.gd").new(security,path+"/tokens")))
	var app = load(APP_SCENE).instantiate()
	app.setup(session,path+"/window.cfg")
	root.add_child(app)
	app.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	await process_frame
	await session.perform("login",OS.get_environment("GODOT_TEST_SERVER"),{"username":"ui","password":"synthetic-password"},false)
	await process_frame
	_step = "ui logged in"
	var workspace: Control = app.get_workspace()
	check(workspace.get_node_or_null("%AccountMenu") == null,"main navigation no longer owns account actions")
	var prewarmed = await _wait_for_prewarmed_settings(app)
	_check_settings_prewarm(prewarmed)
	await _check_settings_clean_reopen(app, prewarmed)
	var dynamics = workspace.get_node("%NavDynamics")
	var unread: Control = workspace.get_node("%DynamicsUnread")
	await _check_navigation_unread(dynamics, unread)
	dynamics.pressed.emit()
	await process_frame
	app.find_child("DynamicsWindow",true,false).get_node("%Publish").pressed.emit()
	await process_frame
	var draft = app.find_child("PublishDraft",true,false)
	check(draft != null,"publishing opens from dynamic navigation")
	draft.text = "unsaved dynamic"
	draft.text_changed.emit()
	workspace.get_node("%NavLogs").pressed.emit()
	var logs = app.find_child("LogWindow",true,false)
	workspace.get_node("%NavSettings").pressed.emit()
	await process_frame
	var window = app.find_child("SettingsWindow",true,false)
	check(window != null,"settings navigation opens unified window")
	check(window == prewarmed,"settings navigation reuses the prewarmed window")
	check(window.get_node_or_null("%LogoutButton") is Button,"settings provides logout action")
	if not _require_logout_button(window):
		app.queue_free()
		await process_frame
		_finish(path, 1)
		return
	window.get_node("%ModelsTab").pressed.emit()
	workspace.get_node("%NavSettings").pressed.emit()
	_check_reopen_preserves_selected_settings_page_and_singleton(app, window)
	window.get_node("%PreferencesTab").pressed.emit()
	var input: TextEdit = window.find_child("CustomContextField",true,false)
	var deadline := Time.get_ticks_msec()+2500
	await _wait_editable(input, deadline)
	input.text = "new draft"
	input.text_changed.emit()
	check(window.is_dirty(),"loaded form accepts draft edit")
	var chat = workspace.get_chat_view()
	chat.get_node("%Input").text = "unsent chat draft"
	var image := Image.create(4,4,false,Image.FORMAT_RGB8)
	chat.get_node("%Input").image_pasted.emit(image)
	root.close_requested.emit()
	_step = "exit prompt opened"
	var dialog = app.get_node("%ExitDialog")
	_check_exit_prompt_only_lists_settings(dialog)
	dialog.get_cancel_button().pressed.emit()
	_check_cancel_preserves_every_draft(chat, window, draft)
	window.get_node("%LogoutButton").pressed.emit()
	_check_logout_waits_for_decision(session, dialog)
	dialog.get_cancel_button().pressed.emit()
	window.get_node("%LogoutButton").pressed.emit()
	dialog.get_ok_button().pressed.emit()
	await process_frame
	_step = "first logout"
	check(session.get_session().is_empty(),"confirmed discard completes logout")
	_check_logout_closes_business_windows_but_preserves_logs(window, logs)
	await session.perform("login",OS.get_environment("GODOT_TEST_SERVER"),{"username":"ui","password":"synthetic-password"},false)
	await process_frame
	_step = "ui relogged in"
	workspace = app.get_workspace()
	chat = workspace.get_chat_view()
	check(chat.get_node("%Input").text == "unsent chat draft","chat text restores after relogin")
	check(chat.get_node("%AttachmentBar").visible,"chat image restores after relogin")
	check(chat.is_dirty(),"restored chat draft is dirty")
	workspace.get_node("%NavDynamics").pressed.emit()
	await process_frame
	await _check_restored_publish(app)
	_step = "restored dynamic checked"
	var restored_window = await _wait_for_prewarmed_settings(app)
	check(restored_window != null,"settings prewarms after relogin")
	workspace.get_node("%NavSettings").pressed.emit()
	await process_frame
	await _second_logout(restored_window, session, dialog)
	_step = "second logout"
	await session.perform("login",OS.get_environment("GODOT_TEST_SERVER"),{"username":"slow_save","password":"synthetic-password"},false)
	await process_frame
	_step = "slow_save logged in"
	workspace = app.get_workspace()
	chat = workspace.get_chat_view()
	check(not chat.is_dirty(),"another account does not inherit chat draft")
	workspace.get_node("%NavDynamics").pressed.emit()
	await process_frame
	await _check_isolated_publish(app)
	_step = "isolation checked"
	workspace.get_node("%NavSettings").pressed.emit()
	window = app.find_child("SettingsWindow",true,false)
	input = window.find_child("CustomContextField",true,false)
	deadline = Time.get_ticks_msec()+2500
	await _wait_editable(input, deadline)
	input.text = "save before logout"
	input.text_changed.emit()
	window.get_node("%SaveAll").pressed.emit()
	_check_save_exposes_processing_feedback(window)
	window.get_node("%LogoutButton").pressed.emit()
	check(not session.get_session().is_empty(),"logout waits for an in-flight save")
	deadline = Time.get_ticks_msec()+3000
	await _wait_logout(session, deadline)
	await process_frame
	_step = "slow save logout prompt"
	check(dialog.visible and dialog.dialog_text.contains("是否退出登录") and dialog.ok_button_text == "是" and dialog.cancel_button_text == "否", "completed save still asks for logout confirmation")
	dialog.get_ok_button().pressed.emit()
	await process_frame
	_check_completed_save_permits_logout_and_keeps_logs(session, window, logs)
	app.queue_free()
	await process_frame
	_step = "done"
	_finish(path, 0)

func _scene_available() -> bool:
	var exists := ResourceLoader.exists(APP_SCENE)
	check(exists,"application scene exists")
	if not exists:
		_finish("", 1)
	return exists


func _require_logout_button(window: Variant) -> bool:
	var button = window.get_node_or_null("%LogoutButton") if is_instance_valid(window) else null
	check(button is Button,"settings provides logout action")
	return button is Button


func _check_restored_publish(app: Variant) -> void:
	var dynamics = app.find_child("DynamicsWindow",true,false)
	if dynamics == null:
		check(false,"dynamics window reopens after relogin")
		return
	dynamics.get_node("%Publish").pressed.emit()
	await process_frame
	var draft = app.find_child("PublishDraft",true,false)
	check(draft != null and draft.text == "unsaved dynamic","publish draft restores after relogin")


func _second_logout(window: Variant, session: Variant, dialog: Variant) -> void:
	if window == null:
		check(false,"settings reopens for second logout")
		await session.logout()
		await process_frame
		return
	window.get_node("%LogoutButton").pressed.emit()
	await process_frame
	check(dialog.visible and dialog.dialog_text == "是否退出登录？","persisted drafts do not block logout")
	dialog.get_ok_button().pressed.emit()
	await process_frame
	await _wait_logout(session, Time.get_ticks_msec() + 3000)
	check(session.get_session().is_empty(),"second logout completes")


func _check_isolated_publish(app: Variant) -> void:
	var dynamics = app.find_child("DynamicsWindow",true,false)
	if dynamics == null:
		check(false,"dynamics window opens for isolated account")
		return
	dynamics.get_node("%Publish").pressed.emit()
	await process_frame
	var draft = app.find_child("PublishDraft",true,false)
	check(draft != null and draft.text.is_empty(),"another account does not inherit publish draft")
	if draft != null:
		draft.get_node("%CancelPublish").pressed.emit()
		await process_frame


func _wait_logout(session: Variant, deadline: int) -> void:
	while not session.get_session().is_empty() and Time.get_ticks_msec()<deadline:
		await process_frame


func _finish(path: String, _code: int = 0) -> void:
	if not path.is_empty():
		remove_folder(path)
	print("Application drafts: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func _watchdog() -> void:
	var timer := Timer.new()
	timer.wait_time = 90.0
	timer.one_shot = true
	timer.timeout.connect(func():
		print("TIMEOUT at step: ", _step)
		quit(2))
	root.add_child(timer)
	timer.start()
func remove_folder(path: String) -> void:
	for folder in DirAccess.get_directories_at(path): remove_folder(path.path_join(folder))
	for file in DirAccess.get_files_at(path): DirAccess.remove_absolute(path.path_join(file))
	DirAccess.remove_absolute(path)

func _check_exit_prompt_only_lists_settings(dialog: Variant) -> void:
	check(dialog.visible and dialog.dialog_text.contains("设置") and not dialog.dialog_text.contains("聊天") and not dialog.dialog_text.contains("动态"),"exit prompt only lists content that will be lost")

func _check_cancel_preserves_every_draft(chat: Variant, window: Variant, draft: Variant) -> void:
	check(chat.is_dirty() and chat.get_node("%Input").text == "unsent chat draft" and window.is_dirty() and draft.text == "unsaved dynamic" and chat.get_node("%AttachmentBar").visible,"cancel preserves every draft")

func _check_completed_save_permits_logout_and_keeps_logs(session: Variant, window: Variant, logs: Variant) -> void:
	check(session.get_session().is_empty() and not is_instance_valid(window) and logs.visible,"completed save permits logout and keeps logs")

func _check_reopen_preserves_selected_settings_page_and_singleton(app: Variant, window: Variant) -> void:
	check(app.find_children("SettingsWindow","Window",true,false).size() == 1 and window.get_node("%ModelPage").visible,"reopen preserves selected settings page and singleton")

func _check_logout_waits_for_decision(session: Variant, dialog: Variant) -> void:
	check(not session.get_session().is_empty() and dialog.visible,"logout waits for decision")

func _check_logout_closes_business_windows_but_preserves_logs(window: Variant, logs: Variant) -> void:
	check(not is_instance_valid(window) and logs.visible,"logout closes business windows but preserves logs")

func _check_save_exposes_processing_feedback(window: Variant) -> void:
	var toast: Control = window.get_node("%SaveToast")
	check(window.is_saving() and toast.visible and toast.last_text().contains("正在保存"),"save exposes processing feedback")

func _check_navigation_unread(dynamics: Button, unread: Control) -> void:
	var deadline := Time.get_ticks_msec() + 5000
	while dynamics.tooltip_text != "动态 · 1 条未读" and Time.get_ticks_msec() < deadline:
		await process_frame
	check(unread.visible and dynamics.text == "动态" and dynamics.tooltip_text == "动态 · 1 条未读", "navigation shows the unread dynamic count without changing reviewed label")

func _wait_editable(input: TextEdit, deadline: int) -> void:
	while not input.editable and Time.get_ticks_msec()<deadline: await process_frame

func _wait_for_prewarmed_settings(app: Variant) -> Variant:
	var deadline := Time.get_ticks_msec() + 5000
	while Time.get_ticks_msec() < deadline:
		var window = app.find_child("SettingsWindow",true,false)
		if window != null and window.is_data_settled(): return window
		await process_frame
	return null

func _check_settings_prewarm(window: Variant) -> void:
	check(window != null and not window.visible,"settings window is prewarmed hidden during login")
	check(window != null and window.is_data_settled(),"settings data settle before the user opens the window")
	check(window != null and window.get_node("%ModelPage").get_node("%Cards").get_child_count() > 0,"model cards are built during login prewarm")

func _check_settings_clean_reopen(app: Variant, window: Variant) -> void:
	app.get_workspace().get_node("%NavSettings").pressed.emit()
	await process_frame
	check(window.visible,"prewarmed settings opens")
	window.close_requested.emit()
	await process_frame
	check(not window.visible and is_instance_valid(window),"clean close keeps the settings cache")
	app.get_workspace().get_node("%NavSettings").pressed.emit()
	await process_frame
	check(window.visible and app.find_children("SettingsWindow","Window",true,false).size() == 1,"reopen reuses the settled settings window")
