extends SceneTree
const AvatarImage = preload("res://src/media/avatar_image.gd")
var failures: Array[String] = []

func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)

func _initialize() -> void:
	run.call_deferred()

func run() -> void:
	_check_landscape_keeps_its_centre()
	_check_portrait_keeps_its_centre()
	_check_small_image_is_upscaled()
	print("Avatar image: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func _check_landscape_keeps_its_centre() -> void:
	var source := Image.create(512, 256, false, Image.FORMAT_RGBA8)
	source.fill(Color(1, 0, 0, 1))
	source.fill_rect(Rect2i(192, 0, 128, 256), Color(0, 1, 0, 1))
	var squared := AvatarImage.fit_square(source, 256)
	check(squared.get_size() == Vector2i(256, 256), "landscape lands on a square canvas")
	check(_is_green(squared.get_pixel(128, 128)), "landscape keeps the centre strip")
	check(not _is_green(squared.get_pixel(2, 128)), "landscape drops the side margins")

func _check_portrait_keeps_its_centre() -> void:
	var source := Image.create(256, 512, false, Image.FORMAT_RGBA8)
	source.fill(Color(1, 0, 0, 1))
	source.fill_rect(Rect2i(0, 192, 256, 128), Color(0, 1, 0, 1))
	var squared := AvatarImage.fit_square(source, 256)
	check(squared.get_size() == Vector2i(256, 256), "portrait lands on a square canvas")
	check(_is_green(squared.get_pixel(128, 128)), "portrait keeps the centre strip")
	check(not _is_green(squared.get_pixel(128, 2)), "portrait drops the top and bottom margins")

func _check_small_image_is_upscaled() -> void:
	var source := Image.create(32, 32, false, Image.FORMAT_RGBA8)
	source.fill(Color(0, 0, 1, 1))
	var squared := AvatarImage.fit_square(source, 256)
	check(squared.get_size() == Vector2i(256, 256), "small images still reach the avatar canvas")
	check(squared.get_pixel(128, 128).b > .9, "upscaling keeps the colour")

func _is_green(color: Color) -> bool:
	return color.g > .9 and color.r < .1
