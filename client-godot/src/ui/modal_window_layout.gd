extends RefCounted

const PREFERRED_SIZE := Vector2i(580, 240)
const MINIMUM_SIZE := Vector2i(360, 200)
const SAFE_MARGIN := 32
## 面板四边的透明留白：圆角阴影画在这里面，不会被窗口边界裁成方角。
const DIALOG_GUTTER := 24


static func present(dialog: Window, panel: Control, _content: Control = null) -> void:
	if dialog == null or panel == null:
		return
	_inset_panel(panel)
	var host_size := _host_size(dialog)
	var max_width := maxi(1, host_size.x - SAFE_MARGIN * 2)
	var max_height := maxi(1, host_size.y - SAFE_MARGIN * 2)
	var min_width := MINIMUM_SIZE.x + DIALOG_GUTTER * 2
	var min_height := MINIMUM_SIZE.y + DIALOG_GUTTER * 2
	dialog.min_size = Vector2i(mini(min_width, max_width), mini(min_height, max_height))
	var width := clampi(PREFERRED_SIZE.x + DIALOG_GUTTER * 2, mini(min_width, max_width), max_width)
	var height := clampi(PREFERRED_SIZE.y + DIALOG_GUTTER * 2, mini(min_height, max_height), max_height)
	# 自己控制尺寸与居中：popup_centered 会在无屏幕的 headless 环境产生负坐标。
	dialog.show()
	dialog.size = Vector2i(width, height)
	_recenter(dialog)
	dialog.call_deferred("_refine_modal_height")


static func refine_height(dialog: Window, panel: Control, content: Control = null) -> void:
	if dialog == null or panel == null or not dialog.visible:
		return
	_inset_panel(panel)
	var host_size := _host_size(dialog)
	var max_height := maxi(1, host_size.y - SAFE_MARGIN * 2)
	var needed := ceili(panel.get_combined_minimum_size().y) + DIALOG_GUTTER * 2
	if content != null:
		# ScrollContainer 的竖向最小尺寸不包含正文，正文高度必须单独加回来。
		needed += ceili(content.get_combined_minimum_size().y)
	var min_height := MINIMUM_SIZE.y + DIALOG_GUTTER * 2
	var height := clampi(needed, mini(min_height, max_height), max_height)
	if dialog.size.y == height:
		return
	dialog.size.y = height
	_recenter(dialog)


static func _inset_panel(panel: Control) -> void:
	panel.offset_left = DIALOG_GUTTER
	panel.offset_top = DIALOG_GUTTER
	panel.offset_right = -DIALOG_GUTTER
	panel.offset_bottom = -DIALOG_GUTTER


static func _recenter(dialog: Window) -> void:
	if dialog.get_parent() == null:
		return
	var host := dialog.get_parent().get_window()
	if host == null or host == dialog:
		return
	var origin := Vector2i.ZERO if dialog.is_embedded() else host.position
	dialog.position = origin + (host.size - dialog.size) / 2


static func _host_size(dialog: Window) -> Vector2i:
	if dialog.get_parent() == null:
		return Vector2i(800, 600)
	var host := dialog.get_parent().get_window()
	if host == null or host == dialog:
		return Vector2i(800, 600)
	# SceneTree 脚本里根窗口可能还没有真实尺寸；用固定宿主避免负坐标弹窗。
	if host.size.x <= 0 or host.size.y <= 0:
		return Vector2i(800, 600)
	return host.size
