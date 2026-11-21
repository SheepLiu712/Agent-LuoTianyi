extends Button
@export var window_system: Resource = preload("res://src/platform/window_system.gd").new()
## 共享的稳定 ID 选择器/动作菜单；弹层细节不对外暴露。
signal activated(id: String)
const ItemScene = preload("res://scenes/ui/components/dropdown_item.tscn")
const SeparatorScene = preload("res://scenes/ui/components/dropdown_separator.tscn")
const DEFAULT_VARIATION := &"DropdownItem"
const SELECTED_VARIATION := &"DropdownItemSelected"
@export var show_selected_label := true
@export var placeholder := ""
var action_menu := false:
	set(value):
		action_menu = value
		custom_minimum_size.x = 90 if value else 140
var _items: Array = []
var _selected := ""
@onready var _popup: PopupPanel = %Menu
@onready var _scroll: ScrollContainer = %Scroll
@onready var _rows: VBoxContainer = %Rows
var _buttons: Array[Button] = []
var _focus_index := -1
var _owner_geometry := Rect2i()
var _trigger: RefCounted
var _pointer_interaction := false
var _pointer_double_click := false
var _focus_visible := true
var _hidden_focus_style: StyleBoxEmpty

func _ready() -> void:
	get_window().gui_embed_subwindows = true
	_popup.window_input.connect(_key_input)
	_popup.visibility_changed.connect(_sync_open_state)
	_trigger = preload("res://src/ui/popup_trigger.gd").new(self,_popup)
	_hidden_focus_style = StyleBoxEmpty.new()
	_hidden_focus_style.content_margin_left = 12
	_hidden_focus_style.content_margin_top = 8
	_hidden_focus_style.content_margin_right = 12
	_hidden_focus_style.content_margin_bottom = 8
	gui_input.connect(_on_trigger_input)
	focus_entered.connect(_on_focus_entered)
	focus_exited.connect(_on_focus_exited)
	pressed.connect(_on_pressed)
	_build()

func set_items(items: Array) -> Error:
	if not _valid_items(items): return ERR_INVALID_PARAMETER
	_items = items.duplicate(true)
	if not _available(_selected):
		_selected = ""
		for item in _items:
			if not item.get("separator",false) and not item.get("disabled",false):
				_selected = item.id
				break
	_caption()
	if is_node_ready(): _build()
	return OK
func get_items() -> Array:
	return _items.duplicate(true)

func set_selected_id(id: String) -> bool:
	if not _available(id): return false
	_selected = id
	_caption()
	if is_menu_open(): _focus_menu_items()
	return true

func get_selected_id() -> String:
	return _selected

func clear_selection() -> void:
	_selected = ""
	_caption()

func set_item_enabled(id: String, enabled: bool) -> void:
	var items := get_items()
	for item in items:
		if item.get("id","") == id: item.disabled = not enabled
	set_items(items)

func _available(id: String) -> bool:
	return _items.any(func(item): return item.get("id","") == id and not item.get("separator",false) and not item.get("disabled",false))

func _caption() -> void:
	if action_menu or not show_selected_label: return
	text = ""
	if _selected.is_empty() and not placeholder.is_empty():
		text = placeholder + "  ▾"
		return
	for item in _items:
		if item.get("id","") == _selected:
			text = item.label + "  ▾"

func _build() -> void:
	close_menu()
	for child in _rows.get_children():
		_rows.remove_child(child)
		child.queue_free()
	_buttons.clear()
	for item in _items:
		if item.get("separator",false):
			_rows.add_child(SeparatorScene.instantiate())
			continue
		var row = ItemScene.instantiate()
		row.setup(item)
		row.gui_input.connect(_key_input)
		row.pressed.connect(func(): _activate(item.id))
		_rows.add_child(row)
		_buttons.append(row)

func open_menu() -> void:
	if disabled or not is_node_ready() or _buttons.is_empty():
		set_pressed_no_signal(false)
		return
	var owner := get_window()
	_owner_geometry = window_system.geometry(owner)
	# 嵌入式弹层在桌面与移动端都使用所属视口的逻辑坐标。
	var available: Vector2 = owner.get_visible_rect().size
	var transform := get_global_transform_with_canvas()
	var origin := Vector2i(transform * Vector2.ZERO)
	var bottom := Vector2i(transform * Vector2(0,size.y))
	var panel: StyleBoxFlat = _popup.get_theme_stylebox("panel")
	var shadow := panel.shadow_size + ceili(maxf(absf(panel.shadow_offset.x),absf(panel.shadow_offset.y)))
	var width := maxi(int(size.x), 230)
	for row in _buttons: width = maxi(width, int(row.get_combined_minimum_size().x + 32))
	width = mini(width, maxi(1, int(available.x) - shadow * 2))
	var height := mini(mini(_buttons.size()*36 + 24, 420), maxi(1, int(available.y) - shadow * 2))
	var y := bottom.y
	if y + height + shadow > available.y: y = origin.y - height
	y = clampi(y, shadow, maxi(shadow, int(available.y) - height - shadow))
	_popup.content_scale_mode = Window.CONTENT_SCALE_MODE_CANVAS_ITEMS
	_popup.content_scale_size = Vector2i.ZERO
	_popup.content_scale_factor = 1.0
	_set_focus_visible(false)
	_popup.popup(Rect2i(Vector2i(clampi(origin.x, shadow, maxi(shadow, int(available.x) - width - shadow)), y), Vector2i(width,height)))
	_focus_menu_items()
