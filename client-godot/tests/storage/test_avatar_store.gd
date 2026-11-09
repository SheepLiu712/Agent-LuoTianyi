extends SceneTree
const AvatarStore = preload("res://src/storage/avatar_store.gd")
const Attachment = preload("res://src/media/image_attachment.gd")
var failures: Array[String] = []

func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)

func _initialize() -> void:
	run.call_deferred()

func run() -> void:
	var root := "user://avatar-test-%s" % Time.get_ticks_usec()
	var store = AvatarStore.new(root)
	store.set_scope("https://example.com", "A")
	check(store.path().begins_with(root), "avatar path lives under the data root")
	check(store.load_texture() == null, "missing avatar reads as no texture")
	check(not store.has_avatar(), "missing avatar reports no custom image")
	_check_save(store)
	_check_isolation(store)
	_check_rejections(store)
	check(store.clear() == OK and store.load_texture() == null, "clear removes the avatar")
	_remove(root)
	print("Avatar store: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func _check_save(store: RefCounted) -> void:
	var saved: Dictionary = store.save(_png(512, 256))
	check(saved.ok and saved.texture != null, "valid image is accepted")
	if saved.texture != null:
		check(saved.texture.get_width() == 256 and saved.texture.get_height() == 256, "stored avatar is squared to 256")
	check(store.has_avatar(), "saved avatar reports a custom image")
	check(not FileAccess.file_exists(store.path() + ".tmp"), "no temporary file is left behind")
	var reloaded: Texture2D = store.load_texture()
	check(reloaded != null and reloaded.get_width() == 256, "avatar reads back at 256px")

func _check_isolation(store: RefCounted) -> void:
	store.set_scope("https://example.com", "B")
	check(store.load_texture() == null, "another account starts without an avatar")
	store.set_scope("https://example.com", "A")
	check(store.load_texture() != null, "the first account keeps its own avatar")

func _check_rejections(store: RefCounted) -> void:
	var bmp := Image.create(64, 64, false, Image.FORMAT_RGBA8)
	bmp.fill(Color(1, 1, 1, 1))
	var bmp_bytes := bmp.save_png_to_buffer()
	bmp_bytes[0] = 0x42
	bmp_bytes[1] = 0x4d
	var rejected: Dictionary = store.save(bmp_bytes)
	check(not rejected.ok and rejected.code == "IMAGE_FORMAT", "bitmap uploads are refused")
	var oversized := PackedByteArray()
	oversized.resize(Attachment.MAX_BYTES + 1)
	check(store.save(oversized).code == "IMAGE_TOO_LARGE", "oversized uploads are refused")
	check(store.save(PackedByteArray()).code == "IMAGE_FORMAT", "empty uploads are refused")
	check(store.load_texture() != null, "rejected uploads leave the previous avatar intact")

func _png(width: int, height: int) -> PackedByteArray:
	var image := Image.create(width, height, false, Image.FORMAT_RGBA8)
	image.fill(Color(0.4, 0.8, 1, 1))
	return image.save_png_to_buffer()

func _remove(path: String) -> void:
	var directory := ProjectSettings.globalize_path(path)
	if not DirAccess.dir_exists_absolute(directory):
		return
	for folder in DirAccess.get_directories_at(directory):
		_remove_absolute(directory.path_join(folder))
	for file in DirAccess.get_files_at(directory):
		DirAccess.remove_absolute(directory.path_join(file))
	DirAccess.remove_absolute(directory)

func _remove_absolute(directory: String) -> void:
	for folder in DirAccess.get_directories_at(directory):
		_remove_absolute(directory.path_join(folder))
	for file in DirAccess.get_files_at(directory):
		DirAccess.remove_absolute(directory.path_join(file))
	DirAccess.remove_absolute(directory)
