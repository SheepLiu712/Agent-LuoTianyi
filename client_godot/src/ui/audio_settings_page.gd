extends MarginContainer
const StorageService = preload("res://src/storage/storage_service.gd")
var _clear_cache: Callable
var _clearing := false
var _storage: StorageService
var _directory := ""
var _scan_generation := 0

func setup(clear_cache: Callable, storage_service: StorageService = null, cache_directory: String = "") -> void:
	_clear_cache = clear_cache
	_storage = storage_service
	_directory = cache_directory
	if is_node_ready():
		%ClearCache.disabled = not _clear_cache.is_valid()
		if visible: _refresh_usage()

func _ready() -> void:
	%ClearCache.disabled = not _clear_cache.is_valid()
	%ClearCache.pressed.connect(func(): %ClearDialog.popup_centered())
	%ClearDialog.confirmed.connect(_clear)
	%RefreshUsage.pressed.connect(_refresh_usage)
	%UsageRing.resized.connect(_position_marker)
	visibility_changed.connect(func(): if visible: _refresh_usage())
	_position_marker()
	if visible: _refresh_usage()

func _clear() -> void:
	if _clearing or not _clear_cache.is_valid(): return
	_clearing = true
	%ClearCache.disabled = true
	%CacheStatus.text = "正在清理…"
	await get_tree().process_frame
	var result: Error = _clear_cache.call()
	_clearing = false
	%ClearCache.disabled = false
	%CacheStatus.text = "已清理本账号语音缓存，聊天文字已保留。" if result == OK else "部分语音未能清理，请关闭占用文件后重试。"
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
