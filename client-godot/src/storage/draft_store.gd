extends RefCounted
## 按账号保存未发送的界面草稿；文字与图片分文件，写入走原子替换。

const AtomicFile = preload("res://src/storage/atomic_file.gd")
const LogEvents = preload("res://src/storage/log_events.gd")
const VERSION := 1

var _root := "user://drafts"
var _logger: RefCounted
var _documents: Dictionary = {}


func _init(root: String = "user://drafts", logger: RefCounted = null) -> void:
	_root = root
	_logger = logger


func read_text(scope: String, key: String) -> String:
	if scope.is_empty() or key.is_empty():
		return ""
	var texts: Dictionary = _load(scope).get("texts", {})
	var value: Variant = texts.get(key, "")
	return value if value is String else ""


func write_text(scope: String, key: String, text: String) -> Error:
	if scope.is_empty():
		return OK
	if key.is_empty():
		return ERR_INVALID_PARAMETER
	var document := _load(scope)
	var texts: Dictionary = document.get("texts", {})
	if text.strip_edges().is_empty():
		if not texts.has(key):
			return OK
		texts.erase(key)
	else:
		texts[key] = text
	document["texts"] = texts
	return _save(scope, document, "draft_save", key)


func clear_text(scope: String, key: String) -> Error:
	if scope.is_empty():
		return OK
	if key.is_empty():
		return ERR_INVALID_PARAMETER
	var document := _load(scope)
	var texts: Dictionary = document.get("texts", {})
	if not texts.has(key):
		return OK
	texts.erase(key)
	document["texts"] = texts
	return _save(scope, document, "draft_clear", key)


func read_attachment(scope: String, key: String) -> Dictionary:
	if scope.is_empty() or key.is_empty():
		return {}
	var document := _load(scope)
	var attachments: Dictionary = document.get("attachments", {})
	var meta: Variant = attachments.get(key)
	if not meta is Dictionary:
		return {}
	var path := _attachment_path(scope, key)
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		_remove_attachment(scope, document, key, false)
		_save(scope, document, "draft_image_clear", key)
		return {"ok": false, "code": "IMAGE_MISSING"}
	var bytes := file.get_buffer(file.get_length())
	file.close()
	if bytes.is_empty():
		_remove_attachment(scope, document, key, false)
		_save(scope, document, "draft_image_clear", key)
		return {"ok": false, "code": "IMAGE_MISSING"}
	return {"ok": true, "bytes": bytes, "mime": str(meta.get("mime", ""))}


func write_attachment(scope: String, key: String, bytes: PackedByteArray, mime: String) -> Error:
	if scope.is_empty():
		return OK
	if key.is_empty() or bytes.is_empty() or mime.is_empty():
		return ERR_INVALID_PARAMETER
	var error := AtomicFile.write_bytes(_attachment_path(scope, key), bytes)
	if error != OK:
		_log_failure("draft_image_save", "CACHE_WRITE_FAILED", "待发送图片写入失败")
		return error
	var document := _load(scope)
	var attachments: Dictionary = document.get("attachments", {})
	attachments[key] = {"mime": mime}
	document["attachments"] = attachments
	return _save(scope, document, "draft_image_save", key)


func clear_attachment(scope: String, key: String) -> Error:
	if scope.is_empty():
		return OK
	if key.is_empty():
		return ERR_INVALID_PARAMETER
	var document := _load(scope)
	var removed := _remove_attachment(scope, document, key, true)
	var save_error := OK
	if removed:
		save_error = _save(scope, document, "draft_image_clear", key)
	return save_error


func _load(scope: String) -> Dictionary:
	var id := _scope_id(scope)
	if _documents.has(id):
		return _documents[id]
	var document := {"version": VERSION, "texts": {}, "attachments": {}}
	var path := _document_path(scope)
	if FileAccess.file_exists(path):
		var parser := JSON.new()
		var parsed := parser.parse(FileAccess.get_file_as_string(path)) == OK
		if parsed and parser.data is Dictionary and int(parser.data.get("version", 0)) == VERSION:
			var texts: Variant = parser.data.get("texts", {})
			var attachments: Variant = parser.data.get("attachments", {})
			if texts is Dictionary:
				document["texts"] = texts
			if attachments is Dictionary:
				document["attachments"] = attachments
		else:
			_log_failure("draft_load", "INVALID_JSON", "草稿文件损坏，已忽略")
	_documents[id] = document
	return document


func _save(scope: String, document: Dictionary, operation: String, key: String) -> Error:
	var texts: Dictionary = document.get("texts", {})
	var attachments: Dictionary = document.get("attachments", {})
	if texts.is_empty() and attachments.is_empty():
		_documents.erase(_scope_id(scope))
		var path := _document_path(scope)
		if not FileAccess.file_exists(path):
			return OK
		var remove_error := DirAccess.remove_absolute(path)
		if remove_error != OK:
			_log_failure(operation, "CACHE_WRITE_FAILED", "空草稿文件清理失败")
		return remove_error
	document["version"] = VERSION
	var error := AtomicFile.write_text(_document_path(scope), JSON.stringify(document))
	if error != OK:
		_log_failure(operation, "CACHE_WRITE_FAILED", "草稿写入失败")
	return error


func _remove_attachment(scope: String, document: Dictionary, key: String, delete_file: bool) -> bool:
	var attachments: Dictionary = document.get("attachments", {})
	var removed := attachments.has(key)
	if removed:
		attachments.erase(key)
		document["attachments"] = attachments
	if delete_file:
		var path := _attachment_path(scope, key)
		if FileAccess.file_exists(path):
			DirAccess.remove_absolute(path)
	return removed


func _scope_id(scope: String) -> String:
	return scope.sha256_text()


func _document_path(scope: String) -> String:
	return _root.path_join(_scope_id(scope) + ".json")


func _attachment_path(scope: String, key: String) -> String:
	return _root.path_join(_scope_id(scope)).path_join(key.sha256_text() + ".image")


func _log_failure(operation: String, code: String, detail: String) -> void:
	if _logger == null:
		return
	var started := Time.get_ticks_usec()
	LogEvents.file_transaction(_logger, "app", operation, "draft-" + str(started), false, started, code, {"detail": detail})
