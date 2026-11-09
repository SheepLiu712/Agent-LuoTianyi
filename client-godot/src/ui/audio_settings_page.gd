extends MarginContainer
const StorageService = preload("res://src/storage/storage_service.gd")
const MigrationPort = preload("res://src/storage/audio_migration_port.gd")
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

func setup(clear_cache: Callable, storage_service: StorageService = null, cache_directory: String = "", migration: MigrationPort = null) -> void:
	_clear_cache = clear_cache
	_storage = storage_service
	_directory = cache_directory
	_migration = migration
	if is_node_ready():
		%ClearCache.disabled = not _clear_cache.is_valid()
		_apply_migration()
		if visible: _refresh_usage()

## 设置窗可能在页面就绪后才拿到迁移服务，所以允许二次注入。
func set_audio_migration(migration: MigrationPort) -> void:
	_migration = migration
	if is_node_ready(): _apply_migration()

func _ready() -> void:
	%ClearCache.disabled = not _clear_cache.is_valid()
	%ClearCache.pressed.connect(_request_clear)
	%MigrateAudio.pressed.connect(_request_migrate)
	%ClearDialog.confirmed.connect(_clear)
	%MigrationDialog.confirmed.connect(_migrate)
	%RefreshUsage.pressed.connect(_refresh_usage)
	%UsageRing.resized.connect(_position_marker)
	visibility_changed.connect(func(): if visible: _refresh_usage())
	_apply_migration()
	_position_marker()
	if visible: _refresh_usage()

## 迁移未接线时按钮保持禁用：没有服务就不能让用户以为已经点过了。
func _apply_migration() -> void:
	%MigrateAudio.disabled = _migration == null
	if _migration == null:
		%MigrationStatus.text = ""
		return
	if not _migration.progress.is_connected(_on_migration_progress):
		_migration.progress.connect(_on_migration_progress)
	_on_migration_progress(_migration.get_state())

func _request_clear() -> void:
	var days: float = %OlderThanDays.value
	if not is_finite(days) or days < 0 or days > 1000000000000:
		%CacheStatus.text = "请输入有效的非负整数天数。"
		return
	if _migration != null and _migration.is_busy():
		%CacheStatus.text = "正在迁移语音，请等迁移完成后再清理。"
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
	%CacheStatus.text = (("已清理本账号全部语音缓存。" if _pending_days == 0 else "已清理本账号 %s 天之前的语音缓存。" % _pending_days) + "聊天文字已保留。") if result == OK else "部分语音未能清理，请关闭占用文件后重试。"
	_refresh_usage()

func _request_migrate() -> void:
	if _migration == null or _migration.is_busy(): return
	%MigrationDialog.dialog_text = "把本机 Python 客户端保存的语音迁入当前账号？\n\n只新增、不覆盖：已有缓存保持不变，源文件保留。迁移期间可以继续聊天。"
	%MigrationDialog.popup_centered()

func _migrate() -> void:
	if _migration == null: return
	%MigrationStatus.text = "正在查找 Python 客户端的语音目录…"
	%MigrateAudio.disabled = true
	_migration.request_all()

## 进度由端口推来：批量迁移显示进度，结束后给出可核对的计数。
func _on_migration_progress(state: Dictionary) -> void:
	var busy := bool(state.get("busy", false))
	var mode := str(state.get("mode", "idle"))
	var imported := int(state.get("imported", 0))
	%MigrateAudio.disabled = _migration == null or busy
	%ClearCache.disabled = busy or not _clear_cache.is_valid()
	if busy:
		if mode == "bulk":
			%MigrationStatus.text = "正在迁移 %d / %d 条语音…" % [int(state.get("done", 0)), int(state.get("total", 0))]
		else:
			%MigrationStatus.text = "正在按需迁入 %d / %d 条语音…" % [int(state.get("done", 0)), int(state.get("total", 0))]
	elif mode == "done":
		%MigrationStatus.text = _summary(state)
	elif mode == "unavailable":
		%MigrationStatus.text = "当前没有可用的语音缓存目录，迁移暂不可用。"
	elif mode == "incremental" and imported > 0:
		%MigrationStatus.text = "已按需迁入 %d 条语音。" % imported
	if imported != _last_imported:
		_last_imported = imported
		_refresh_usage_throttled()

func _summary(state: Dictionary) -> String:
	match str(state.get("code", "")):
		"SOURCE_NOT_FOUND":
			return "未找到 Python 客户端的语音目录。若之前用过 Python 客户端，可把它的 temp/tts_output 放到客户端目录旁再试。"
		"SOURCE_EMPTY":
			return "Python 语音目录里没有可迁移的文件。"
		"PARTIAL", "":
			var text := "已迁入 %d 条语音，跳过 %d 条（已存在或不可用），失败 %d 条。" % [
				int(state.get("imported", 0)), int(state.get("skipped", 0)), int(state.get("failed", 0)),
			]
			return text + ("未成功的条目会在翻看历史时自动重试。" if int(state.get("failed", 0)) > 0 else "")
		_:
			return "迁移未完成，请稍后重试。"

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
