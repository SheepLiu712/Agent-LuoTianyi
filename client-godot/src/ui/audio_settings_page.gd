extends MarginContainer

const StorageService = preload("res://src/storage/storage_service.gd")
const MigrationPort = preload("res://src/storage/python_media_migration_port.gd")
const USAGE_REFRESH_MS := 2000
const STATUS_INFO := Color(0.117647, 0.407843, 0.6, 1)
const STATUS_SUCCESS := Color(0.117647, 0.431373, 0.286275, 1)
const STATUS_WARNING := Color(0.611765, 0.341176, 0, 1)
const STATUS_ERROR := Color(0.717647, 0.164706, 0.164706, 1)
const STATUS_MUTED := Color(0.42, 0.5, 0.56, 1)

var _clear_cache: Callable
var _clearing := false
var _storage: StorageService
var _directory := ""
var _app_directory := ""
var _scan_generation := 0
var _pending_days := 0
var _migration: MigrationPort
var _last_imported := 0
var _usage_refreshed_ms := 0
var _usage_loaded := false
var _scan_ok := false
var _importable := false


func setup(
	clear_cache: Callable,
	storage_service: StorageService = null,
	cache_directory: String = "",
	migration: MigrationPort = null,
	app_data_directory: String = ""
) -> void:
	_clear_cache = clear_cache
	_storage = storage_service
	_directory = cache_directory
	_app_directory = app_data_directory if not app_data_directory.is_empty() else cache_directory
	_migration = migration
	_usage_loaded = false
	_scan_generation += 1
	if is_node_ready():
		%ClearCache.disabled = not _clear_cache.is_valid()
		_apply_migration()
		# 设置窗预暖时父 Window 仍隐藏；子控件自身 visible 仍为 true，不能据此触发磁盘扫描。
		if is_visible_in_tree():
			_refresh_scan()
			_refresh_usage()


## 设置窗可能在页面就绪后才拿到导入服务，所以允许二次注入。
func set_media_migration(migration: MigrationPort) -> void:
	_migration = migration
	if is_node_ready():
		_apply_migration()
		if is_visible_in_tree():
			_refresh_scan()


## 兼容旧调用名：该页面现在同时管理语音与图片。
func set_audio_migration(migration: MigrationPort) -> void:
	set_media_migration(migration)


func _ready() -> void:
	%ClearCache.disabled = not _clear_cache.is_valid()
	%ClearCache.pressed.connect(_request_clear)
	%MigrateMedia.pressed.connect(_request_migrate)
	%BrowsePython.pressed.connect(_request_pick)
	%PythonPicker.file_selected.connect(_on_python_selected)
	%PythonPicker.canceled.connect(func(): %PythonPicker.hide())
	%ClearDialog.confirmed.connect(_clear)
	%MigrationDialog.confirmed.connect(_migrate)
	%RefreshUsage.pressed.connect(_refresh_usage)
	visibility_changed.connect(func():
		if is_visible_in_tree():
			_refresh_scan()
			_refresh_usage_if_needed())
	_apply_migration()
	if is_visible_in_tree():
		_refresh_scan()
		_refresh_usage_if_needed()


## 未接线时导入按钮保持禁用：没有服务就不能让用户以为已经点过了。
func _apply_migration() -> void:
	%MigrateMedia.disabled = _migration == null
	%BrowsePython.disabled = _migration == null
	if _migration == null:
		%PythonPath.text = ""
		%PythonPath.tooltip_text = ""
		_set_migration_status("导入暂不可用。", "muted")
		return
	if not _migration.progress.is_connected(_on_migration_progress):
		_migration.progress.connect(_on_migration_progress)
	_on_migration_progress(_migration.get_state())


## 打开页面才重新校验：启动不阻塞、不弹窗；路径失效时引导重选。
func _refresh_scan() -> void:
	if _migration == null:
		_set_migration_status("导入暂不可用。", "muted")
		return
	var result := _migration.scan()
	_show_target()
	_apply_scan(result)


func _show_target() -> void:
	var path := _migration.get_target_path() if _migration != null else ""
	%PythonPath.text = path
	%PythonPath.tooltip_text = path


