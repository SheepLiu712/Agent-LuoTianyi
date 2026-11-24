extends Window
const Schema = preload("res://src/storage/log_schema.gd")
const LogRow = preload("res://src/ui/log_entry_row.gd")
const ErrorDialog = preload("res://src/ui/error_dialog.gd")
const ToastOverlay = preload("res://src/ui/toast_overlay.gd")
const UiMotion = preload("res://src/ui/ui_motion.gd")
const MAX_RENDER_ENTRIES := 500
@export var files: Resource = preload("res://src/platform/file_interaction.gd").new()
@export var input_service: Resource = preload("res://src/platform/input_service.gd").new()
var _logger: RefCounted
var _incomplete_announced := false
@onready var _runs = %RunsDropdown
@onready var _category = %CategoryDropdown
@onready var _module = %ModuleDropdown
@onready var _origin = %OriginDropdown
@onready var _search: LineEdit = %Search
@onready var _follow: BaseButton = %Follow
@onready var _log_scroll: ScrollContainer = %LogScroll
@onready var _log_rows: VBoxContainer = %LogRows
@onready var _status: Label = %Status
@onready var _dropped: Label = %Dropped
@onready var _picker: FileDialog = %Picker
@onready var _copy: Button = %CopyButton
@onready var _export: Button = %ExportButton
var _selected := ""
var _export_id := ""
var _initialized := false
var _search_timer: Timer
var _truncated := false
var _total_count := 0
var _shown_count := 0
var _level_counts := {"INFO": 0, "WARN": 0, "ERROR": 0, "DEBUG": 0}
var _level_enabled := {"INFO": true, "WARN": true, "ERROR": true, "DEBUG": true}
var _visible_entries: Array[Dictionary] = []
var _mono_font: SystemFont


func setup(logger: RefCounted) -> void:
	_logger = logger
	if is_node_ready():
		_initialize()


func _ready() -> void:
	title = "客户端日志 · " + preload("res://src/storage/release_info.gd").title()
	_mono_font = SystemFont.new()
	_mono_font.font_names = PackedStringArray(["Cascadia Mono", "Consolas", "Noto Sans Mono CJK SC", "monospace"])
	UiMotion.bind_interactive_cursors(self)
	if _logger == null:
		return
	_initialize()


func _initialize() -> void:
	if _initialized:
		return
	_initialized = true
	_runs.activated.connect(func(index):
		_selected = index
		_refresh())
	_populate_dropdowns()
	_bind_level_chips()
	_bind_search_and_actions()
	close_requested.connect(hide)
	_logger.entry_added.connect(_on_entry_added)
	_logger.write_failed.connect(func(_error):
		ToastOverlay.present_in(self, "归档可能不完整，当前窗口仍可查看本次记录。", "warning", 4.0))


func _populate_dropdowns() -> void:
	var categories: Array = [{"id": "all", "label": "类别：全部"}]
	for category in Schema.CATEGORIES:
		categories.append({"id": category, "label": "类别：%s" % LogRow.CATEGORY_SHORT.get(category, category)})
	_category.set_items(categories)
	var modules: Array = [{"id": "all", "label": "模块：全部"}]
	for module in _logger.MODULES:
		modules.append({"id": module, "label": "模块：%s" % module})
	_module.set_items(modules)
	var origins: Array = [{"id": "all", "label": "归属：全部"}]
	for origin in Schema.ORIGINS:
		origins.append({"id": origin, "label": "归属：%s" % Schema.ORIGIN_LABELS[origin]})
	_origin.set_items(origins)
	_category.activated.connect(func(_index): _refresh())
	_module.activated.connect(func(_index): _refresh())
	_origin.activated.connect(func(_index): _refresh())


func _bind_level_chips() -> void:
	for pair in [["INFO", %ChipInfo], ["WARN", %ChipWarn], ["ERROR", %ChipError], ["DEBUG", %ChipDebug]]:
		var level: String = pair[0]
		var chip: Button = pair[1]
		chip.set_pressed_no_signal(true)
		chip.toggled.connect(func(on: bool):
			_level_enabled[level] = on
			chip.modulate.a = 1.0 if on else 0.45
			_refresh())


