extends RefCounted
## Python 桌面客户端定位器：只读目录指纹与媒体索引，不写磁盘、不解密凭据。
## 目录判据不依赖 exe 文件名，允许用户重命名程序或选择旧版本目录。

const CONFIG_RELATIVE := "config/config.json"
const ACCOUNT_RELATIVE := "temp/user.json"
const AUDIO_RELATIVE := "temp/tts_output"
const IMAGES_RELATIVE := "temp/images"
const IMAGE_EXTENSIONS := ["png", "jpg", "jpeg", "webp"]
const UNSUPPORTED_IMAGE_EXTENSIONS := ["gif", "bmp"]
const UUID_PATTERN := "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
const CONFIG_LIMIT := 512 * 1024
const ACCOUNT_LIMIT := 64 * 1024

static var _uuid: RegEx


static func is_uuid(value: String) -> bool:
	if _uuid == null:
		_uuid = RegEx.create_from_string(UUID_PATTERN)
	return _uuid.search(value) != null


## 接受 exe 路径或客户端目录；返回规范化后的数据根。
static func normalize_root(path: String) -> String:
	var value := path.strip_edges().replace("\\", "/").trim_suffix("/")
	if value.is_empty():
		return ""
	if DirAccess.dir_exists_absolute(value):
		return value.simplify_path()
	return value.get_base_dir().simplify_path()


static func inspect(path: String) -> Dictionary:
	var root := normalize_root(path)
	if root.is_empty() or not DirAccess.dir_exists_absolute(root):
		return _result(false, "TARGET_MISSING", {"root":root})
	var fingerprint := _fingerprint(root)
	if not fingerprint.ok:
		return _result(false, str(fingerprint.code), {"root":root})
	var audio_dir := root.path_join(AUDIO_RELATIVE)
	var images_dir := root.path_join(IMAGES_RELATIVE)
	var audio := audio_index(audio_dir)
	var image_data := _scan_images(images_dir)
	return {
		"ok":true, "code":"OK", "root":root,
		"audio_dir":audio_dir, "images_dir":images_dir,
		"has_audio":DirAccess.dir_exists_absolute(audio_dir),
		"has_images":DirAccess.dir_exists_absolute(images_dir),
		"audio_count":audio.size(), "image_count":image_data.index.size(),
		"unmatched_count":int(image_data.unmatched),
		"account":resolve_account(root),
	}


## 目录里所有「文件名就是 UUID」的 wav：id → 绝对路径。
static func audio_index(directory: String) -> Dictionary:
	var entries := {}
	if not DirAccess.dir_exists_absolute(directory):
		return entries
	for name in DirAccess.get_files_at(directory):
		if not name.to_lower().ends_with(".wav"):
			continue
		var id := name.get_basename()
		if is_uuid(id):
			entries[id.to_lower()] = directory.path_join(name)
	return entries


## 只收能按消息 UUID 对齐、且 Godot 可解码的历史图片。
static func image_index(directory: String) -> Dictionary:
	return _scan_images(directory).index


static func find_audio(directory: String, id: String) -> String:
	if not is_uuid(id):
		return ""
	for candidate in [id, id.to_lower()]:
		var path := directory.path_join(candidate + ".wav")
		if FileAccess.file_exists(path):
			return path
	return ""


static func find_image(directory: String, id: String) -> String:
	if not is_uuid(id):
		return ""
	for candidate in [id, id.to_lower()]:
		for extension in IMAGE_EXTENSIONS:
			for suffix in [extension, extension.to_upper()]:
				var path := directory.path_join(candidate + "." + suffix)
				if FileAccess.file_exists(path):
					return path
	return ""


## 只读账号字段：不回传 token，也不触碰 DPAPI 密文。
static func resolve_account(root: String) -> Dictionary:
	var data := _read_json(root.path_join(ACCOUNT_RELATIVE), ACCOUNT_LIMIT)
	var username := ""
	if data.get("username") is String:
		username = str(data.username).strip_edges()
	var server := ""
	if data.get("server_url") is String:
		server = str(data.server_url).strip_edges()
	if server.is_empty():
		server = _configured_base_url(root)
	return {
		"username":username,
		"server_url":_expand_env(server),
		"available":not username.is_empty() or not server.is_empty(),
	}


static func _scan_images(directory: String) -> Dictionary:
	var index := {}
	var unmatched := 0
	if not DirAccess.dir_exists_absolute(directory):
		return {"index":index, "unmatched":unmatched}
	for name in DirAccess.get_files_at(directory):
		var extension := name.get_extension().to_lower()
		if extension in UNSUPPORTED_IMAGE_EXTENSIONS:
			unmatched += 1
			continue
		if not extension in IMAGE_EXTENSIONS:
			continue
		var id := name.get_basename()
		if is_uuid(id):
			index[id.to_lower()] = directory.path_join(name)
		else:
			unmatched += 1
	return {"index":index, "unmatched":unmatched}


static func _fingerprint(root: String) -> Dictionary:
	if _config_matches(root):
		return {"ok":true, "code":"OK"}
	var account := _read_json(root.path_join(ACCOUNT_RELATIVE), ACCOUNT_LIMIT)
	if _looks_like_account(account) and DirAccess.dir_exists_absolute(root.path_join("temp")):
		return {"ok":true, "code":"OK"}
	return {"ok":false, "code":"TARGET_INVALID"}


static func _config_matches(root: String) -> bool:
	var config := _read_json(root.path_join(CONFIG_RELATIVE), CONFIG_LIMIT)
	var live2d: Variant = config.get("live2d")
	if not live2d is Dictionary:
		return false
	var model: Variant = live2d.get("model")
	if not model is Dictionary:
		return false
	var model_path := str(model.get("model_path", "")).strip_edges()
	return not model_path.is_empty() and FileAccess.file_exists(root.path_join(model_path))


static func _looks_like_account(data: Dictionary) -> bool:
	for key in ["username", "auto_login", "token_dpapi", "token", "server_url"]:
		if data.has(key):
			return true
	return false


static func _configured_base_url(root: String) -> String:
	var config := _read_json(root.path_join(CONFIG_RELATIVE), CONFIG_LIMIT)
	var section := "debug_config" if bool(config.get("is_debug", false)) else "release_config"
	var entry: Variant = config.get(section)
	return str(entry.get("base_url", "")) if entry is Dictionary else ""


## 与 Python 端一致：只有整串以 $ 开头才替换环境变量。
static func _expand_env(value: String) -> String:
	if not value.begins_with("$"):
		return value
	var name := value.substr(1)
	if name.begins_with("{") and name.ends_with("}"):
		name = name.substr(1, name.length() - 2)
	var resolved := OS.get_environment(name)
	return resolved if not resolved.is_empty() else value


static func _read_json(path: String, limit: int) -> Dictionary:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null or file.get_length() <= 0 or file.get_length() > limit:
		if file != null:
			file.close()
		return {}
	var text := file.get_as_text()
	file.close()
	var parsed: Variant = JSON.parse_string(text)
	return parsed if parsed is Dictionary else {}


static func _result(ok: bool, code: String, extra: Dictionary) -> Dictionary:
	var result := {"ok":ok, "code":code}
	result.merge(extra, true)
	return result