func _apply_scan(result: Dictionary) -> void:
	_scan_ok = bool(result.get("ok", false))
	var audio := int(result.get("audio_count", 0))
	var images := int(result.get("image_count", 0))
	_importable = _scan_ok and audio + images > 0
	_update_import_button(false)
	if not _scan_ok:
		var code := str(result.get("code", "TARGET_MISSING"))
		_set_migration_status(_scan_failure(code), "warning" if code == "TARGET_MISSING" else "error")
		return
	var mismatch := _migration != null and bool(_migration.get_state().get("mismatch", false))
	var kind := "warning" if mismatch or not _importable else "success"
	_set_migration_status(_scan_summary(result, audio, images), kind)


func _scan_summary(result: Dictionary, audio: int, images: int) -> String:
	var text := "没有可导入的媒体。" if audio + images == 0 else "可导入：语音 %d 条，图片 %d 张。" % [audio, images]
	var unmatched := int(result.get("unmatched_count", 0))
	if unmatched > 0:
		text += " 另有 %d 张图片无法匹配，将跳过。" % unmatched
	var missing: Array[String] = []
	if not bool(result.get("has_audio", false)):
		missing.append("语音")
	if not bool(result.get("has_images", false)):
		missing.append("图片")
	if not missing.is_empty():
		text += " 缺少%s目录。" % "、".join(missing)
	if _migration != null and bool(_migration.get_state().get("mismatch", false)):
		text += " 客户端账号与当前登录不同，导入前会确认。"
	return text


func _scan_failure(code: String) -> String:
	match code:
		"TARGET_INVALID":
			return "不是可识别的客户端程序，请重新选择。"
		"TARGET_MISSING":
			return "目标目录不存在，请重新选择程序。" if not %PythonPath.text.is_empty() else "尚未选择客户端程序。"
		_:
			return "导入暂不可用，请重新选择程序。"


func _update_import_button(busy: bool) -> void:
	%MigrateMedia.disabled = _migration == null or busy or not _importable
	%BrowsePython.disabled = _migration == null or busy
	%ClearCache.disabled = busy or not _clear_cache.is_valid()


func _request_pick() -> void:
	if _migration == null:
		return
	%PythonPicker.popup_centered_ratio(0.7)


func _on_python_selected(path: String) -> void:
	if _migration == null:
		return
	var result := _migration.set_target(path)
	_show_target()
	_apply_scan(result)


func _request_clear() -> void:
	var days: float = %OlderThanDays.value
	if not is_finite(days) or days < 0 or days > 1000000000000:
		_set_cache_status("请输入有效的非负整数天数。", "error")
		return
	if _migration != null and _migration.is_busy():
		_set_cache_status("正在导入媒体，请等导入完成后再清理。", "warning")
		return
	_pending_days = int(days)
	%ClearDialog.dialog_text = ("清理当前服务器、本账号的全部语音缓存？" if _pending_days == 0 else "清理当前服务器、本账号 %s 天之前保存的语音缓存？" % _pending_days) + "\n聊天文字与历史图片保留；已清理语音无法重放。本地重放将停止，在线声音继续。"
	%ClearDialog.popup_centered()


func _clear() -> void:
	if _clearing or not _clear_cache.is_valid():
		return
	_clearing = true
	%ClearCache.disabled = true
	%OlderThanDays.editable = false
	_set_cache_status("正在清理…", "info")
	await get_tree().process_frame
	var result: Error = _clear_cache.call(_pending_days)
	_clearing = false
	%ClearCache.disabled = false
	%OlderThanDays.editable = true
	if result == OK:
		_set_cache_status(
			"已清理本账号全部语音缓存。" if _pending_days == 0 else "已清理本账号 %s 天之前的语音缓存。" % _pending_days,
			"success"
		)
	else:
		_set_cache_status("部分语音文件被占用，关闭后重试。", "error")
	_refresh_usage()


func _request_migrate() -> void:
	if _migration == null or _migration.is_busy():
		return
	if not _scan_ok:
		_refresh_scan()
		return
	%MigrationDialog.dialog_text = _confirmation()
	%MigrationDialog.popup_centered()


