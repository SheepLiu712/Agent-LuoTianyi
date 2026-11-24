extends Control
## 客户端本地外观（扁平/清透）、图标风格（svg/emoji，默认仅启用 svg）与动效偏好设置页。

signal dirty_changed

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
	_sync_ui_style_controls(_ui_style.ui_style, _ui_style.icon_style, _reduced_motion_value(), _default_preview_image_value())
	var style_selected := _on_ui_style_selected.bind("style")
	var icons_selected := _on_ui_style_selected.bind("icons")
	if not %UiStylePresets.activated.is_connected(style_selected):
		%UiStylePresets.activated.connect(style_selected)
	if not %IconStylePresets.activated.is_connected(icons_selected):
		%IconStylePresets.activated.connect(icons_selected)
	if has_node("%ReducedMotion") and not %ReducedMotion.toggled.is_connected(_on_reduced_motion_toggled):
		%ReducedMotion.toggled.connect(_on_reduced_motion_toggled)
	if has_node("%DefaultPreviewImage") and not %DefaultPreviewImage.toggled.is_connected(_on_default_preview_toggled):
		%DefaultPreviewImage.toggled.connect(_on_default_preview_toggled)

func _reduced_motion_value() -> bool:
	return bool(_ui_style.reduced_motion) if _ui_style != null and "reduced_motion" in _ui_style else false

func _default_preview_image_value() -> bool:
	return bool(_ui_style.default_preview_image) if _ui_style != null and "default_preview_image" in _ui_style else true

func _sync_ui_style_controls(style: String, icons: String, reduce_motion: bool = false, preview_image: bool = true) -> void:
	var styles := {"flat": "扁平", "crystal": "清透"}
	var icon_kinds := {"svg": "标准 SVG", "emoji": "趣味 Emoji（实验性）"}
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
	if has_node("%ReducedMotion"):
		%ReducedMotion.set_pressed_no_signal(reduce_motion)
	if has_node("%DefaultPreviewImage"):
		%DefaultPreviewImage.set_pressed_no_signal(preview_image)
	_ui_style_pending = {"style": style, "icons": icons, "reduced_motion": reduce_motion, "default_preview_image": preview_image}

func _on_ui_style_selected(id, field: String) -> void:
	if _ui_style == null:
		return
	_ui_style_pending[field] = id
	if field == "style":
		%UiStylePresets.set_selected_id(id)
	else:
		%IconStylePresets.set_selected_id(id)
	dirty_changed.emit()

func _on_reduced_motion_toggled(pressed: bool) -> void:
	if _ui_style == null:
		return
	_ui_style_pending["reduced_motion"] = pressed
	dirty_changed.emit()

func _on_default_preview_toggled(pressed: bool) -> void:
	if _ui_style == null:
		return
	_ui_style_pending["default_preview_image"] = pressed
	dirty_changed.emit()

func ui_style_dirty() -> bool:
	if _ui_style == null or _ui_style_pending.is_empty():
		return false
	if _ui_style_pending.get("style", "") != _ui_style.ui_style or _ui_style_pending.get("icons", "") != _ui_style.icon_style:
		return true
	if bool(_ui_style_pending.get("reduced_motion", false)) != _reduced_motion_value():
		return true
	return bool(_ui_style_pending.get("default_preview_image", true)) != _default_preview_image_value()


func discard_ui_style() -> void:
	if _ui_style == null:
		return
	_sync_ui_style_controls(_ui_style.ui_style, _ui_style.icon_style, _reduced_motion_value(), _default_preview_image_value())
	dirty_changed.emit()

func save_ui_style() -> Dictionary:
	if _ui_style == null or not ui_style_dirty():
		return {"ok": true, "results": []}
	var error: Error = _ui_style.save_preferences(
		_ui_style_pending.style,
		_ui_style_pending.icons,
		_ui_style_pending.get("reduced_motion", false),
		_ui_style_pending.get("default_preview_image", true)
	)
	var result := {"section":"ui", "id":"界面与动效风格", "ok":error == OK, "code":"OK" if error == OK else "本地保存失败"}
	if error != OK:
		result.message = "风格保存失败，本次仍生效，重启后恢复上次设置。"
	else:
		dirty_changed.emit()
	return {"ok": error == OK, "results": [result]}