func _bind_search_and_actions() -> void:
	_search_timer = Timer.new()
	_search_timer.wait_time = 0.2
	_search_timer.one_shot = true
	_search_timer.timeout.connect(_refresh)
	add_child(_search_timer)
	_search.text_changed.connect(func(_value): _search_timer.start())
	_search.focus_entered.connect(func(): _style_search_frame(true))
	_search.focus_exited.connect(func(): _style_search_frame(false))
	_follow.toggled.connect(func(value):
		if value:
			_scroll_to_bottom.call_deferred())
	_copy.pressed.connect(_copy_visible)
	files.bind(_picker)
	_export.pressed.connect(func():
		_export_id = _selected
		files.select_export("agentluo-diagnostics-" + _selected + ".zip"))
	files.export_selected.connect(_on_export_selected)


func _style_search_frame(focused: bool) -> void:
	var box := StyleBoxFlat.new()
	box.bg_color = Color.WHITE
	box.set_corner_radius_all(6)
	box.set_border_width_all(2 if focused else 1)
	box.border_color = Color("66ccff") if focused else Color("dbe7f0")
	box.content_margin_left = 12.0
	box.content_margin_right = 12.0
	%SearchFrame.add_theme_stylebox_override("panel", box)


func _copy_visible() -> void:
	if input_service.copy_text(_format_copy_text()) == OK:
		ToastOverlay.present_in(self, "已复制当前显示的日志。", "success")
	else:
		ErrorDialog.present(self, "复制失败，请检查系统剪贴板。")


func _format_copy_text() -> String:
	var lines: Array[String] = []
	for entry in _visible_entries:
		var cat := str(Schema.CATEGORY_LABELS.get(entry.get("category", "system"), "系统"))
		lines.append("%s [%s] [%s] [%s] %s · %s %s" % [
			entry.get("time", ""), entry.get("level", ""), cat,
			entry.get("module", ""), entry.get("message", ""), entry.get("event", ""),
			JSON.stringify(entry)
		])
	return "\n".join(lines)


func _on_export_selected(target: Variant) -> void:
	var error: Error = target.export_log(_logger, _export_id)
	if error == OK:
		ToastOverlay.present_in(self, "完整诊断包已导出。", "success")
	else:
		ErrorDialog.present(self, "导出失败：目标文件已存在或不可写，请换一个路径。")


func open() -> void:
	_logger.drain()
	var options: Array = []
	_selected = _logger.get_run_id() if _selected.is_empty() else _selected
	var runs: Array = _logger.list_runs()
	if not runs.any(func(run): return run.id == _logger.get_run_id()):
		runs.push_front({"id": _logger.get_run_id(), "started": "本次启动", "closed": false, "active": true, "complete": false})
	for run in runs:
		options.append({"id": run.id, "label": _format_run_label(run)})
	_runs.set_items(options)
	_runs.set_selected_id(_selected)
	_selected = _runs.get_selected_id()
	_refresh()
	%Chrome.open_window()


func _format_run_label(run: Dictionary) -> String:
	var stamp := str(run.get("started", "")).replace("T", " ").trim_suffix("Z")
	if run.id == _logger.get_run_id():
		return "本次启动 · " + stamp
	if not bool(run.get("closed", true)):
		return ("%s · 运行中" if bool(run.get("active", false)) else "%s · 未正常结束") % stamp
	return stamp


func _refresh() -> void:
	_clear_rows()
	var entries: Array = _logger.read_entries(_selected)
	_total_count = entries.size()
	_count_levels(entries)
	var matching: Array[Dictionary] = []
	for entry in entries:
		if _matches(entry):
			matching.append(entry)
	_shown_count = matching.size()
	_truncated = matching.size() > MAX_RENDER_ENTRIES
	var slice := matching.slice(matching.size() - MAX_RENDER_ENTRIES) if _truncated else matching
	_visible_entries = slice
	for entry in slice:
		_add_row(entry)
	_update_summary()
	_announce_incomplete()
	if _follow.button_pressed:
		_scroll_to_bottom.call_deferred()


func _clear_rows() -> void:
	_visible_entries.clear()
	for child in _log_rows.get_children():
		_log_rows.remove_child(child)
		child.queue_free()


func _count_levels(entries: Array) -> void:
	_level_counts = {"INFO": 0, "WARN": 0, "ERROR": 0, "DEBUG": 0}
	for entry in entries:
		var lvl := str(entry.get("level", "INFO"))
		_level_counts[lvl] = int(_level_counts.get(lvl, 0)) + 1
	_sync_level_chips()


