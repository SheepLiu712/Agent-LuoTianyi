extends SceneTree
const Files = preload("res://src/storage/image_file_reader.gd")
const Attachment = preload("res://src/media/image_attachment.gd")
var failures: Array[String] = []
func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ",label)
func _initialize() -> void:
	var image := Image.create(32,24,false,Image.FORMAT_RGB8)
	image.fill(Color("66ccff"))
	for pair in [[image.save_png_to_buffer(),"image/png"],[image.save_jpg_to_buffer(),"image/jpeg"],[image.save_webp_to_buffer(),"image/webp"]]:
		var result := Attachment.from_bytes(pair[0],pair[1])
		check(result.ok and result.texture.get_size() == Vector2(32,24), "supported format previews: " + pair[1])
	var file_path := "user://image-input-test.png"
	image.save_png(file_path)
	var read_result := Files.read(file_path)
	check(read_result.ok and read_result.mime == "image/png", "file picker identifies PNG from content")
	DirAccess.remove_absolute(file_path)
	check(Files.read(file_path).code == "IMAGE_READ_FAILED", "missing file gives explicit failure")
	var mismatched_png := "user://image-input-test.jpg"
	image.save_png(mismatched_png)
	read_result = Files.read(mismatched_png)
	check(read_result.ok and read_result.mime == "image/png", "JPG extension does not override PNG header")
	DirAccess.remove_absolute(mismatched_png)
	var unknown_extension := "user://image-input-test.data"
	image.save_png(unknown_extension)
	read_result = Files.read(unknown_extension)
	check(read_result.ok and read_result.mime == "image/png", "supported content works with unknown extension")
	DirAccess.remove_absolute(unknown_extension)
	check(Attachment.from_image(image).mime == "image/png", "clipboard uses PNG wire data")
	var data_uri := "data:image/png;base64," + Marshalls.raw_to_base64(image.save_png_to_buffer())
	check(Attachment.from_data_uri(data_uri).ok, "strict image data URI accepted")
	check(Attachment.from_data_uri("https://example.invalid/image.png").code == "IMAGE_FORMAT", "external image URL rejected")
	check(Attachment.from_data_uri("data:image/png;base64,not-base64!").code == "IMAGE_FORMAT", "malformed image data URI rejected")
	var big := PackedByteArray()
	big.resize(6 * 1024 * 1024)
	check(Attachment.from_bytes(big,"image/png").code == "IMAGE_TOO_LARGE", "oversized packet is rejected before decoding")
	var invalid := image.save_png_to_buffer()
	invalid[16] = 127
	check(Attachment.from_bytes(invalid,"image/png").code == "IMAGE_DIMENSIONS", "oversized PNG dimensions are rejected before decoding")
	var corrected := Attachment.from_bytes(image.save_png_to_buffer(),"image/jpeg")
	check(corrected.ok and corrected.mime == "image/png", "declared MIME is corrected from the file header")
	check(Attachment.from_bytes("not an image".to_utf8_buffer(),"image/png").code == "IMAGE_FORMAT", "unknown image content is rejected")
	var jpeg := image.save_jpg_to_buffer()
	check(Attachment.from_bytes(jpeg,"image/png").ok and Attachment.from_bytes(jpeg,"image/png").mime == "image/jpeg", "JPEG header corrects PNG declaration")
	var bmp := Marshalls.base64_to_raw("Qk1GAAAAAAAAADYAAAAoAAAAAgAAAAIAAAABABgAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAA/8xmAAD/AAD///8AAAAAAA==")
	var normalized_bmp := Attachment.from_bytes(bmp,"image/png")
	_check_bmp_is_normalized_to_png_before_sending(normalized_bmp)
	print("Image attachment validation: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func _check_bmp_is_normalized_to_png_before_sending(normalized_bmp: Variant) -> void:
	check(normalized_bmp.ok and normalized_bmp.mime == "image/png" and normalized_bmp.bytes.slice(0,8).hex_encode() == "89504e470d0a1a0a", "BMP is normalized to PNG before sending")
	if not normalized_bmp.ok: return
	var decoded := Image.new()
	check(decoded.load_png_from_buffer(normalized_bmp.bytes) == OK, "normalized BMP is decodable PNG")
	check(decoded.get_size() == Vector2i(2,2), "BMP dimensions survive normalization")
	check(decoded.get_pixel(0,0).is_equal_approx(Color.WHITE), "BMP top row survives normalization")
	check(decoded.get_pixel(1,0).is_equal_approx(Color.BLACK), "BMP pixel padding is decoded correctly")
	check(decoded.get_pixel(0,1).is_equal_approx(Color(102.0/255.0,204.0/255.0,1.0)), "BMP BGR color survives normalization")