func _confirmation() -> String:
	var text := "把 Python 客户端保存的语音与历史图片复制到当前账号？\n\n只新增、不覆盖：已有缓存保持不变，源文件保留。"
	var state := _migration.get_state()
	if bool(state.get("mismatch", false)):
		var scan: Dictionary = state.get("scan", {})
		var account: Variant = scan.get("account", {})
		text = "%s\n\n注意：Python 客户端记录的是 %s @ %s，与当前登录不同；媒体仍会写入当前账号。" % [
			text, str(account.get("username", "未知账号")), str(account.get("server_url", "未知服务器")),
		]
	return text


func _migrate() -> void:
	if _migration == null:
		return
	_set_migration_status("正在导入 Python 客户端媒体…", "info")
	_update_import_button(true)
	_migration.request_import()


## 进度由端口推来：批量显示双进度，结束后给出可核对的计数。
func _on_migration_progress(state: Dictionary) -> void:
	if _migration == null:
		return
	var busy := bool(state.get("busy", false))
	var mode := str(state.get("mode", "idle"))
	var imported := int(state.get("imported", 0))
	_update_import_button(busy)
	if busy:
		_set_migration_status("正在导入 %d / %d（语音 %d / %d，图片 %d / %d）…" % [
			int(state.get("done", 0)), int(state.get("total", 0)),
			int(state.get("audio_done", 0)), int(state.get("audio_total", 0)),
			int(state.get("image_done", 0)), int(state.get("image_total", 0)),
		], "info")
	elif mode == "done":
		_set_migration_status(_summary(state), "warning" if _migration_failure(state) else "success")
	elif mode == "unavailable":
		_set_migration_status(_unavailable(str(state.get("code", ""))), "error")
	elif mode == "incremental" and imported > 0:
		_set_migration_status("已按需导入 %d 条语音。" % imported, "success")
	if imported != _last_imported:
		_last_imported = imported
		if is_visible_in_tree():
			_refresh_usage_throttled()
		else:
			_usage_loaded = false


func _unavailable(code: String) -> String:
	if code in ["TARGET_MISSING", "TARGET_INVALID", "SOURCE_NOT_FOUND"]:
		return _scan_failure(code)
	if code == "STORAGE_UNAVAILABLE":
		return "缓存目录不可用，请先登录后再导入。"
	return "导入暂不可用，请重新选择 Python 客户端程序。"


func _migration_failure(state: Dictionary) -> bool:
	return str(state.get("code", "")) in ["TARGET_MISSING", "TARGET_INVALID", "SOURCE_NOT_FOUND", "STORAGE_UNAVAILABLE", "PARTIAL"]


func _summary(state: Dictionary) -> String:
	match str(state.get("code", "")):
		"SOURCE_EMPTY":
			return "选中的客户端里没有可导入的媒体文件。"
		"TARGET_MISSING", "TARGET_INVALID", "SOURCE_NOT_FOUND":
			return _scan_failure(str(state.get("code", "")))
		"STORAGE_UNAVAILABLE":
			return "缓存目录不可用，请先登录后再导入。"
		_:
			var text := "已处理 %d 条（语音 %d、图片 %d）：导入 %d 条，跳过 %d 条，失败 %d 条。" % [
				int(state.get("done", 0)), int(state.get("audio_total", 0)),
				int(state.get("image_total", 0)), int(state.get("imported", 0)),
				int(state.get("skipped", 0)), int(state.get("failed", 0)),
			]
			if int(state.get("failed", 0)) > 0:
				text = "部分文件未导入，已成功的内容会保留；未成功的条目会在翻看历史时自动重试。"
			return text


func _refresh_usage_if_needed() -> void:
	if not _usage_loaded:
		_refresh_usage()


func _refresh_usage_throttled() -> void:
	if not visible:
		return
	var now := Time.get_ticks_msec()
	if now - _usage_refreshed_ms < USAGE_REFRESH_MS:
		return
	_usage_refreshed_ms = now
	_refresh_usage()


