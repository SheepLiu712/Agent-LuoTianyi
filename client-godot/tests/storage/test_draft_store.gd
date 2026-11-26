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
	var root := "user://draft-store-test-%s" % Time.get_ticks_usec()
	DirAccess.make_dir_recursive_absolute(root)
	var store = load("res://src/storage/draft_store.gd").new(root)
	var scope_a := "scope-a"
	var scope_b := "scope-b"

	check(store.write_text(scope_a, "chat.text", "你好\n第二行") == OK, "text write succeeds")
	check(store.read_text(scope_a, "chat.text") == "你好\n第二行", "text round trips")
	check(store.write_text(scope_b, "chat.text", "another account") == OK, "second scope write succeeds")
	check(store.read_text(scope_a, "chat.text") == "你好\n第二行", "scopes are isolated")
	check(store.read_text(scope_b, "chat.text") == "another account", "second scope reads itself")

	var reloaded = load("res://src/storage/draft_store.gd").new(root)
	check(reloaded.read_text(scope_a, "chat.text") == "你好\n第二行", "text survives store recreation")
	check(reloaded.write_text(scope_a, "chat.text", "   ") == OK, "empty text clears")
	check(reloaded.read_text(scope_a, "chat.text").is_empty(), "cleared text reads empty")

	var image := Image.create(4, 4, false, Image.FORMAT_RGB8)
	image.fill(Color(0.2, 0.4, 0.8))
	var bytes := image.save_png_to_buffer()
	check(reloaded.write_attachment(scope_a, "chat.image", bytes, "image/png") == OK, "image write succeeds")
	var attachment: Dictionary = reloaded.read_attachment(scope_a, "chat.image")
	check(bool(attachment.get("ok", false)), "image read succeeds")
	check(attachment.get("bytes", PackedByteArray()) == bytes, "image bytes round trip")
	check(str(attachment.get("mime", "")) == "image/png", "image mime round trips")

	var image_path: String = reloaded._attachment_path(scope_a, "chat.image")
	DirAccess.remove_absolute(image_path)
	var missing: Dictionary = reloaded.read_attachment(scope_a, "chat.image")
	check(not bool(missing.get("ok", true)) and str(missing.get("code", "")) == "IMAGE_MISSING", "missing image reports code")
	check(reloaded.read_attachment(scope_a, "chat.image").is_empty(), "missing image metadata is cleaned")

	check(reloaded.write_text(scope_b, "broken", "value") == OK, "seed corrupt document")
	var document_path: String = reloaded._document_path(scope_b)
	var file := FileAccess.open(document_path, FileAccess.WRITE)
	file.store_string("{not valid json")
	file.close()
	var corrupt = load("res://src/storage/draft_store.gd").new(root)
	check(corrupt.read_text(scope_b, "broken").is_empty(), "corrupt document is ignored")
	check(corrupt.write_text(scope_b, "broken", "recovered") == OK, "corrupt document can be replaced")
	check(corrupt.read_text(scope_b, "broken") == "recovered", "replacement text reads back")

	var blocked := root.path_join("blocked")
	var blocker := FileAccess.open(blocked, FileAccess.WRITE)
	blocker.store_string("not a directory")
	blocker.close()
	var failing = load("res://src/storage/draft_store.gd").new(blocked)
	check(failing.write_text(scope_a, "chat.text", "cannot save") != OK, "write failure is reported")

	remove_folder(root)
	print("Draft store: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func remove_folder(path: String) -> void:
	for folder in DirAccess.get_directories_at(path):
		remove_folder(path.path_join(folder))
	for file in DirAccess.get_files_at(path):
		DirAccess.remove_absolute(path.path_join(file))
	DirAccess.remove_absolute(path)
