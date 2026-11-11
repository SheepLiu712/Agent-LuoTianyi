extends MarginContainer
const StorageService = preload("res://src/storage/storage_service.gd")
const MigrationPort = preload("res://src/storage/python_media_migration_port.gd")
const ErrorDialog = preload("res://src/ui/error_dialog.gd")
const USAGE_REFRESH_MS := 2000

var _clear_cache: Callable
var _clearing := false
var _storage: StorageService
var _directory := ""
var _scan_generation := 0
var _pending_days := 0
var _migration: MigrationPort
var _last_imported := 0
var _usage_refreshed_ms := 0
var _scan_ok := false
var _importable := false


func setup(clear_cache: Callable, storage_service: StorageService = null, cache_directory: String = "", migration: MigrationPort = null) -> void:
	_clear_cache = clear_cache
	_storage = storage_service
	_directory = cache_directory
	_migration = migration
	if is_node_ready():
		%ClearCache.disabled = not _clear_cache.is_valid()
		_apply_migration()
		if visible:
			_refresh_scan()
			_refresh_usage()


## 设置窗可能在页面就绪后才拿到导入服务，所以允许二次注入。
func set_media_migration(migration: MigrationPort) -> void:
	_migration = migration
	if is_node_ready():
		_apply_migration()
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
	%UsageRing.resized.connect(_position_marker)
	visibility_changed.connect(func():
		if visible:
			_refresh_scan()
			_refresh_usage())
	_apply_migration()
	_position_marker()
	if visible:
		_refresh_scan()
		_refresh_usage()


## 未接线时导入按钮保持禁用：没有服务就不能让用户以为已经点过了。
func _apply_migration() -> void:
	%MigrateMedia.disabled = _migration == null
	%BrowsePython.disabled = _migration == null
	if _migration == null:
		%MigrationStatus.text = ""
		%PythonPath.text = ""
		return
	if not _migration.progress.is_connected(_on_migration_progress):
		_migration.progress.connect(_on_migration_progress)
	_on_migration_progress(_migration.get_state())


## 打开页面才重新校验：启动不阻塞、不弹窗；路径失效时引导重选。
func _refresh_scan() -> void:
	if _migration == null:
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
	if _scan_ok:
		%MigrationStatus.text = _scan_summary(result, audio, images)
		return
	%MigrationStatus.text = ""
	ErrorDialog.present(self, _scan_failure(str(result.get("code", "TARGET_MISSING"))))


func _scan_summary(result: Dictionary, audio: int, images: int) -> String:
	var text := "已识别客户端：语音 %d 条，图片 %d 张。" % [audio, images]
	var unmatched := int(result.get("unmatched_count", 0))
	if unmatched > 0:
		text += "另有 %d 张图片无法按消息匹配或格式不支持，不会导入。" % unmatched
	var missing: Array[String] = []
	if not bool(result.get("has_audio", false)):
		missing.append("语音目录")
	if not bool(result.get("has_images", false)):
		missing.append("图片目录")
	if not missing.is_empty():
		text += " 缺少：%s。" % "、".join(missing)
	if audio + images == 0:
		text += " 没有可导入的媒体。"
	return text


func _scan_failure(code: String) -> String:
	match code:
		"TARGET_INVALID":
			return "不是可识别的客户端目录，请重新选择程序。"
		"TARGET_MISSING":
			return "目标目录不存在，请重新选择程序。" if not %PythonPath.text.is_empty() else "尚未选择 Python 客户端程序。"
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
	if _scan_ok and _migration.get_state().get("mismatch", false):
		%MigrationStatus.text += "\n注意：Python 客户端记录的账号/服务器与当前登录不同，导入前会再次确认。"


func _request_clear() -> void:
	var days: float = %OlderThanDays.value
	if not is_finite(days) or days < 0 or days > 1000000000000:
		%CacheStatus.text = ""
		ErrorDialog.present(self, "请输入有效的非负整数天数。")
		return
	if _migration != null and _migration.is_busy():
		%CacheStatus.text = "正在导入媒体，请等导入完成后再清理。"
		return
	_pending_days = int(days)
	%ClearDialog.dialog_text = ("清理当前服务器、本账号的全部语音缓存？" if _pending_days == 0 else "清理当前服务器、本账号 %s 天之前保存的语音缓存？" % _pending_days) + "\n聊天文字保留；已清理语音无法重放。本地重放将停止，在线声音继续。"
	%ClearDialog.popup_centered()


