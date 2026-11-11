extends Window
const Schema = preload("res://src/storage/log_schema.gd")
const ErrorDialog = preload("res://src/ui/error_dialog.gd")
@export var files: Resource = preload("res://src/platform/file_interaction.gd").new()
@export var input_service: Resource = preload("res://src/platform/input_service.gd").new()
var _logger: RefCounted
var _incomplete_announced := false
@onready var _runs = %RunsDropdown
@onready var _category = %CategoryDropdown
@onready var _level = %LevelDropdown
@onready var _module = %ModuleDropdown
@onready var _origin = %OriginDropdown
@onready var _search: LineEdit = %Search
@onready var _follow: CheckBox = %Follow
@onready var _text: RichTextLabel = %Text
@onready var _status: Label = %Status
@onready var _picker: FileDialog = %Picker
@onready var _copy: Button = %CopyButton
@onready var _export: Button = %ExportButton
var _selected := ""
var _export_id := ""
var _initialized := false
var _search_timer: Timer

func setup(logger: RefCounted) -> void:
	_logger = logger
	if is_node_ready():
		_initialize()

func _ready() -> void:
	title = "客户端日志 · " + preload("res://src/storage/release_info.gd").title()
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
	_level.set_items([{"id":"all","label":"全部级别"},{"id":"DEBUG","label":"DEBUG"},{"id":"INFO","label":"INFO"},{"id":"WARN","label":"WARN"},{"id":"ERROR","label":"ERROR"}])
	var categories: Array = [{"id":"all","label":"全部类别"}]
	for category in Schema.CATEGORIES:
		categories.append({"id":category,"label":Schema.CATEGORY_LABELS[category]})
	_category.set_items(categories)
	var modules: Array = [{"id":"all","label":"全部模块"}]
	for module in _logger.MODULES:
		modules.append({"id":module,"label":module})
	_module.set_items(modules)
	var origins: Array = [{"id":"all","label":"全部归属"}]
	for origin in Schema.ORIGINS:
		origins.append({"id":origin,"label":Schema.ORIGIN_LABELS[origin]})
	_origin.set_items(origins)
	_level.activated.connect(func(_index): _refresh())
	_category.activated.connect(func(_index): _refresh())
	_module.activated.connect(func(_index): _refresh())
	_origin.activated.connect(func(_index): _refresh())
	_search_timer = Timer.new()
	_search_timer.wait_time = 0.2
	_search_timer.one_shot = true
	_search_timer.timeout.connect(_refresh)
	add_child(_search_timer)
	# 每次按键都全量过滤 5 万条会让输入卡顿；合并到 200ms 后再刷新。
	_search.text_changed.connect(func(_value): _search_timer.start())
	_follow.toggled.connect(func(value):
		_text.scroll_following = value
		if value:
			_text.scroll_to_line(maxi(0,_text.get_line_count()-1)))
	_text.scroll_following = true
	_copy.pressed.connect(func():
		if input_service.copy_text(_text.get_parsed_text()) != OK:
			_status.text = ""
			ErrorDialog.present(self, "复制失败，请手动选择文本。"))
	files.bind(_picker)
	_export.pressed.connect(func():
		_export_id = _selected
		files.select_export("agentluo-diagnostics-" + _selected + ".zip"))
	files.export_selected.connect(func(target):
		var error: Error = target.export_log(_logger,_export_id)
		if error == OK:
			_status.text = "所选启动的完整诊断已导出（未上传）。"
		else:
			_status.text = ""
			ErrorDialog.present(self, "导出失败：目标文件已存在或不可写，请换一个路径。"))
	close_requested.connect(hide)
	_logger.entry_added.connect(func(entry):
		if visible and _selected == _logger.get_run_id() and _matches(entry):
			_append(entry))
	_logger.write_failed.connect(func(_error):
		_status.text = ""
		ErrorDialog.present(self, "归档可能不完整，当前窗口仍可查看本次记录。"))
