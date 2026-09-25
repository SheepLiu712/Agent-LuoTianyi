extends RefCounted
const Attachment = preload("res://src/media/image_attachment.gd")
static func read(path: String) -> Dictionary:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null: return {"ok":false,"code":"IMAGE_READ_FAILED"}
	if file.get_length() > Attachment.MAX_BYTES:
		file.close()
		return {"ok":false,"code":"IMAGE_TOO_LARGE"}
	var bytes := file.get_buffer(file.get_length())
	file.close()
	var mime: String = {"png":"image/png","jpg":"image/jpeg","jpeg":"image/jpeg","webp":"image/webp","bmp":"image/bmp"}.get(path.get_extension().to_lower(), "")
	return {"ok":true,"code":"OK","bytes":bytes,"mime":mime}
