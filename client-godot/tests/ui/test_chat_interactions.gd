extends SceneTree

const ChatScene = preload("res://scenes/ui/chat/chat_view.tscn")
const DecisionScene = preload("res://scenes/ui/components/decision_dialog.tscn")
const Coordinator = preload("res://src/application/window_coordinator.gd")
const UiStyle = preload("res://src/application/ui_style.gd")
const Store = preload("res://src/storage/godot_settings_store.gd")

var failures: Array[String] = []


class MockChatSession extends Node:
	signal message_audio_changed(id: String, state: Dictionary)
	signal message_image_changed(id: String, state: Dictionary)
	signal changed
	signal state_changed(state: Dictionary)

	var sent_images := 0
	var sent_texts: Array[String] = []

	func retry_history() -> void:
		pass

	func skip_history() -> void:
		pass

	func get_audio_state() -> Dictionary:
		return {"volume": 1.0, "playing": false, "queued": 0}

	func set_volume(_v: float) -> void:
		pass

	func get_state() -> Dictionary:
		return {"phase": "ready", "code": "", "messages": [], "history": {"phase": "done"}, "typing": false, "speaking": false, "thinking": false}

	func get_messages() -> Array[Dictionary]:
		return []

	func get_reading_state() -> Dictionary:
		return {"pending": false, "target_id": "", "located": true, "manual": false}

	func report_visible_messages(_ids: Array, _visible: bool) -> void:
		pass

	func get_user_avatar() -> Texture2D:
		return null

	func load_older_history() -> void:
		pass

	func note_read_interaction() -> void:
		pass

	func set_typing(_active: bool, _length: int = 0) -> void:
		pass

	func set_image_selecting(_active: bool) -> void:
		pass

	func send_image(_bytes: PackedByteArray, _mime: String) -> String:
		sent_images += 1
		return "img-%s" % sent_images

	func send_text(text: String) -> String:
		sent_texts.append(text)
		return "txt-%s" % sent_texts.size()


class StubImages extends Node:
	func close() -> void:
		pass


func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)


func _initialize() -> void:
	run.call_deferred()


func run() -> void:
	var path := "user://chat-interactions-%s.cfg" % Time.get_ticks_usec()
	await _test_volume_toggle_and_image_preview(path)
	await _test_logout_and_exit_dialog()
	DirAccess.remove_absolute(path)
	print("Chat interactions: ", "PASS" if failures.is_empty() else "FAIL: " + str(failures))
	quit(0 if failures.is_empty() else 1)


func _test_volume_toggle_and_image_preview(path: String) -> void:
	var style := UiStyle.new()
	style.configure(Store.new(path))
	var session := MockChatSession.new()
	root.add_child(session)
	var view = ChatScene.instantiate()
	view.setup(session)
	view.set_ui_style(style)
	root.add_child(view)
	await process_frame
	_check_volume_toggle(view)
	_check_image_preview_setting(view, session, style, path)
	view.queue_free()
	session.queue_free()
	await process_frame


func _check_volume_toggle(view: Node) -> void:
	var btn: Button = view.get_node("%VolumeButton")
	var popup: PopupPanel = view.get_node("%VolumePopup")
	btn.button_down.emit()
	btn.pressed.emit()
	check(popup.visible, "first click opens volume popup")
	btn.button_down.emit()
	popup.hide()
	btn.pressed.emit()
	check(not popup.visible, "second click keeps volume popup closed after press dismissal")
	btn.pressed.emit()
	check(popup.visible, "third click reopens volume popup")
	btn.pressed.emit()
	check(not popup.visible, "programmatic second press also closes volume popup")


func _check_image_preview_setting(view: Node, session: MockChatSession, style: RefCounted, path: String) -> void:
	var previews: Array[Callable] = []
	view.attachment_requested.connect(func(_provider, confirm): previews.append(confirm))
	var img := Image.create(8, 8, false, Image.FORMAT_RGB8)
	img.fill(Color("66ccff"))
	view.get_node("%Input").image_pasted.emit(img)
	check(previews.size() == 1 and view.get_node("%AttachmentBar").visible, "default_preview_image=true auto-opens preview")
	view.get_node("%RemoveImage").pressed.emit()
	check(style.save_preferences("flat", "svg", false, false) == OK, "saving default_preview_image=false succeeds")
	var restored := UiStyle.new()
	restored.configure(Store.new(path))
	check(not restored.default_preview_image, "default_preview_image=false persists across restarts")
	view.get_node("%Input").image_pasted.emit(img)
	check(previews.size() == 1 and view.get_node("%AttachmentBar").visible, "default_preview_image=false stages without popping preview")
	view.get_node("%PreviewImage").pressed.emit()
	check(previews.size() == 2, "manual preview button still opens review window")
	view.get_node("%Send").pressed.emit()
	check(session.sent_images == 1 and session.sent_texts.is_empty() and not view.get_node("%AttachmentBar").visible, "send button sends image-only attachment")


func _test_logout_and_exit_dialog() -> void:
	var host := Control.new()
	var dialog := DecisionScene.instantiate()
	var images := StubImages.new()
	host.add_child(dialog)
	host.add_child(images)
	root.add_child(host)
	await process_frame
	var draft_state := {"dirty": false}
	var coord := Coordinator.new(host, dialog, images, null, Callable(), Callable(), func(): return draft_state.dirty)
	coord.request_close("logout")
	check(dialog.visible and dialog.title == "退出登录" and dialog.dialog_text == "是否退出登录？", "logout without drafts asks concise question")
	check(dialog.ok_button_text == "是" and dialog.cancel_button_text == "否", "logout dialog uses yes/no buttons")
	dialog.get_cancel_button().pressed.emit()
	draft_state.dirty = true
	coord.request_close("logout")
	check(dialog.dialog_text.contains("是否退出登录") and dialog.dialog_text.contains("尚未提交"), "logout with drafts keeps draft warning")
	dialog.get_cancel_button().pressed.emit()
	coord.request_close("exit")
	check(dialog.ok_button_text == "放弃并继续" and dialog.cancel_button_text == "返回继续编辑", "exit dialog restores discard/continue buttons")
	dialog.get_cancel_button().pressed.emit()
	var exits := [0]
	var silent := Coordinator.new(host, dialog, images, null, Callable(), Callable(), func(): return true, null, func(): return true, func(): return [])
	silent.exit_requested.connect(func(): exits[0] += 1)
	silent.request_close("exit")
	check(exits[0] == 1 and not dialog.visible, "persisted drafts exit without a discard dialog")
	silent.dispose()
	coord.dispose()
	host.queue_free()
	await process_frame
