extends MarginContainer

const StorageService = preload("res://src/storage/storage_service.gd")
const MigrationPort = preload("res://src/storage/python_media_migration_port.gd")
const StatusBanner = preload("res://src/ui/status_banner.gd")
const UiMotion = preload("res://src/ui/ui_motion.gd")
const SETTINGS_SECTION := "storage"
const SETTINGS_LAST_SCAN := "last_scan_at"
const SETTINGS_SNAPSHOT := "usage_snapshot"
const SNAPSHOT_VERSION := 1
const BUTTON_START := "开始扫描"
const BUTTON_RESCAN := "重新扫描"
const BUTTON_SCANNING := "正在扫描…"
const LABEL_UNSCANNED := "尚未扫描"
const LABEL_SCANNING := "扫描中…"
const LABEL_AVAILABLE := "客户端占磁盘"
const LABEL_UNAVAILABLE := "容量数据暂不可用"
const ACTION_START := "start"
const ACTION_DETECT := "detect"
const ACTION_IMPORT := "import"

var _ui_style: RefCounted
var _migration_kind := "muted"
var _cache_kind := "muted"

var _clear_cache: Callable
var _clearing := false
var _storage: StorageService
var _directory := ""
var _app_directory := ""
var _scan_generation := 0
var _pending_days := 0
var _migration: MigrationPort
var _last_imported := 0
var _settings_store: Resource
var _scope := ""
var _scanning := false
var _last_scan_at := 0
var _has_snapshot := false
var _scan_ok := false
var _importable := false
var _already_imported := false
var _pending_audio := 0
var _pending_images := 0
var _button_action := ACTION_START


func setup(
	clear_cache: Callable,
	storage_service: StorageService = null,
	cache_directory: String = "",
	migration: MigrationPort = null,
	app_data_directory: String = "",
	settings_store: Resource = null,
	scope: String = ""
) -> void:
	_clear_cache = clear_cache
	_storage = storage_service
	_directory = cache_directory
	_app_directory = app_data_directory if not app_data_directory.is_empty() else cache_directory
	_migration = migration
	_settings_store = settings_store
	_scope = scope
	_scan_generation += 1
	_scanning = false
	if is_node_ready():
		%ClearCache.disabled = not _clear_cache.is_valid()
		_apply_migration()
		# 设置窗预暖时父 Window 仍隐藏；显示后再恢复未检测状态。
		if is_visible_in_tree():
			_reset_import_view()
		_load_saved_usage()


## 设置窗可能在页面就绪后才拿到导入服务，所以允许二次注入。
func set_media_migration(migration: MigrationPort) -> void:
	_migration = migration
	if is_node_ready():
		_apply_migration()
		if is_visible_in_tree():
			_reset_import_view()


## 兼容旧调用名：该页面现在同时管理语音与图片。
func set_audio_migration(migration: MigrationPort) -> void:
	set_media_migration(migration)


func set_ui_style(ui_style: RefCounted) -> void:
	if _ui_style != null and _ui_style.style_changed.is_connected(_reapply_banner_styles):
		_ui_style.style_changed.disconnect(_reapply_banner_styles)
	_ui_style = ui_style
	if _ui_style != null:
		_ui_style.style_changed.connect(_reapply_banner_styles)
	if is_node_ready():
		_reapply_banner_styles()


func _reapply_banner_styles() -> void:
	StatusBanner.apply_surface_status(%MigrationStatusPanel, %MigrationStatus, _migration_kind, _ui_style)
	if %CacheStatusPanel.visible:
		StatusBanner.apply_surface_status(%CacheStatusPanel, %CacheStatus, _cache_kind, _ui_style)


func _ready() -> void:
	UiMotion.bind_interactive_cursors(self)
	%OlderThanDays.custom_minimum_size.y = maxf(%OlderThanDays.custom_minimum_size.y, 40.0)
	%OlderThanDays.get_line_edit().theme_type_variation = &"SettingsLineEdit"
	%ClearCache.disabled = not _clear_cache.is_valid()
	%ClearCache.pressed.connect(_request_clear)
	%MigrateMedia.pressed.connect(_request_migrate)
	%BrowsePython.pressed.connect(_request_pick)
	%PythonPicker.file_selected.connect(_on_python_selected)
	%PythonPicker.canceled.connect(func(): %PythonPicker.hide())
	%ClearDialog.confirmed.connect(_clear)
	%MigrationDialog.confirmed.connect(_migrate)
	%RefreshUsage.pressed.connect(_scan_usage)
	visibility_changed.connect(func():
		if is_visible_in_tree():
			_reset_import_view())
	_apply_migration()
	_load_saved_usage()
	if is_visible_in_tree():
		_reset_import_view()


