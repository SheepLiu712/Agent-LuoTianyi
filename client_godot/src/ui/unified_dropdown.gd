extends Button
## Shared stable-ID selector / action menu. Popup details remain private.
signal activated(id: String)
const Item = preload("res://scenes/ui/dropdown_item.tscn")
const SeparatorScene = preload("res://scenes/ui/dropdown_separator.tscn")
@export var show_selected_label := true
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

func _ready() -> void:
	get_window().gui_embed_subwindows = true
	_popup.window_input.connect(_key_input)
	_trigger = preload("res://src/ui/popup_trigger.gd").new(self,_popup)
	pressed.connect(func():
		if _trigger.should_open(): open_menu())
	_build()

func set_items(items: Array) -> Error:
	var ids := {}
	for item in items:
		if not item is Dictionary: return ERR_INVALID_PARAMETER
		if item.get("separator",false): continue
		if not item.get("id") is String or item.id.is_empty() or not item.get("label") is String or ids.has(item.id):
			return ERR_INVALID_PARAMETER
		ids[item.id] = true
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
	return true

func get_selected_id() -> String:
	return _selected

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
		var row = Item.instantiate()
		row.setup(item)
		row.gui_input.connect(_key_input)
		row.pressed.connect(func(): _activate(item.id))
		_rows.add_child(row)
		_buttons.append(row)

func open_menu() -> void:
	if disabled or not is_node_ready() or _buttons.is_empty(): return
	var owner := get_window()
	_owner_geometry = Rect2i(owner.position,owner.size)
	# Embedded popups use their owning viewport's logical coordinates on desktop and mobile.
	var available: Vector2 = owner.get_visible_rect().size
	var transform := get_global_transform_with_canvas()
	var origin := Vector2i(transform * Vector2.ZERO)
	var bottom := Vector2i(transform * Vector2(0,size.y))
	var shadow: int = _popup.get_theme_stylebox("panel").shadow_size
	var width := maxi(int(size.x), 230)
	for row in _buttons: width = maxi(width, int(row.get_combined_minimum_size().x + 32))
	width = mini(width, maxi(1, int(available.x) - shadow * 2))
	var height := mini(mini(_buttons.size()*42 + 24, 420), maxi(1, int(available.y) - shadow * 2))
	var y := bottom.y
	if y + height + shadow > available.y: y = origin.y - height
	y = clampi(y, shadow, maxi(shadow, int(available.y) - height - shadow))
	_popup.content_scale_mode = Window.CONTENT_SCALE_MODE_CANVAS_ITEMS
	_popup.content_scale_size = Vector2i.ZERO
	_popup.content_scale_factor = 1.0
	_popup.popup(Rect2i(Vector2i(clampi(origin.x, shadow, maxi(shadow, int(available.x) - width - shadow)), y), Vector2i(width,height)))
	_focus_index = -1
	for index in _buttons.size():
		var row := _buttons[index]
		row.text = ("✓  " if not action_menu and row.get_meta("id") == _selected else "    ") + _label(row.get_meta("id"))
		for state in ["font_color","font_focus_color","font_hover_color","font_pressed_color"]:
			row.add_theme_color_override(state,get_theme_color("font_selected_color", "DropdownItem") if not action_menu and row.get_meta("id") == _selected else get_theme_color("font_color", "DropdownItem"))
		if row.get_meta("id") == _selected: _focus_index = index
	if _focus_index >= 0: _buttons[_focus_index].grab_focus()

func _label(id: String) -> String:
	for item in _items:
		if item.get("id","") == id: return item.label
	return ""

func close_menu() -> void:
	_popup.hide()

func is_menu_open() -> bool:
	return _popup.visible

func _activate(id: String) -> void:
	if disabled or not _available(id): return
	set_selected_id(id)
	close_menu()
	activated.emit(id)

func _key_input(event: InputEvent) -> void:
	if not event is InputEventKey or not event.pressed: return
	match event.keycode:
		KEY_ESCAPE: close_menu()
		KEY_ENTER,KEY_KP_ENTER:
			if _focus_index >= 0: _activate(_buttons[_focus_index].get_meta("id"))
		KEY_DOWN,KEY_UP:
			var direction := 1 if event.keycode == KEY_DOWN else -1
			for step in _buttons.size():
				_focus_index = posmod(_focus_index+direction,_buttons.size())
				if not _buttons[_focus_index].disabled:
					_buttons[_focus_index].grab_focus()
					_scroll.ensure_control_visible(_buttons[_focus_index])
					break
		_: return
	_popup.set_input_as_handled()

func _process(_delta: float) -> void:
	if not is_menu_open(): return
	var owner := get_window()
	if not is_visible_in_tree() or disabled or owner.mode == Window.MODE_MINIMIZED or Rect2i(owner.position,owner.size) != _owner_geometry:
		close_menu()
