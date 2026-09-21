extends RefCounted
const MAX_BYTES := 6 * 1024 * 1024 - 4096
const MAX_SIDE := 8192
const MAX_PIXELS := 16000000

static func from_data_uri(uri: String) -> Dictionary:
	var expression := RegEx.new()
	expression.compile("^data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/]+={0,2})$")
	var matched := expression.search(uri)
	if matched == null:
		return {"ok":false,"code":"IMAGE_FORMAT"}
	var encoded := matched.get_string(2)
	var encoded_limit := int(ceil(float(MAX_BYTES) * 4.0 / 3.0))
	if encoded.length() > encoded_limit:
		return {"ok":false,"code":"IMAGE_TOO_LARGE"}
	if encoded.length() % 4 != 0:
		return {"ok":false,"code":"INVALID_IMAGE"}
	var bytes := Marshalls.base64_to_raw(encoded)
	if bytes.is_empty() or Marshalls.raw_to_base64(bytes) != encoded:
		return {"ok":false,"code":"INVALID_IMAGE"}
	return from_bytes(bytes, matched.get_string(1))

static func from_image(image: Image) -> Dictionary:
	if image == null or image.is_empty(): return {"ok":false,"code":"INVALID_IMAGE"}
	if not _dimensions_ok(image): return {"ok":false,"code":"IMAGE_DIMENSIONS"}
	return from_bytes(image.save_png_to_buffer(), "image/png")

static func from_bytes(bytes: PackedByteArray, mime: String) -> Dictionary:
	if bytes.size() > MAX_BYTES: return {"ok":false,"code":"IMAGE_TOO_LARGE"}
	if bytes.size() < 24: return {"ok":false,"code":"INVALID_IMAGE"}
	var header := header_dimensions(bytes, mime)
	if not header.ok:
		return {"ok":false,"code":header.code}
	if header.has("width") and (header.width < 1 or header.height < 1 or header.width > MAX_SIDE or header.height > MAX_SIDE or header.width * header.height > MAX_PIXELS):
		return {"ok":false,"code":"IMAGE_DIMENSIONS"}
	var image := Image.new()
	var error := ERR_INVALID_DATA
	match mime:
		"image/bmp":
			if bytes.size() < 26 or bytes.slice(0,2).get_string_from_ascii() != "BM": return {"ok":false,"code":"INVALID_IMAGE"}
			if image.load_bmp_from_buffer(bytes) != OK: return {"ok":false,"code":"INVALID_IMAGE"}
			return from_image(image)
		"image/png":
			if bytes.slice(0,8).hex_encode() != "89504e470d0a1a0a": return {"ok":false,"code":"INVALID_IMAGE"}
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

static func header_dimensions(bytes: PackedByteArray, mime: String) -> Dictionary:
	match mime:
		"image/png":
			if bytes.size() < 24 or bytes.slice(0,8).hex_encode() != "89504e470d0a1a0a": return {"ok":false,"code":"INVALID_IMAGE"}
			return {"ok":true,"code":"OK","width":_big_endian(bytes,16),"height":_big_endian(bytes,20)}
		"image/jpeg": return _jpeg_dimensions(bytes)
		"image/webp": return _webp_dimensions(bytes)
		"image/bmp":
			return {"ok":true,"code":"OK"} if bytes.size() >= 26 and bytes.slice(0,2).get_string_from_ascii() == "BM" else {"ok":false,"code":"INVALID_IMAGE"}
		_: return {"ok":false,"code":"IMAGE_FORMAT"}

static func _big_endian(bytes: PackedByteArray, index: int) -> int:
	return (int(bytes[index]) << 24) | (int(bytes[index + 1]) << 16) | (int(bytes[index + 2]) << 8) | int(bytes[index + 3])

static func _little_endian(bytes: PackedByteArray, index: int, count: int) -> int:
	var result := 0
	for offset in count:
		result |= int(bytes[index + offset]) << (offset * 8)
	return result

static func _jpeg_dimensions(bytes: PackedByteArray) -> Dictionary:
	if bytes.size() < 4 or bytes[0] != 0xff or bytes[1] != 0xd8: return {"ok":false,"code":"INVALID_IMAGE"}
	var index := 2
	while index + 3 < bytes.size():
		while index < bytes.size() and bytes[index] != 0xff: index += 1
		while index < bytes.size() and bytes[index] == 0xff: index += 1
		if index >= bytes.size(): break
		var marker: int = bytes[index]
		index += 1
		if marker in [0xd9, 0xda]: break
		if marker == 0x01 or marker in range(0xd0, 0xd8): continue
		if index + 1 >= bytes.size(): break
		var length := (int(bytes[index]) << 8) | int(bytes[index + 1])
		if length < 2 or index + length > bytes.size(): break
		if marker in [0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf] and length >= 7:
			return {"ok":true,"code":"OK","height":(int(bytes[index + 3]) << 8) | int(bytes[index + 4]),"width":(int(bytes[index + 5]) << 8) | int(bytes[index + 6])}
		index += length
	return {"ok":false,"code":"INVALID_IMAGE"}

static func _webp_dimensions(bytes: PackedByteArray) -> Dictionary:
	if bytes.size() < 16 or bytes.slice(0,4).get_string_from_ascii() != "RIFF" or bytes.slice(8,12).get_string_from_ascii() != "WEBP": return {"ok":false,"code":"INVALID_IMAGE"}
	var index := 12
	while index + 8 <= bytes.size():
		var kind := bytes.slice(index,index + 4).get_string_from_ascii()
		var length := _little_endian(bytes,index + 4,4)
		var data := index + 8
		if data + length > bytes.size(): break
		if kind == "VP8X" and length >= 10:
			return {"ok":true,"code":"OK","width":1 + _little_endian(bytes,data + 4,3),"height":1 + _little_endian(bytes,data + 7,3)}
		if kind == "VP8 " and length >= 10 and bytes[data + 3] == 0x9d and bytes[data + 4] == 0x01 and bytes[data + 5] == 0x2a:
			return {"ok":true,"code":"OK","width":_little_endian(bytes,data + 6,2) & 0x3fff,"height":_little_endian(bytes,data + 8,2) & 0x3fff}
		if kind == "VP8L" and length >= 5 and bytes[data] == 0x2f:
			var width := 1 + ((int(bytes[data + 1]) | (int(bytes[data + 2]) << 8)) & 0x3fff)
			var height := 1 + (((int(bytes[data + 2]) >> 6) | (int(bytes[data + 3]) << 2) | (int(bytes[data + 4]) << 10)) & 0x3fff)
			return {"ok":true,"code":"OK","width":width,"height":height}
		index = data + length + (length & 1)
	return {"ok":false,"code":"INVALID_IMAGE"}
