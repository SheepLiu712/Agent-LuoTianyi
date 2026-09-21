extends RefCounted
const MAX_BYTES := 6 * 1024 * 1024 - 4096
const MAX_SIDE := 8192
const MAX_PIXELS := 16000000

static func from_image(image: Image) -> Dictionary:
	if image == null or image.is_empty(): return {"ok":false,"code":"INVALID_IMAGE"}
	if not _dimensions_ok(image): return {"ok":false,"code":"IMAGE_DIMENSIONS"}
	return from_bytes(image.save_png_to_buffer(), "image/png")

static func from_bytes(bytes: PackedByteArray, mime: String) -> Dictionary:
	if bytes.size() > MAX_BYTES: return {"ok":false,"code":"IMAGE_TOO_LARGE"}
	if bytes.size() < 24: return {"ok":false,"code":"INVALID_IMAGE"}
	var image := Image.new()
	var error := ERR_INVALID_DATA
	match mime:
		"image/bmp":
			if bytes.size() < 26 or bytes.slice(0,2).get_string_from_ascii() != "BM": return {"ok":false,"code":"INVALID_IMAGE"}
			if image.load_bmp_from_buffer(bytes) != OK: return {"ok":false,"code":"INVALID_IMAGE"}
			return from_image(image)
		"image/png":
			if bytes.slice(0,8).hex_encode() != "89504e470d0a1a0a": return {"ok":false,"code":"INVALID_IMAGE"}
			var width := (int(bytes[16]) << 24) | (int(bytes[17]) << 16) | (int(bytes[18]) << 8) | int(bytes[19])
			var height := (int(bytes[20]) << 24) | (int(bytes[21]) << 16) | (int(bytes[22]) << 8) | int(bytes[23])
			if width < 1 or height < 1 or width > MAX_SIDE or height > MAX_SIDE or width * height > MAX_PIXELS: return {"ok":false,"code":"IMAGE_DIMENSIONS"}
			error = image.load_png_from_buffer(bytes)
		"image/jpeg":
			if bytes[0] != 255 or bytes[1] != 216: return {"ok":false,"code":"INVALID_IMAGE"}
			error = image.load_jpg_from_buffer(bytes)
		"image/webp":
			if bytes.slice(0,4).get_string_from_ascii() != "RIFF" or bytes.slice(8,12).get_string_from_ascii() != "WEBP": return {"ok":false,"code":"INVALID_IMAGE"}
			error = image.load_webp_from_buffer(bytes)
		_: return {"ok":false,"code":"IMAGE_FORMAT"}
	if error != OK or image.is_empty(): return {"ok":false,"code":"INVALID_IMAGE"}
	if not _dimensions_ok(image): return {"ok":false,"code":"IMAGE_DIMENSIONS"}
	return {"ok":true,"code":"OK","bytes":bytes,"mime":mime,"texture":ImageTexture.create_from_image(image)}

static func _dimensions_ok(image: Image) -> bool:
	return image.get_width() <= MAX_SIDE and image.get_height() <= MAX_SIDE and image.get_width() * image.get_height() <= MAX_PIXELS