func _refresh_usage() -> void:
	_scan_generation += 1
	var generation := _scan_generation
	%UsageRing.set_unavailable()
	%UsagePercent.text = "--%"
	%UsageState.text = "容量数据扫描中"
	%StorageTotal.text = "整盘 --"
	%AccountNote.text = "其中本账号语音缓存：--"
	_set_usage_legend("--", "--", "--", "--", "--", "--")
	%RefreshUsage.disabled = true
	await get_tree().process_frame
	var root_directory := _app_directory if not _app_directory.is_empty() else _directory
	var root_data := _query_directory(root_directory)
	var cache_data := root_data if _directory == root_directory else _query_directory(_directory)
	if generation != _scan_generation:
		return
	var client: int = root_data.get("directory_bytes", -1)
	var total: int = root_data.get("total_bytes", -1)
	var free: int = root_data.get("free_bytes", -1)
	var account: int = cache_data.get("directory_bytes", -1)
	var known := client >= 0 and total > 0 and free >= 0 and free <= total
	var client_used := 0
	if known:
		client_used = mini(client, total - free)
		%UsageRing.set_usage(client, total, free)
		var segments: Array = %UsageRing.get_segments()
		var other_used := _segment_bytes(segments, "other")
		var free_used := _segment_bytes(segments, "free")
		%UsagePercent.text = _format_share(client_used, total)
		%UsageState.text = "客户端占磁盘"
		%StorageTotal.text = "整盘 %s" % _format_bytes(total)
		_set_usage_legend(
			_format_bytes(client_used), _format_share(client_used, total),
			_format_bytes(other_used), _format_share(other_used, total),
			_format_bytes(free_used), _format_share(free_used, total)
		)
		%AccountNote.text = "其中本账号语音缓存：%s" % (_format_bytes(account) if account >= 0 else "暂不可用")
	else:
		%UsageRing.set_unavailable()
		%UsagePercent.text = "--%"
		%UsageState.text = "容量数据暂不可用"
		%StorageTotal.text = "整盘 --"
		_set_usage_legend("--", "--", "--", "--", "--", "--")
		%AccountNote.text = "其中本账号语音缓存：%s" % (_format_bytes(account) if account >= 0 else "暂不可用")
	_usage_loaded = true
	%RefreshUsage.disabled = false


func _query_directory(path: String) -> Dictionary:
	if _storage == null or path.is_empty():
		return {"directory_bytes":-1, "total_bytes":-1, "free_bytes":-1}
	return _storage.query_directory(path)


func _segment_bytes(segments: Array, kind: String) -> int:
	for segment in segments:
		if str(segment.get("kind", "")) == kind:
			return int(segment.get("bytes", 0))
	return 0


func _set_usage_legend(
	client_value: String,
	client_percent: String,
	other_value: String,
	other_percent: String,
	free_value: String,
	free_percent: String
) -> void:
	%ClientValue.text = client_value
	%ClientPercent.text = client_percent
	%OtherValue.text = other_value
	%OtherPercent.text = other_percent
	%FreeValue.text = free_value
	%FreePercent.text = free_percent


func _set_migration_status(text: String, kind: String) -> void:
	%MigrationStatus.text = text
	%MigrationStatus.add_theme_color_override("font_color", _status_color(kind))


func _set_cache_status(text: String, kind: String) -> void:
	%CacheStatus.visible = not text.is_empty()
	%CacheStatus.text = text
	%CacheStatus.add_theme_color_override("font_color", _status_color(kind))


func _status_color(kind: String) -> Color:
	match kind:
		"success":
			return STATUS_SUCCESS
		"warning":
			return STATUS_WARNING
		"error":
			return STATUS_ERROR
		"info":
			return STATUS_INFO
		_:
			return STATUS_MUTED


func _format_share(bytes: int, total: int) -> String:
	if bytes <= 0 or total <= 0:
		return "0%"
	var percent := 100.0 * float(bytes) / float(total)
	if percent < 0.01:
		return "<0.01%"
	return "%.2f%%" % percent


func _format_bytes(bytes: int) -> String:
	if bytes < 0:
		return "无法读取"
	if bytes < 1024:
		return "%s bytes" % bytes
	var amount := float(bytes)
	for unit in ["KiB", "MiB", "GiB", "TiB", "PiB"]:
		amount /= 1024.0
		if amount < 1024.0:
			return "%.2f %s" % [amount, unit]
	return "%s bytes" % bytes