func _clear() -> void:
	if _clearing or not _clear_cache.is_valid(): return
	_clearing = true
	%ClearCache.disabled = true
	%OlderThanDays.editable = false
	%CacheStatus.text = "正在清理…"
	await get_tree().process_frame
	var result: Error = _clear_cache.call(_pending_days)
	_clearing = false
	%ClearCache.disabled = false
	%OlderThanDays.editable = true
	if result == OK:
		%CacheStatus.text = ("已清理本账号全部语音缓存。" if _pending_days == 0 else "已清理本账号 %s 天之前的语音缓存。" % _pending_days) + "聊天文字已保留。"
	else:
		%CacheStatus.text = ""
		ErrorDialog.present(self, "部分语音文件被占用，关闭后重试。")
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
	%MigrationStatus.text = "正在导入 Python 客户端媒体…"
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
		%MigrationStatus.text = "正在导入 %d / %d（语音 %d / %d，图片 %d / %d）…" % [
			int(state.get("done", 0)), int(state.get("total", 0)),
			int(state.get("audio_done", 0)), int(state.get("audio_total", 0)),
			int(state.get("image_done", 0)), int(state.get("image_total", 0)),
		]
	elif mode == "done":
		var summary := _summary(state)
		if _migration_failure(state):
			%MigrationStatus.text = ""
			ErrorDialog.present(self, summary)
		else:
			%MigrationStatus.text = summary
	elif mode == "unavailable":
		%MigrationStatus.text = ""
		ErrorDialog.present(self, _unavailable(str(state.get("code", ""))))
	elif mode == "incremental" and imported > 0:
		%MigrationStatus.text = "已按需导入 %d 条语音。" % imported
	if imported != _last_imported:
		_last_imported = imported
		_refresh_usage_throttled()


func _unavailable(code: String) -> String:
	if code in ["TARGET_MISSING", "TARGET_INVALID", "SOURCE_NOT_FOUND"]:
		return _scan_failure(code)
	if code == "STORAGE_UNAVAILABLE":
		return "缓存目录不可用，请先登录后再导入。"
	return "导入暂不可用，请重新选择 Python 客户端程序。"

func _migration_failure(state: Dictionary) -> bool:
	return str(state.get("code", "")) in ["TARGET_MISSING","TARGET_INVALID","SOURCE_NOT_FOUND","STORAGE_UNAVAILABLE","PARTIAL"]


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


func _refresh_usage_throttled() -> void:
	if not visible: return
	var now := Time.get_ticks_msec()
	if now - _usage_refreshed_ms < USAGE_REFRESH_MS: return
	_usage_refreshed_ms = now
	_refresh_usage()


func _refresh_usage() -> void:
	_scan_generation += 1
	var generation := _scan_generation
	%UsagePercent.text = "--%"
	%UsageState.text = "存储空间扫描中"
	%RefreshUsage.disabled = true
	await get_tree().process_frame
	var data: Dictionary = _storage.query_directory(_directory) if _storage != null else {"directory_bytes":-1,"total_bytes":-1,"free_bytes":-1}
	if generation != _scan_generation: return
	var used: int = data.get("directory_bytes", -1)
	var total: int = data.get("total_bytes", -1)
	var free: int = data.get("free_bytes", -1)
	var known := used >= 0 and total > 0
	var percent := 100.0 * float(used) / float(total) if known else 0.0
	%UsageProgress.value = percent
	%UsageMarker.visible = known
	%UsagePercent.text = ("0%" if used == 0 else ("<0.01%" if percent < 0.01 else "%.2f%%" % percent)) if known else "--%"
	%UsageState.text = "占所在磁盘空间" if known else "存储数据暂不可用"
	%UsageDetails.text = "本账号语音缓存：%s\n\n所在磁盘总容量：%s\n可用容量：%s" % [_format_bytes(used),_format_bytes(total),_format_bytes(free)]
	%RefreshUsage.disabled = false
	_position_marker()


func _position_marker() -> void:
	var center: Vector2 = %UsageRing.size / 2.0
	var radius: float = minf(center.x, center.y) - 24.0
	var angle: float = deg_to_rad(%UsageProgress.value * 3.6 - 90.0)
	%UsageMarker.position = center + Vector2(cos(angle),sin(angle)) * radius - %UsageMarker.size / 2.0


func _format_bytes(bytes: int) -> String:
	if bytes < 0: return "无法读取"
	if bytes < 1024: return "%s bytes" % bytes
	var amount := float(bytes)
	for unit in ["KiB", "MiB", "GiB", "TiB", "PiB"]:
		amount /= 1024.0
		if amount < 1024.0: return "%.2f %s" % [amount, unit]
	return "%s bytes" % bytes
