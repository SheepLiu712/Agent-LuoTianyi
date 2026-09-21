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
	check(Files.read(file_path).ok, "file picker path decodes the actual image")
	DirAccess.remove_absolute(file_path)
	check(Files.read(file_path).code == "IMAGE_READ_FAILED", "missing file gives explicit failure")
	check(Attachment.from_image(image).mime == "image/png", "clipboard uses PNG wire data")
	var big := PackedByteArray()
	big.resize(6 * 1024 * 1024)
	check(Attachment.from_bytes(big,"image/png").code == "IMAGE_TOO_LARGE", "oversized packet is rejected before decoding")
	var invalid := image.save_png_to_buffer()
	invalid[16] = 127
	check(Attachment.from_bytes(invalid,"image/png").code == "IMAGE_DIMENSIONS", "oversized PNG dimensions are rejected before decoding")
	check(not Attachment.from_bytes(image.save_png_to_buffer(),"image/jpeg").ok, "MIME must match image bytes")
	print("Image attachment validation: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