func _label(id: String) -> String:
	for item in _items:
		if item.get("id","") == id: return item.label
	return ""

func close_menu() -> void:
	if _popup.visible:
		_popup.hide()
	set_pressed_no_signal(false)
	_sync_focus_visibility()

func is_menu_open() -> bool:
	return _popup.visible

func _activate(id: String) -> void:
	if disabled or not _available(id): return
	_pointer_double_click = false
	set_selected_id(id)
	close_menu()
	activated.emit(id)

func _key_input(event: InputEvent) -> void:
	if event is InputEventMouseButton:
		_handle_pointer(event)
		return
	if not event is InputEventKey or not event.pressed: return
	_pointer_interaction = false
	if has_focus() and not is_menu_open(): _set_focus_visible(true)
	if not _handle_menu_key(event): return
	_popup.set_input_as_handled()


func _handle_pointer(event: InputEvent) -> void:
	var mouse := event as InputEventMouseButton
	if mouse.pressed:
		_pointer_interaction = true
		_pointer_double_click = mouse.double_click


func _handle_menu_key(event: InputEvent) -> bool:
	var key := event as InputEventKey
	match key.keycode:
		KEY_ESCAPE: close_menu()
		KEY_ENTER,KEY_KP_ENTER:
			if _focus_index >= 0: _activate(_buttons[_focus_index].get_meta("id"))
		KEY_DOWN,KEY_UP:
			_move_focus(1 if key.keycode == KEY_DOWN else -1)
		_: return false
	return true


func _move_focus(direction: int) -> void:
	for step in _buttons.size():
		_focus_index = posmod(_focus_index+direction,_buttons.size())
		if not _buttons[_focus_index].disabled:
			_buttons[_focus_index].grab_focus()
			_scroll.ensure_control_visible(_buttons[_focus_index])
			break

func _process(_delta: float) -> void:
	if not is_menu_open(): return
	var owner := get_window()
	if not is_visible_in_tree() or disabled or window_system.minimized(owner) or window_system.geometry(owner) != _owner_geometry:
		close_menu()

func _valid_items(items: Array) -> bool:
	var ids := {}
	for item in items:
		if not item is Dictionary: return false
		if item.get("separator",false): continue
		if not item.get("id") is String or item.id.is_empty() or not item.get("label") is String or ids.has(item.id):
			return false
		ids[item.id] = true
	return true

func _focus_menu_items() -> void:
	_focus_index = -1
	for index in _buttons.size():
		var row := _buttons[index]
		var selected: bool = not action_menu and row.get_meta("id") == _selected
		row.theme_type_variation = SELECTED_VARIATION if selected else DEFAULT_VARIATION
		row.text = ("✓  " if selected else "    ") + _label(row.get_meta("id"))
		if selected: _focus_index = index
	if _focus_index >= 0: _buttons[_focus_index].grab_focus()

func _sync_open_state() -> void:
	if is_node_ready():
		set_pressed_no_signal(_popup.visible)
		_sync_focus_visibility()

func _on_pressed() -> void:
	var double_click := _pointer_double_click
	_pointer_double_click = false
	if double_click:
		set_pressed_no_signal(false)
		_sync_focus_visibility()
		return
	if _trigger.should_open():
		open_menu()
	else:
		close_menu()

func _on_trigger_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed:
		_pointer_interaction = true
		_pointer_double_click = event.double_click
		_set_focus_visible(false)
	elif event is InputEventKey and event.pressed:
		_pointer_interaction = false
		if not is_menu_open(): _set_focus_visible(true)

func _on_focus_entered() -> void:
	_sync_focus_visibility()

func _on_focus_exited() -> void:
	if not is_menu_open(): _pointer_interaction = false
	_set_focus_visible(true)

func _sync_focus_visibility() -> void:
	_set_focus_visible(has_focus() and not is_menu_open() and not _pointer_interaction)

func _set_focus_visible(value: bool) -> void:
	if value == _focus_visible: return
	_focus_visible = value
	if value:
		remove_theme_stylebox_override("focus")
	else:
		add_theme_stylebox_override("focus", _hidden_focus_style)
