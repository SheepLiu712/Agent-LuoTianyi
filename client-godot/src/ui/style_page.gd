extends Control
## Client-local UI style (flat/crystal) and icon style (svg/emoji) settings page.

var _ui_style: RefCounted
var _ui_style_pending := {}

func _ready() -> void:
	_initialize_ui_style()

func set_ui_style(ui_style: RefCounted) -> void:
	_ui_style = ui_style
	if is_node_ready() and _ui_style != null:
		_initialize_ui_style()

func _initialize_ui_style() -> void:
	if _ui_style == null:
		return
	if not has_node("%UiStylePresets") or not has_node("%IconStylePresets"):
		return
	_sync_ui_style_controls(_ui_style.ui_style, _ui_style.icon_style)
	var style_selected := _on_ui_style_selected.bind("style")
	var icons_selected := _on_ui_style_selected.bind("icons")
	if not %UiStylePresets.activated.is_connected(style_selected):
		%UiStylePresets.activated.connect(style_selected)
	if not %IconStylePresets.activated.is_connected(icons_selected):
		%IconStylePresets.activated.connect(icons_selected)

func _sync_ui_style_controls(style: String, icons: String) -> void:
	var styles := {"flat": "扁平", "crystal": "清透"}
	var icon_kinds := {"svg": "扁平 icon", "emoji": "emoji"}
	var style_opts: Array = []
	for id in styles:
		style_opts.append({"id": id, "label": styles[id]})
	var icon_opts: Array = []
	for id in icon_kinds:
		icon_opts.append({"id": id, "label": icon_kinds[id]})
	%UiStylePresets.set_items(style_opts)
	%IconStylePresets.set_items(icon_opts)
	%UiStylePresets.set_selected_id(style)
	%IconStylePresets.set_selected_id(icons)
	%UiStyleField.text = styles.get(style, styles["flat"])
	%IconStyleField.text = icon_kinds.get(icons, icon_kinds["svg"])
	_ui_style_pending = {"style": style, "icons": icons}

func _on_ui_style_selected(id, field: String) -> void:
	if _ui_style == null:
		return
	_ui_style_pending[field] = id
	var styles := {"flat": "扁平", "crystal": "清透"}
	var icon_kinds := {"svg": "扁平 icon", "emoji": "emoji"}
	if field == "style":
		%UiStyleField.text = styles.get(id, "")
	else:
		%IconStyleField.text = icon_kinds.get(id, "")

func ui_style_dirty() -> bool:
	if _ui_style == null or _ui_style_pending.is_empty():
		return false
	return _ui_style_pending.get("style", "") != _ui_style.ui_style or _ui_style_pending.get("icons", "") != _ui_style.icon_style

func save_ui_style() -> Dictionary:
	if _ui_style == null or not ui_style_dirty():
		return {"ok": true, "results": []}
	var error: Error = _ui_style.save_preferences(_ui_style_pending.style, _ui_style_pending.icons)
	return {"ok": error == OK, "results": [{"section": "ui", "id": "界面与图标风格", "ok": error == OK, "code": "OK" if error == OK else "本地保存失败（%s）" % error}]}
