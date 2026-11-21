extends RefCounted
## 历史图片的统一解码口径：PNG/JPEG/WebP，限制字节、边长与总像素。
## 在线下载、Python 媒体导入与本地缓存读取共用，避免三处规则漂移。

const Attachment = preload("res://src/media/image_attachment.gd")
const MAX_BYTES := 16 * 1024 * 1024
const MAX_SIDE := 8192
const MAX_PIXELS := 16000000


static func decode(bytes: PackedByteArray) -> Image:
	if bytes.size() < 24 or bytes.size() > MAX_BYTES:
		return null
	var image := Image.new()
	if _decode_format(bytes, image) != OK:
		return null
	if image.get_width() > MAX_SIDE or image.get_height() > MAX_SIDE:
		return null
	if image.get_width() * image.get_height() > MAX_PIXELS:
		return null
	return image


static func _decode_format(bytes: PackedByteArray, image: Image) -> Error:
	if bytes.slice(0, 8).hex_encode() == "89504e470d0a1a0a":
		return image.load_png_from_buffer(bytes) if _header_ok(bytes, "image/png") else ERR_INVALID_DATA
	if bytes[0] == 255 and bytes[1] == 216:
		return image.load_jpg_from_buffer(bytes) if _header_ok(bytes, "image/jpeg") else ERR_INVALID_DATA
	if bytes.slice(0, 4).get_string_from_ascii() == "RIFF" and bytes.slice(8, 12).get_string_from_ascii() == "WEBP":
		return image.load_webp_from_buffer(bytes) if _header_ok(bytes, "image/webp") else ERR_INVALID_DATA
	return ERR_INVALID_DATA


static func _header_ok(bytes: PackedByteArray, mime: String) -> bool:
	var header: Dictionary = Attachment.header_dimensions(bytes, mime)
	if not header.get("ok", false):
		return false
	var width := int(header.get("width", 0))
	var height := int(header.get("height", 0))
	return width > 0 and height > 0 and width <= MAX_SIDE and height <= MAX_SIDE and width * height <= MAX_PIXELS
