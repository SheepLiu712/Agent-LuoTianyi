extends SceneTree

var failures: Array[String] = []


func _initialize() -> void:
	run.call_deferred()


func check(ok: bool, label: String) -> void:
	if ok:
		return
	failures.append(label)
	print("FAIL: ", label)


func run() -> void:
	var root_path := "user://draft-autosave-test-%s" % Time.get_ticks_usec()
	var store = load("res://src/storage/draft_store.gd").new(root_path)
	var editor := TextEdit.new()
	root.add_child(editor)
	var autosave = load("res://src/ui/draft_autosave.gd").new()
	autosave.bind(editor, store, "scope", "chat.text")

	editor.text = "自动保存"
	editor.text_changed.emit()
	await create_timer(0.5).timeout
	check(store.read_text("scope", "chat.text") == "自动保存", "debounced text reaches the store")

	editor.clear()
	autosave.clear()
	check(store.read_text("scope", "chat.text").is_empty(), "clear removes the stored draft")

	editor.text = "flush now"
	check(autosave.flush(), "flush reports success")
	check(store.read_text("scope", "chat.text") == "flush now", "flush writes without waiting")

	var restored := TextEdit.new()
	root.add_child(restored)
	var second = load("res://src/ui/draft_autosave.gd").new()
	second.bind(restored, store, "scope", "chat.text")
	check(restored.text == "flush now", "binding restores existing text")

	editor.queue_free()
	restored.queue_free()
	await process_frame
	_remove_folder(root_path)
	print("Draft autosave: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func _remove_folder(path: String) -> void:
	for folder in DirAccess.get_directories_at(path):
		_remove_folder(path.path_join(folder))
	for file in DirAccess.get_files_at(path):
		DirAccess.remove_absolute(path.path_join(file))
	DirAccess.remove_absolute(path)
