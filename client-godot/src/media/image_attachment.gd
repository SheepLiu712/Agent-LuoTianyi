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
	var detected_mime := detect_mime(bytes)
	if detected_mime.is_empty(): return {"ok":false,"code":"IMAGE_FORMAT"}
	if bytes.size() < 24: return {"ok":false,"code":"INVALID_IMAGE"}
	var header := header_dimensions(bytes, detected_mime)
	if not header.ok:
		return {"ok":false,"code":header.code}
	if not _header_dimensions_ok(header): return {"ok":false,"code":"IMAGE_DIMENSIONS"}
	var image := Image.new()
	var error := _decode_format(image, bytes, detected_mime)
	if error != OK or image.is_empty(): return {"ok":false,"code":"INVALID_IMAGE"}
	if detected_mime == "image/bmp": return from_image(image)
	if not _dimensions_ok(image): return {"ok":false,"code":"IMAGE_DIMENSIONS"}
	return {"ok":true,"code":"OK","bytes":bytes,"mime":detected_mime,"texture":ImageTexture.create_from_image(image)}

static func detect_mime(bytes: PackedByteArray) -> String:
	if _is_png(bytes): return "image/png"
	if _is_jpeg(bytes): return "image/jpeg"
	if _is_webp(bytes): return "image/webp"
	if bytes.size() >= 2 and bytes.slice(0,2).get_string_from_ascii() == "BM": return "image/bmp"
	return ""
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
	if bytes.size() < 4 or not _is_jpeg(bytes): return {"ok":false,"code":"INVALID_IMAGE"}
	var index := 2
	while index + 3 < bytes.size():
		index = _next_jpeg_marker(bytes, index)
		if index >= bytes.size(): break
		var marker: int = bytes[index]
		index += 1
		if marker in [0xd9, 0xda]: break
		if marker == 0x01 or marker in range(0xd0, 0xd8): continue
		var segment := _jpeg_segment(bytes, index, marker)
		if not segment.ok: break
		if segment.has("width"): return segment
		index = segment.next
	return {"ok":false,"code":"INVALID_IMAGE"}
static func _webp_dimensions(bytes: PackedByteArray) -> Dictionary:
	if bytes.size() < 16 or not _is_webp(bytes): return {"ok":false,"code":"INVALID_IMAGE"}
	var index := 12
	while index + 8 <= bytes.size():
		var kind := bytes.slice(index,index + 4).get_string_from_ascii()
		var length := _little_endian(bytes,index + 4,4)
		var data := index + 8
		if data + length > bytes.size(): break
		var dimensions := _webp_chunk_dimensions(bytes, data, length, kind)
		if not dimensions.is_empty(): return dimensions
		index = data + length + (length & 1)
	return {"ok":false,"code":"INVALID_IMAGE"}

static func _header_dimensions_ok(header: Dictionary) -> bool:
	if not header.has("width"): return true
	return header.width >= 1 and header.height >= 1 and header.width <= MAX_SIDE and header.height <= MAX_SIDE and header.width * header.height <= MAX_PIXELS

static func _is_png(bytes: PackedByteArray) -> bool:
	return bytes.size() >= 8 and bytes.slice(0,8).hex_encode() == "89504e470d0a1a0a"

static func _is_jpeg(bytes: PackedByteArray) -> bool:
	return bytes.size() >= 2 and bytes[0] == 0xff and bytes[1] == 0xd8

static func _is_webp(bytes: PackedByteArray) -> bool:
	return bytes.size() >= 12 and bytes.slice(0,4).get_string_from_ascii() == "RIFF" and bytes.slice(8,12).get_string_from_ascii() == "WEBP"

static func _decode_format(image: Image, bytes: PackedByteArray, mime: String) -> Error:
	match mime:
		"image/bmp": return _decode_bmp(image, bytes)
		"image/png": return image.load_png_from_buffer(bytes) if _is_png(bytes) else ERR_INVALID_DATA
		"image/jpeg": return image.load_jpg_from_buffer(bytes) if _is_jpeg(bytes) else ERR_INVALID_DATA
		"image/webp": return image.load_webp_from_buffer(bytes) if _is_webp(bytes) else ERR_INVALID_DATA
	return ERR_INVALID_DATA

static func _decode_bmp(image: Image, bytes: PackedByteArray) -> Error:
	if bytes.size() < 26 or bytes.slice(0,2).get_string_from_ascii() != "BM": return ERR_INVALID_DATA
	return image.load_bmp_from_buffer(bytes)

static func _next_jpeg_marker(bytes: PackedByteArray, index: int) -> int:
	while index < bytes.size() and bytes[index] != 0xff: index += 1
	while index < bytes.size() and bytes[index] == 0xff: index += 1
	return index

static func _jpeg_segment(bytes: PackedByteArray, index: int, marker: int) -> Dictionary:
	if index + 1 >= bytes.size(): return {"ok":false}
	var length := (int(bytes[index]) << 8) | int(bytes[index + 1])
	if length < 2 or index + length > bytes.size(): return {"ok":false}
	if marker in [0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf] and length >= 7:
		return {"ok":true,"code":"OK","height":(int(bytes[index + 3]) << 8) | int(bytes[index + 4]),"width":(int(bytes[index + 5]) << 8) | int(bytes[index + 6])}
	return {"ok":true,"next":index + length}

static func _webp_chunk_dimensions(bytes: PackedByteArray, data: int, length: int, kind: String) -> Dictionary:
	match kind:
		"VP8X":
			if length >= 10:
				return {"ok":true,"code":"OK","width":1 + _little_endian(bytes,data + 4,3),"height":1 + _little_endian(bytes,data + 7,3)}
		"VP8 ": return _vp8_dimensions(bytes, data, length)
		"VP8L": return _vp8l_dimensions(bytes, data, length)
	return {}

static func _vp8_dimensions(bytes: PackedByteArray, data: int, length: int) -> Dictionary:
	if length < 10 or bytes[data + 3] != 0x9d or bytes[data + 4] != 0x01 or bytes[data + 5] != 0x2a: return {}
	return {"ok":true,"code":"OK","width":_little_endian(bytes,data + 6,2) & 0x3fff,"height":_little_endian(bytes,data + 8,2) & 0x3fff}

static func _vp8l_dimensions(bytes: PackedByteArray, data: int, length: int) -> Dictionary:
	if length < 5 or bytes[data] != 0x2f: return {}
	var width := 1 + ((int(bytes[data + 1]) | (int(bytes[data + 2]) << 8)) & 0x3fff)
	var height := 1 + (((int(bytes[data + 2]) >> 6) | (int(bytes[data + 3]) << 2) | (int(bytes[data + 4]) << 10)) & 0x3fff)
	return {"ok":true,"code":"OK","width":width,"height":height}