func _sync_level_chips() -> void:
	%ChipInfo.text = "INFO %d" % _level_counts.INFO
	%ChipWarn.text = "WARN %d" % _level_counts.WARN
	%ChipError.text = "ERROR %d" % _level_counts.ERROR
	%ChipDebug.text = "DEBUG %d" % _level_counts.DEBUG


func _on_entry_added(entry: Dictionary) -> void:
	if not visible or _selected != _logger.get_run_id():
		return
	_total_count += 1
	var lvl := str(entry.get("level", "INFO"))
	_level_counts[lvl] = int(_level_counts.get(lvl, 0)) + 1
	_sync_level_chips()
	if _matches(entry):
		_shown_count += 1
		if _log_rows.get_child_count() >= MAX_RENDER_ENTRIES:
			var first := _log_rows.get_child(0)
			_log_rows.remove_child(first)
			first.queue_free()
			if not _visible_entries.is_empty():
				_visible_entries.remove_at(0)
			_truncated = true
		_visible_entries.append(entry)
		_add_row(entry)
		if _follow.button_pressed:
			_scroll_to_bottom.call_deferred()
	_update_summary()


func _add_row(entry: Dictionary) -> void:
	var row := LogRow.new()
	row.setup(entry, _mono_font)
	_log_rows.add_child(row)


func _scroll_to_bottom() -> void:
	if not is_inside_tree():
		return
	var bar := _log_scroll.get_v_scroll_bar()
	_log_scroll.scroll_vertical = maxi(0, int(bar.max_value))


func _update_summary() -> void:
	var text := "共 %d 条 · 显示 %d 条" % [_total_count, _shown_count]
	if _truncated:
		text += "（显示最新 %d 条）" % MAX_RENDER_ENTRIES
	_status.text = text
	var dropped := _drop_counts()
	var d_limit := int(dropped.get("limit", 0))
	var d_pending := int(dropped.get("pending", 0))
	var d_total := d_limit + d_pending + int(dropped.get("debug", 0))
	_dropped.text = "丢弃 %d（容量 %d / 队列 %d）" % [d_total, d_limit, d_pending]


func _drop_counts() -> Dictionary:
	if _selected == _logger.get_run_id():
		var stats: Dictionary = _logger.get_stats()
		return {"limit": stats.get("dropped_limit", 0), "pending": stats.get("dropped_pending", 0), "debug": stats.get("dropped_debug", 0)}
	for run in _logger.list_runs():
		if run.id == _selected:
			return {"limit": run.get("dropped_limit", 0), "pending": run.get("dropped_pending", 0), "debug": run.get("dropped_debug", 0)}
	return {}


func _announce_incomplete() -> void:
	if _incomplete_announced:
		return
	for run in _logger.list_runs():
		if run.id == _selected and not run.complete:
			_incomplete_announced = true
			ErrorDialog.present(self, "归档可能不完整，当前窗口仍可查看本次记录。")
			return


func _matches(entry: Dictionary) -> bool:
	var lvl := str(entry.get("level", "INFO"))
	if not bool(_level_enabled.get(lvl, true)):
		return false
	return _filters_match(entry) and _search_matches(entry)


func _filters_match(entry: Dictionary) -> bool:
	return _selected_matches(_category, entry.get("category", "info")) \
		and _selected_matches(_module, entry.get("module", "")) \
		and _selected_matches(_origin, entry.get("origin", "unknown"))


func _selected_matches(control: Node, value: Variant) -> bool:
	var selected: Variant = control.get_selected_id()
	return selected == "all" or value == selected


func _search_matches(entry: Dictionary) -> bool:
	var needle := _search.text.strip_edges().to_lower()
	if needle.is_empty():
		return true
	var haystack := "%s %s %s %s %s %s %s" % [entry.get("event", ""), entry.get("message", ""), entry.get("detail", ""),
		entry.get("code", ""), entry.get("module", ""), entry.get("category", ""), entry.get("trace_id", "")]
	if entry.get("data") is Dictionary:
		haystack += " " + JSON.stringify(entry.data)
	return haystack.to_lower().contains(needle)


func _exit_tree() -> void:
	files.cancel()