## 未接线时导入按钮保持禁用：没有服务就不能让用户以为已经点过了。
func _apply_migration() -> void:
	%MigrateMedia.disabled = _migration == null
	%BrowsePython.disabled = _migration == null
	if _migration == null:
		%PythonPath.text = ""
		%PythonPath.tooltip_text = ""
		_button_action = ACTION_START
		_set_migration_status("导入暂不可用。", "muted")
		_update_import_button(false)
		return
	if not _migration.progress.is_connected(_on_migration_progress):
		_migration.progress.connect(_on_migration_progress)
	var state: Dictionary = _migration.get_state()
	# 预暖时同步一次已有进度，不能把历史导入量当成刚刚发生的缓存变化。
	_last_imported = int(state.get("imported", 0))
	_on_migration_progress(state)


## 显式检测才扫描：打开页面不自动读盘。
func _refresh_scan() -> void:
	if _migration == null:
		_set_migration_status("导入暂不可用。", "muted")
		return
	var result := _migration.scan()
	_show_target()
	_apply_scan(result)


func _reset_import_view() -> void:
	_scan_ok = false
	_importable = false
	_already_imported = false
	_pending_audio = 0
	_pending_images = 0
	_show_target()
	if _migration == null:
		_button_action = ACTION_START
		_set_migration_status("导入暂不可用。", "muted")
	else:
		_button_action = ACTION_DETECT if not %PythonPath.text.strip_edges().is_empty() else ACTION_START
		_set_migration_status("", "muted")
	_update_import_button(false)


func _show_target() -> void:
	var path := _migration.get_target_path() if _migration != null else ""
	%PythonPath.text = path
	%PythonPath.tooltip_text = path


func _apply_scan(result: Dictionary) -> void:
	_scan_ok = bool(result.get("ok", false))
	var audio := int(result.get("audio_count", 0))
	var images := int(result.get("image_count", 0))
	_pending_audio = int(result.get("pending_audio_count", 0))
	_pending_images = int(result.get("pending_image_count", 0))
	_already_imported = _scan_ok and bool(result.get("already_imported", false))
	_importable = _scan_ok and _pending_audio + _pending_images > 0
	if not _scan_ok:
		_button_action = ACTION_DETECT if not %PythonPath.text.strip_edges().is_empty() else ACTION_START
		_update_import_button(false)
		_show_scan_failure(result)
		return
	_button_action = ACTION_IMPORT if _importable or _already_imported else ACTION_DETECT
	_update_import_button(false)
	_set_migration_status(_scan_summary(result, audio, images), _scan_kind())


func _show_scan_failure(result: Dictionary) -> void:
	var code := str(result.get("code", "TARGET_MISSING"))
	var kind := "muted" if code == "TARGET_MISSING" and %PythonPath.text.is_empty() else ("warning" if code == "TARGET_MISSING" else "error")
	_set_migration_status(_scan_failure(code), kind)


func _scan_kind() -> String:
	if _already_imported:
		return "success"
	var mismatch := _migration != null and bool(_migration.get_state().get("mismatch", false))
	return "warning" if mismatch or not _importable else "success"


func _scan_summary(result: Dictionary, audio: int, images: int) -> String:
	if bool(result.get("already_imported", false)):
		return "已导入：语音 %d 条，图片 %d 张。" % [audio, images]
	var pending_audio := int(result.get("pending_audio_count", 0))
	var pending_images := int(result.get("pending_image_count", 0))
	var text := "没有可导入的媒体。"
	if pending_audio + pending_images > 0:
		text = ("新增：语音 %d 条，图片 %d 张。" if bool(result.get("has_previous_import", false))
			else "可导入：语音 %d 条，图片 %d 张。") % [pending_audio, pending_images]
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
	var enabled := _migration != null and not busy
	if _button_action == ACTION_IMPORT:
		enabled = enabled and _importable and not _already_imported
	%MigrateMedia.disabled = not enabled
	%MigrateMedia.text = _action_text()
	%BrowsePython.disabled = _migration == null or busy
	%ClearCache.disabled = busy or not _clear_cache.is_valid()


