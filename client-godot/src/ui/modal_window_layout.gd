extends RefCounted
## Deterministic layout and shadow-gutter placement for embedded & floating modal dialogs.

const PREFERRED_SIZE := Vector2i(580, 240)
const MINIMUM_SIZE := Vector2i(360, 200)
const SAFE_MARGIN := 32
const DIALOG_GUTTER := 24


static func present(
	dialog: Window,
	panel: Control,
	content: Control = null,
	min_content_height: int = MINIMUM_SIZE.y,
	preferred_size: Vector2i = PREFERRED_SIZE
) -> void:
	if dialog == null or panel == null:
		return
	_inset_panel(panel)
	var host_size := _host_size(dialog)
	var max_width := maxi(1, host_size.x - SAFE_MARGIN * 2)
	var max_height := maxi(1, host_size.y - SAFE_MARGIN * 2)
	var min_width := MINIMUM_SIZE.x + DIALOG_GUTTER * 2
	var min_height := min_content_height + DIALOG_GUTTER * 2
	dialog.min_size = Vector2i(mini(min_width, max_width), mini(min_height, max_height))
	var width := clampi(preferred_size.x + DIALOG_GUTTER * 2, mini(min_width, max_width), max_width)
	var height := clampi(preferred_size.y + DIALOG_GUTTER * 2, mini(min_height, max_height), max_height)
	dialog.show()
	dialog.size = Vector2i(width, height)
	_recenter(dialog)
	if content != null:
		content.reset_size()
	if dialog.has_method("_refine_modal_height"):
		dialog.call_deferred("_refine_modal_height")


static func refine_height(
	dialog: Window,
	panel: Control,
	content: Control = null,
	min_content_height: int = MINIMUM_SIZE.y
) -> void:
	if dialog == null or panel == null or not dialog.visible:
		return
	_inset_panel(panel)
	var host_size := _host_size(dialog)
	var max_height := maxi(1, host_size.y - SAFE_MARGIN * 2)
	var needed := _compute_needed_height(panel, content)
	var min_height := min_content_height + DIALOG_GUTTER * 2
	var height := clampi(needed, mini(min_height, max_height), max_height)
	if dialog.size.y != height:
		dialog.size.y = height
		_recenter(dialog)


static func _compute_needed_height(panel: Control, content: Control) -> int:
	var panel_min := ceili(panel.get_combined_minimum_size().y)
	if content == null:
		return panel_min + DIALOG_GUTTER * 2
	var scroll := content.get_parent() as ScrollContainer
	if scroll != null:
		scroll.scroll_vertical = 0
		# ScrollContainer does not include its child content height in minimum size; add a 2px safety cushion so tiny rounding differences never spawn a scrollbar.
		return panel_min + ceili(content.get_combined_minimum_size().y) + DIALOG_GUTTER * 2 + 2
	return panel_min + DIALOG_GUTTER * 2


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
	if host.size.x <= 0 or host.size.y <= 0:
		return Vector2i(800, 600)
	return host.size
