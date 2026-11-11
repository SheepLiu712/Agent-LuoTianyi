extends SceneTree

const DROPDOWN_SCENE := "res://scenes/ui/unified_dropdown.tscn"
const SETTINGS_STYLE := preload("res://src/ui/settings_style.gd")
const SELECTOR_SCENES := [
	"res://scenes/ui/log_window.tscn",
	"res://scenes/ui/preferences_page.tscn",
	"res://scenes/ui/style_page.tscn",
	"res://scenes/ui/model_purpose_card.tscn",
	"res://scenes/preview/chat_preview.tscn",
]
var failures: Array[String] = []

func _initialize() -> void:
	run.call_deferred()

func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)

func run() -> void:
	_check_selector_scenes_use_the_shared_control()
	_check_theme_contract()
	await _check_trigger_and_selected_rows()
	print("Dropdown consistency: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

## 选择型下拉必须由同一个场景承载；原生 OptionButton 不再散落在产品界面。
func _check_selector_scenes_use_the_shared_control() -> void:
	for path in SELECTOR_SCENES:
		var source := FileAccess.get_file_as_string(path)
		check(not source.contains('type="OptionButton"'), "no native selector remains: " + path)
	for path in ["res://scenes/ui/log_window.tscn", "res://scenes/ui/preferences_page.tscn",
			"res://scenes/ui/style_page.tscn", "res://scenes/ui/model_purpose_card.tscn",
			"res://scenes/preview/chat_preview.tscn"]:
		check(FileAccess.get_file_as_string(path).contains(DROPDOWN_SCENE), "selector scene reuses the shared dropdown: " + path)
	var account := FileAccess.get_file_as_string("res://scenes/ui/account_view.tscn")
	check(account.count('theme_type_variation = &"DropdownPopup"') >= 2, "account action and history popups reuse the dropdown surface")
	check(account.count("transparent_bg = true") >= 2, "account popups keep transparent rounded corners")

func _check_theme_contract() -> void:
	var theme: Theme = load("res://theme/app_theme.tres")
	check(theme.get_type_variation_base("DropdownTrigger") == &"Button", "trigger keeps Button behavior")
	_check_trigger_states(theme)
	_check_popup_and_rows(theme)


func _check_trigger_states(theme: Theme) -> void:
	for state in ["normal", "hover", "pressed", "disabled", "focus"]:
		check(theme.has_stylebox(state, "DropdownTrigger"), "trigger declares " + state)
	var normal := theme.get_stylebox("normal", "DropdownTrigger") as StyleBoxFlat
	var hover := theme.get_stylebox("hover", "DropdownTrigger") as StyleBoxFlat
	var pressed := theme.get_stylebox("pressed", "DropdownTrigger") as StyleBoxFlat
	var focus := theme.get_stylebox("focus", "DropdownTrigger") as StyleBoxFlat
	check(normal != null and normal.bg_color.is_equal_approx(Color("eef6fb")), "trigger uses the canonical pale-blue surface")
	check(normal != null and normal.corner_radius_top_left == 8, "trigger uses the canonical radius")
	check(hover != null and not hover.bg_color.is_equal_approx(normal.bg_color), "trigger hover is visible")
	check(pressed != null and not pressed.bg_color.is_equal_approx(hover.bg_color), "trigger pressed is distinct")
	check(focus != null and focus.border_color.is_equal_approx(Color("66ccff")), "trigger keyboard focus uses cyan")


func _check_popup_and_rows(theme: Theme) -> void:
	var popup := theme.get_stylebox("panel", "DropdownPopup") as StyleBoxFlat
	check(popup != null and popup.shadow_size > 0 and popup.corner_radius_top_left == 8, "popup surface stays elevated and rounded")
	var item := theme.get_stylebox("normal", "DropdownItem") as StyleBoxFlat
	var selected := theme.get_stylebox("normal", "DropdownItemSelected") as StyleBoxFlat
	check(item != null and selected != null and selected.border_width_left == 1, "selected row has its own outlined surface")
	check(item != null and selected != null and not item.bg_color.is_equal_approx(selected.bg_color), "selected row is distinguishable")

func _check_trigger_and_selected_rows() -> void:
	var dropdown = load(DROPDOWN_SCENE).instantiate()
	root.add_child(dropdown)
	dropdown.set_items([{"id":"a","label":"全部类别"},{"id":"b","label":"错误"}])
	await process_frame
	check(dropdown.theme_type_variation == &"DropdownTrigger", "shared scene starts on the trigger variation")
	SETTINGS_STYLE.apply(dropdown)
	check(dropdown.theme_type_variation == &"DropdownTrigger", "settings styling never overwrites the dropdown trigger")
	dropdown.open_menu()
	await process_frame
	var popup: Window = dropdown.find_children("*", "Window", true, false)[0]
	check(popup.get_theme_stylebox("panel") == dropdown.get_theme_stylebox("panel", "DropdownPopup"), "popup uses the shared elevated surface")
	var rows = dropdown.get_node("%Rows").get_children()
	check(rows.size() == 2, "shared dropdown builds one row per item")
	check(rows[0].theme_type_variation == &"DropdownItemSelected", "selected row uses the selected variation")
	check(rows[0].text.begins_with("✓"), "selected row shows a checkmark")
	check(rows[1].theme_type_variation == &"DropdownItem", "other rows keep the normal variation")
	dropdown.close_menu()
	await process_frame
	check(not dropdown.button_pressed, "closing the popup clears the pressed trigger state")
	dropdown.queue_free()
	await process_frame