func _action_text() -> String:
	match _button_action:
		ACTION_IMPORT:
			return "导入媒体…"
		ACTION_DETECT:
			return "重新检测"
		_:
			return "开始检测"


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
		_invalidate_usage()
		_set_cache_status(
			"已清理本账号全部语音缓存。" if _pending_days == 0 else "已清理本账号 %s 天之前的语音缓存。" % _pending_days,
			"success"
		)
	else:
		_set_cache_status("部分语音文件被占用，关闭后重试。", "error")


func _request_migrate() -> void:
	if _migration == null or _migration.is_busy():
		return
	if _button_action != ACTION_IMPORT:
		if _migration.get_target_path().strip_edges().is_empty():
			_request_pick()
		else:
			_refresh_scan()
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
		_show_migration_progress(state)
	else:
		_show_migration_result(state, mode, imported)
	_track_imported(imported)


func _show_migration_progress(state: Dictionary) -> void:
	_set_migration_status("正在导入 %d / %d（语音 %d / %d，图片 %d / %d）…" % [
		int(state.get("done", 0)), int(state.get("total", 0)),
		int(state.get("audio_done", 0)), int(state.get("audio_total", 0)),
		int(state.get("image_done", 0)), int(state.get("image_total", 0)),
	], "info")


func _show_migration_result(state: Dictionary, mode: String, imported: int) -> void:
	if mode == "done":
		_show_done(state)
	elif mode == "unavailable":
		_set_detection_action()
		_set_migration_status(_unavailable(str(state.get("code", ""))), "error")
	elif mode == "incremental" and imported > 0:
		_set_migration_status("已按需导入 %d 条语音。" % imported, "success")


func _show_done(state: Dictionary) -> void:
	if not _migration_failure(state):
		_refresh_scan()
		return
	_set_migration_status(_summary(state), "warning")
	if str(state.get("code", "")) != "PARTIAL":
		_set_detection_action()


func _set_detection_action() -> void:
	_button_action = ACTION_DETECT if not %PythonPath.text.strip_edges().is_empty() else ACTION_START
	_update_import_button(false)


func _track_imported(imported: int) -> void:
	if imported == _last_imported:
		return
	_last_imported = imported
	if imported > 0:
		_invalidate_usage()


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


## 唯一的容量入口：只有用户点击按钮时才读盘。
func _scan_usage() -> void:
	if _scanning:
		return
	_scan_generation += 1
	var generation := _scan_generation
	_scanning = true
	%UsageState.text = LABEL_SCANNING
	_update_scan_controls()
	await get_tree().process_frame
	if generation != _scan_generation or not is_inside_tree():
		return
	var root_directory := _app_directory if not _app_directory.is_empty() else _directory
	var root_data := _query_directory(root_directory)
	var cache_data := root_data if _directory == root_directory else _query_directory(_directory)
	if generation != _scan_generation:
		return
	_scanning = false
	_has_snapshot = _is_renderable(root_data, cache_data)
	_last_scan_at = int(Time.get_unix_time_from_system())
	_render_usage(root_data, cache_data)
	_update_scan_controls()
	_persist_usage(root_data, cache_data)


func _render_usage(root_data: Dictionary, cache_data: Dictionary) -> void:
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
		%UsageState.text = LABEL_AVAILABLE
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
		%UsageState.text = LABEL_UNAVAILABLE
		%StorageTotal.text = "整盘 --"
		_set_usage_legend("--", "--", "--", "--", "--", "--")
		%AccountNote.text = "其中本账号语音缓存：%s" % (_format_bytes(account) if account >= 0 else "暂不可用")


func _render_unscanned() -> void:
	%UsageRing.set_unavailable()
	%UsagePercent.text = "--%"
	%UsageState.text = LABEL_UNSCANNED
	%StorageTotal.text = "整盘 --"
	_set_usage_legend("--", "--", "--", "--", "--", "--")
	%AccountNote.text = "其中本账号语音缓存：--"
	_update_scan_controls()


func _update_scan_controls() -> void:
	%RefreshUsage.disabled = _scanning
	%RefreshUsage.text = BUTTON_SCANNING if _scanning else (
		BUTTON_RESCAN if _has_snapshot or _last_scan_at > 0 else BUTTON_START)
	%LastScan.text = "尚未扫描" if _last_scan_at <= 0 else "上次扫描：%s" % _format_scan_time(_last_scan_at)


func _format_scan_time(timestamp: int) -> String:
	var bias: int = int(Time.get_time_zone_from_system().get("bias", 0)) * 60
	return Time.get_datetime_string_from_unix_time(timestamp + bias).replace("T", " ").substr(0, 16)