func open() -> void:
	_logger.drain()
	var options: Array = []
	_selected = _logger.get_run_id() if _selected.is_empty() else _selected
	var runs: Array = _logger.list_runs()
	if not runs.any(func(run): return run.id == _logger.get_run_id()):
		runs.push_front({"id":_logger.get_run_id(),"started":"本次启动（未能保存）","closed":false,"active":true,"complete":false})
	for run in runs:
		var caption: String = run.started
		if run.id == _logger.get_run_id():
			caption += " · 本次启动"
		elif not run.closed:
			caption += " · 运行中" if run.active else " · 未正常结束"
		elif run.get("legacy_unverified", false):
			caption += " · 旧归档未校验"
		options.append({"id":run.id,"label":caption})
	_runs.set_items(options)
	_runs.set_selected_id(_selected)
	_selected = _runs.get_selected_id()
	_refresh()
	%Chrome.open_window()

func _refresh() -> void:
	_text.clear()
	var entries: Array = _logger.read_entries(_selected)
	_append_matching(entries)
	_update_status_summary(entries)
	_announce_incomplete()

func _append_matching(entries: Array) -> void:
	for entry in entries:
		if _matches(entry):
			_append(entry)

func _update_status_summary(entries: Array) -> void:
	var counts := {}
	for entry in entries:
		var category: String = entry.get("category", "info")
		counts[category] = int(counts.get(category, 0)) + 1
	var parts: Array[String] = []
	for category in Schema.CATEGORIES:
		var count := int(counts.get(category, 0))
		if count > 0:
			parts.append("%s %s" % [Schema.CATEGORY_LABELS[category], count])
	_status.text = "共 %s 条记录；筛选只影响显示，导出包含整次启动。" % entries.size()
	if not parts.is_empty():
		_status.text = "共 %s 条记录（%s）；筛选只影响显示，导出包含整次启动。" % [entries.size(), " / ".join(parts)]

func _announce_incomplete() -> void:
	if _incomplete_announced:
		return
	for run in _logger.list_runs():
		if run.id == _selected and not run.complete:
			_incomplete_announced = true
			ErrorDialog.present(self, "归档可能不完整，当前窗口仍可查看本次记录。")
			return

func _matches(entry: Dictionary) -> bool:
	return _filters_match(entry) and _search_matches(entry)


func _filters_match(entry: Dictionary) -> bool:
	return _selected_matches(_category, entry.get("category", "info")) \
		and _selected_matches(_level, entry.get("level", "")) \
		and _selected_matches(_module, entry.get("module", "")) \
		and _selected_matches(_origin, entry.get("origin", "unknown"))


func _selected_matches(control: Node, value: Variant) -> bool:
	var selected: Variant = control.get_selected_id()
	return selected == "all" or value == selected


func _search_matches(entry: Dictionary) -> bool:
	var needle := _search.text.strip_edges().to_lower()
	if needle.is_empty():
		return true
	var haystack := "%s %s %s %s %s %s" % [entry.get("event", ""), entry.get("message", ""), entry.get("detail", ""),
		entry.get("code", ""), entry.get("module", ""), entry.get("category", "")]
	if entry.get("data") is Dictionary:
		haystack += " " + JSON.stringify(entry.data)
	return haystack.to_lower().contains(needle)

func _append(entry: Dictionary) -> void:
	_text.push_color(get_theme_color(entry.level, "LogEntry"))
	var metrics := entry.duplicate()
	for key in ["time","level","module","category","message","event","detail","stack","data"]:
		metrics.erase(key)
	var category: String = entry.get("category", "info")
	var category_label: String = Schema.CATEGORY_LABELS.get(category, category)
	var origin_label: String = Schema.ORIGIN_LABELS.get(entry.get("origin", "unknown"), "未知")
	var suffix := ""
	var detail := str(entry.get("detail", ""))
	if not detail.is_empty():
		suffix += " | " + (detail.left(157) + "..." if detail.length() > 160 else detail)
	var stack: Variant = entry.get("stack", [])
	if stack is Array and not stack.is_empty():
		suffix += " | stack:%d" % stack.size()
	_text.add_text("%s [%s] [%s] [%s] [%s] %s · %s%s %s\n" % [entry.time,entry.level,category_label,origin_label,entry.module,entry.message,entry.event,suffix,JSON.stringify(metrics)])
	_text.pop()

func _exit_tree() -> void:
	files.cancel()
