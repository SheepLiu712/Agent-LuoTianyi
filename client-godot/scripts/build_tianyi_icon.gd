extends SceneTree
## 一次性生成器：把登录页的天依头部特写做成聊天用头像。
## 只保留非透明包围盒，等比缩到画布的 88% 居中留白，避免圆形遮罩切到头发与下巴。
const SOURCE := "res://assets/ui/login_portrait.png"
const TARGET := "res://assets/ui/tianyi_icon.png"
const SIZE := 256
const FILL := 0.88

func _initialize() -> void:
	run.call_deferred()

func run() -> void:
	var source := Image.load_from_file(ProjectSettings.globalize_path(SOURCE))
	if source == null:
		push_error("Cannot read " + SOURCE)
		quit(1)
		return
	var art := _trim(source)
	var canvas := Image.create(SIZE, SIZE, false, Image.FORMAT_RGBA8)
	canvas.fill(Color(0, 0, 0, 0))
	var scaled := _fit(art, int(round(SIZE * FILL)))
	canvas.blend_rect(scaled, Rect2i(Vector2i.ZERO, scaled.get_size()), _origin(scaled))
	if canvas.save_png(ProjectSettings.globalize_path(TARGET)) != OK:
		push_error("Cannot write " + TARGET)
		quit(1)
		return
	var bytes := FileAccess.get_file_as_bytes(ProjectSettings.globalize_path(TARGET))
	print("tianyi icon: %sx%s sha256=%s" % [canvas.get_width(), canvas.get_height(), _sha256(bytes)])
	quit(0)

func _sha256(bytes: PackedByteArray) -> String:
	var context := HashingContext.new()
	context.start(HashingContext.HASH_SHA256)
	context.update(bytes)
	return context.finish().hex_encode()

## 全透明图没有包围盒，此时按原图处理，避免裁出 0 像素。
func _trim(source: Image) -> Image:
	var image := source.duplicate() as Image
	if image.get_format() != Image.FORMAT_RGBA8:
		image.convert(Image.FORMAT_RGBA8)
	var used := image.get_used_rect()
	if used.size.x <= 0 or used.size.y <= 0:
		return image
	return image.get_region(used)

## 等比缩放到长边不超过 side；小图也放大，保证所有头像在同一画布下视觉等大。
func _fit(image: Image, side: int) -> Image:
	var scaled := image.duplicate() as Image
	var source_side := maxi(image.get_width(), image.get_height())
	var factor := float(side) / float(maxi(1, source_side))
	var width := maxi(1, int(round(image.get_width() * factor)))
	var height := maxi(1, int(round(image.get_height() * factor)))
	scaled.resize(width, height, Image.INTERPOLATE_LANCZOS)
	return scaled

func _origin(scaled: Image) -> Vector2i:
	return Vector2i((SIZE - scaled.get_width()) / 2, (SIZE - scaled.get_height()) / 2)