func _is_renderable(root_data: Dictionary, cache_data: Dictionary) -> bool:
	var client := int(root_data.get("directory_bytes", -1))
	var total := int(root_data.get("total_bytes", -1))
	var free := int(root_data.get("free_bytes", -1))
	return client >= 0 and total > 0 and free >= 0 and free <= total


func _load_saved_usage() -> void:
	_last_scan_at = 0
	_has_snapshot = false
	if _settings_store != null:
		var saved_at: Variant = _settings_store.get_value(SETTINGS_SECTION, SETTINGS_LAST_SCAN, 0)
		if saved_at is int or saved_at is float:
			_last_scan_at = maxi(0, int(saved_at))
		var snapshot: Variant = _settings_store.get_value(SETTINGS_SECTION, SETTINGS_SNAPSHOT, {})
		if _last_scan_at > 0 and _valid_snapshot(snapshot):
			_has_snapshot = true
			var root_data := {
				"directory_bytes": int(snapshot.app_bytes),
				"total_bytes": int(snapshot.total_bytes),
				"free_bytes": int(snapshot.free_bytes),
			}
			_render_usage(root_data, {"directory_bytes": int(snapshot.account_bytes)})
			_update_scan_controls()
			return
	_last_scan_at = 0
	_render_unscanned()


func _valid_snapshot(snapshot: Variant) -> bool:
	if not snapshot is Dictionary:
		return false
	if int(snapshot.get("version", 0)) != SNAPSHOT_VERSION:
		return false
	if str(snapshot.get("scope", "")) != _scope:
		return false
	return _valid_snapshot_bytes(snapshot)


func _valid_snapshot_bytes(snapshot: Dictionary) -> bool:
	for key in ["app_bytes", "total_bytes", "free_bytes", "account_bytes"]:
		var value: Variant = snapshot.get(key)
		if not (value is int or value is float):
			return false
	var app_bytes := int(snapshot.app_bytes)
	var total_bytes := int(snapshot.total_bytes)
	var free_bytes := int(snapshot.free_bytes)
	var account_bytes := int(snapshot.account_bytes)
	if app_bytes < 0 or total_bytes <= 0 or free_bytes < 0:
		return false
	return free_bytes <= total_bytes and account_bytes >= -1


func _persist_usage(root_data: Dictionary, cache_data: Dictionary) -> void:
	if _settings_store == null:
		return
	_settings_store.set_value(SETTINGS_SECTION, SETTINGS_LAST_SCAN, _last_scan_at)
	_settings_store.set_value(SETTINGS_SECTION, SETTINGS_SNAPSHOT, _snapshot(root_data, cache_data) if _has_snapshot else {})
	var error: Error = _settings_store.save_settings()
	if error != OK:
		push_warning("Storage usage could not be saved (%s)" % error)


func _snapshot(root_data: Dictionary, cache_data: Dictionary) -> Dictionary:
	return {
		"version": SNAPSHOT_VERSION,
		"scope": _scope,
		"app_bytes": int(root_data.get("directory_bytes", -1)),
		"total_bytes": int(root_data.get("total_bytes", -1)),
		"free_bytes": int(root_data.get("free_bytes", -1)),
		"account_bytes": int(cache_data.get("directory_bytes", -1)),
	}


func _invalidate_usage() -> void:
	_scan_generation += 1
	_scanning = false
	_last_scan_at = 0
	_has_snapshot = false
	if _settings_store != null:
		_settings_store.set_value(SETTINGS_SECTION, SETTINGS_LAST_SCAN, 0)
		_settings_store.set_value(SETTINGS_SECTION, SETTINGS_SNAPSHOT, {})
		var error: Error = _settings_store.save_settings()
		if error != OK:
			push_warning("Storage usage could not be cleared (%s)" % error)
	_render_unscanned()


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
	_migration_kind = kind
	var active := not text.is_empty()
	%MigrationStatusPanel.visible = active
	%MigrationStatus.text = text
	if active:
		StatusBanner.apply_surface_status(%MigrationStatusPanel, %MigrationStatus, kind, _ui_style)


func _set_cache_status(text: String, kind: String) -> void:
	_cache_kind = kind
	var active := not text.is_empty()
	%CacheStatusPanel.visible = active
	%CacheStatus.text = text
	if active:
		StatusBanner.apply_surface_status(%CacheStatusPanel, %CacheStatus, kind, _ui_style)


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
