extends Window
var _logger: RefCounted
@onready var _runs = %RunsDropdown
@onready var _level = %LevelDropdown
@onready var _module = %ModuleDropdown
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

func setup(logger: RefCounted) -> void:
	_logger = logger
	if is_node_ready():
		_initialize()

func _ready() -> void:
	title = "客户端日志 · " + preload("res://src/release_info.gd").title()
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
	_level.set_items([{"id":"all","label":"全部级别"},{"id":"INFO","label":"INFO"},{"id":"WARN","label":"WARN"},{"id":"ERROR","label":"ERROR"}])
	var modules: Array = [{"id":"all","label":"全部模块"}]
	for module in _logger.MODULES:
		modules.append({"id":module,"label":module})
	_module.set_items(modules)
	_level.activated.connect(func(_index): _refresh())
	_module.activated.connect(func(_index): _refresh())
	_search.text_changed.connect(func(_value): _refresh())
	_follow.toggled.connect(func(value):
		_text.scroll_following = value
		if value:
			_text.scroll_to_line(maxi(0,_text.get_line_count()-1)))
	_text.scroll_following = true
	_copy.pressed.connect(func(): DisplayServer.clipboard_set(_text.get_parsed_text()))
	_export.pressed.connect(func():
		_export_id = _selected
		_picker.current_file = "agentluo-diagnostics-" + _selected + ".zip"
		_picker.popup_centered_ratio(.7))
	_picker.file_selected.connect(func(path):
		var error: Error = _logger.export_run(_export_id,path)
		_status.text = "所选启动的完整诊断已导出（未上传）。" if error == OK else "导出失败（%s），请选择尚不存在且可写的文件。" % error)
	close_requested.connect(hide)
	_logger.entry_added.connect(func(entry):
		if visible and _selected == _logger.get_run_id() and _matches(entry):
			_append(entry))
	_logger.write_failed.connect(func(_error): _status.text = "日志写盘失败，当前窗口仍可查看内存记录；归档可能不完整。")
func open() -> void:
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
		options.append({"id":run.id,"label":caption})
	_runs.set_items(options)
	_runs.set_selected_id(_selected)
	_selected = _runs.get_selected_id()
	_refresh()
	show()
	grab_focus()

func _refresh() -> void:
	_text.clear()
	var entries: Array = _logger.read_entries(_selected)
	for entry in entries:
		if _matches(entry):
			_append(entry)
	_status.text = "共 %s 条记录；筛选只影响显示，导出包含整次启动。" % entries.size()
	for run in _logger.list_runs():
		if run.id == _selected and not run.complete:
			_status.text += " 此次归档不完整。"

func _matches(entry: Dictionary) -> bool:
	return (_level.get_selected_id() == "all" or entry.level == _level.get_selected_id()) and (_module.get_selected_id() == "all" or entry.module == _module.get_selected_id()) and (_search.text.is_empty() or JSON.stringify(entry).to_lower().contains(_search.text.to_lower()))

func _append(entry: Dictionary) -> void:
	_text.push_color({"INFO":Color("d6e5ee"),"WARN":Color("ffd58a"),"ERROR":Color("ff8c8c")}[entry.level])
	var metrics := entry.duplicate()
	for key in ["time","level","module","message","event"]:
		metrics.erase(key)
	_text.add_text("%s [%s] [%s] %s · %s %s\n" % [entry.time,entry.level,entry.module,entry.message,entry.event,JSON.stringify(metrics)])
	_text.pop()
