extends MarginContainer
var _clear_cache: Callable
var _clearing := false

func setup(clear_cache: Callable) -> void:
	_clear_cache = clear_cache
	if is_node_ready(): %ClearCache.disabled = not _clear_cache.is_valid()

func _ready() -> void:
	%ClearCache.disabled = not _clear_cache.is_valid()
	%ClearCache.pressed.connect(func(): %ClearDialog.popup_centered())
	%ClearDialog.confirmed.connect(_clear)

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
