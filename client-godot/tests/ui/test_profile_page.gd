extends SceneTree
## 头像页的核心契约：选完立刻落盘、失败按码给文案、不登录时不给点。
const Scene = preload("res://scenes/ui/profile_page.tscn")
const AvatarProfile = preload("res://src/session/avatar_profile.gd")
const AvatarStore = preload("res://src/storage/avatar_store.gd")
var failures: Array[String] = []
var _temp := ""

func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)

func _initialize() -> void:
	run.call_deferred()

func run() -> void:
	_temp = "user://profile-page-test-%s" % Time.get_ticks_usec()
	var picture := _write(_temp.path_join("me.png"), _png())
	var not_an_image := _write(_temp.path_join("notes.png"), "这不是图片".to_utf8_buffer())
	var page = Scene.instantiate()
	root.add_child(page)
	await process_frame
	var profile = AvatarProfile.new(AvatarStore.new(_temp.path_join("avatar")))
	profile.start({"server": "https://example.com", "username": "魂"})
	page.set_avatar_source(profile)
	await process_frame
	check(page.get_node("%Account").text == "魂", "profile page shows the signed-in account")
	check(page.get_node("%Preview").texture != null, "profile page falls back to the tianyi avatar")
	check(page.get_node("%Result").visible == false, "no result line before any action")
	_check_apply(page, picture)
	await _check_errors(page, not_an_image)
	_check_reset(page)
	await _check_without_account()
	page.queue_free()
	await process_frame
	profile.free()
	_remove(_temp)
	print("Profile page: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

## 选完就落盘：不发请求、不进草稿，页面自己给一句「已更新」。
func _check_apply(page: Node, picture: String) -> void:
	page.get_node("%FileDialog").file_selected.emit(picture)
	check(page.get_node("%Result").visible and page.get_node("%Result").text.contains("头像已更新"), "picked file reports success inline")
	check(page.get_node("%Preview").texture.get_width() == 256, "preview is replaced by the stored square avatar")
	check(not page.get_node("%ResetButton").disabled, "reset becomes available once a custom avatar exists")

## 失败既不落盘也不改图，只在页面内说清是读不到还是格式不对。
func _check_errors(page: Node, not_an_image: String) -> void:
	var before: Texture2D = page.get_node("%Preview").texture
	page.get_node("%FileDialog").file_selected.emit(_temp.path_join("missing.png"))
	var dialog := _error_dialog()
	check(page.get_node("%Result").text.is_empty() and dialog != null and dialog.get_current_text().contains("读不出来"), "unreadable picks explain the read failure through the error popup")
	page.get_node("%FileDialog").file_selected.emit(not_an_image)
	if dialog != null:
		dialog.get_node("%ErrorConfirm").pressed.emit()
	await process_frame
	check(dialog != null and dialog.get_current_text().contains("只支持"), "wrong formats name the accepted types")
	check(page.get_node("%Preview").texture == before, "failed picks leave the preview alone")
	await process_frame

func _check_reset(page: Node) -> void:
	page.get_node("%ResetButton").pressed.emit()
	check(page.get_node("%Result").text.contains("已恢复"), "reset reports that the default avatar is back")
	check(page.get_node("%ResetButton").disabled, "reset is disabled without a custom avatar")
	check(not page.get_node("%PickButton").disabled, "picking stays available after a reset")

func _check_without_account() -> void:
	var page = Scene.instantiate()
	root.add_child(page)
	await process_frame
	page.set_avatar_source(null)
	await process_frame
	check(page.get_node("%PickButton").disabled, "picking is disabled until an account is ready")
	check(page.get_node("%Account").text == "—", "no account is shown as a dash")
	page.queue_free()
	await process_frame

func _png() -> PackedByteArray:
	var image := Image.create(320, 200, false, Image.FORMAT_RGBA8)
	image.fill(Color(0.4, 0.8, 1, 1))
	return image.save_png_to_buffer()

func _error_dialog() -> Node:
	for child in root.find_children("*", "", true, false):
		if child.is_in_group("error_dialog"):
			return child
	return null

func _write(path: String, bytes: PackedByteArray) -> String:
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(_temp))
	var file := FileAccess.open(path, FileAccess.WRITE)
	file.store_buffer(bytes)
	file.close()
	return path

func _remove(path: String) -> void:
	var directory := ProjectSettings.globalize_path(path)
	if not DirAccess.dir_exists_absolute(directory): return
	for folder in DirAccess.get_directories_at(directory): _remove(directory.path_join(folder))
	for file in DirAccess.get_files_at(directory): DirAccess.remove_absolute(directory.path_join(file))
	DirAccess.remove_absolute(directory)
