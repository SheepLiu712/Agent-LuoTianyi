extends SceneTree

const THEME_PATH := "res://theme/app_theme.tres"
const INK := Color("304553")
const ACCENT := Color("66ccff")
var failures: Array[String] = []

func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)

func _initialize() -> void:
	run.call_deferred()


func _check_settings_variations(theme: Theme) -> void:
	check(theme.get_type_variation_base("PrimaryButton") == &"Button", "primary actions share button behavior")
	var primary := flat_style(theme, "PrimaryButton", "normal")
	if primary != null:
		check(primary.bg_color.is_equal_approx(ACCENT), "primary action uses Tianyi blue")
	for entry in [["SettingsButton", "Button"], ["SettingsPrimaryButton", "Button"], ["SettingsDangerButton", "Button"],
			["SettingsLineEdit", "LineEdit"], ["SettingsTextEdit", "TextEdit"], ["SettingsCheckBox", "CheckBox"],
			["SettingsCard", "PanelContainer"], ["SettingsDialogSurface", "PanelContainer"], ["SettingsToast", "PanelContainer"],
			["SettingsPageTitle", "Label"], ["SettingsCardTitle", "Label"], ["SettingsFieldLabel", "Label"],
			["SettingsHelpText", "Label"], ["SettingsDialogTitle", "Label"], ["ChatIconButton", "Button"]]:
		check(theme.get_type_variation_base(entry[0]) == StringName(entry[1]), "settings variation keeps base control: " + entry[0])
	for state in ["normal", "hover", "pressed", "disabled", "focus"]:
		check(theme.has_stylebox(state, "ChatIconButton"), "chat icon declares hover/focus state: " + state)
	var settings_primary := flat_style(theme, "SettingsPrimaryButton", "normal")
	if settings_primary != null:
		check(settings_primary.bg_color.is_equal_approx(Color(0, 0.780392, 0.941176)), "settings primary uses ring cyan")
	var settings_dialog := flat_style(theme, "SettingsDialogSurface", "panel")
	if settings_dialog != null:
		check(settings_dialog.shadow_size > 0, "settings dialogs always keep elevation")
		check(settings_dialog.border_width_left == 0 and settings_dialog.border_width_top == 0 and settings_dialog.border_width_right == 0 and settings_dialog.border_width_bottom == 0, "settings dialogs have no outer border")


func _check_toggle_states(theme: Theme) -> void:
	check_surface(theme, "CheckBox", "hover_pressed", 8)
	var selected := flat_style(theme, "CheckBox", "pressed")
	if selected != null:
		check(selected.bg_color.is_equal_approx(Color("d9f1ff")), "selected toggle uses light blue")
	for state in ["font_pressed_color", "font_hover_color", "font_hover_pressed_color", "font_focus_color"]:
		check(theme.get_color(state, "CheckBox").is_equal_approx(INK), "legible toggle text: " + state)


func _check_dynamic_selection(theme: Theme) -> void:
	var dynamic_normal := flat_style(theme, "DynamicsPost", "normal")
	var dynamic_selected := flat_style(theme, "DynamicsPost", "selected")
	if dynamic_normal != null and dynamic_selected != null:
		check(not dynamic_normal.bg_color.is_equal_approx(dynamic_selected.bg_color), "selected dynamic is distinguishable")


func run() -> void:
	var theme: Theme = load(THEME_PATH)
	check(theme != null, "shared theme loads")
	if theme == null:
		quit(1)
		return
	check(ProjectSettings.get_setting("gui/theme/custom", "") == THEME_PATH, "project uses app theme")
	_check_readable_font_resource_and_15px_default(theme)
	_check_settings_variations(theme)
	for kind in ["Label", "Button", "LineEdit", "TextEdit", "CheckBox", "RichTextLabel"]:
		check(theme.get_color("font_color", kind).is_equal_approx(INK), "dark body text: " + kind)
	_check_selection_colors(theme)
	_check_button_states(theme)
	_check_focus_and_input(theme)
	_check_checkbox_focus_geometry(theme)
	_check_toggle_states(theme)
	check_surface(theme, "AppSurface", "panel", 8)
	_check_dynamic_selection(theme)
	check(not theme.get_color("delivery_failed", "MessageBubble").is_equal_approx(theme.get_color("delivery_status", "MessageBubble")), "delivery errors differ from ordinary status")
	_check_log_severity_remains_distinguishable(theme)
	_check_slider_icons(theme)
	_check_shared_control_states(theme)
	_check_surface_variations(theme)
	_check_styles_are_centralised()
	check(load("res://assets/ui/round_avatar.gdshader") is Shader, "avatar material resource loads")
	_check_tianyi_avatar_keeps_transparent_padding()
	print("Theme contract: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


## 聊天头像是圆形遮罩：满幅不透明图会被裁成方头，必须留透明边。
func _check_tianyi_avatar_keeps_transparent_padding() -> void:
	var icon := load("res://assets/ui/tianyi_icon.png") as Texture2D
	check(icon != null, "Tianyi avatar loads")
	if icon == null:
		return
	check(icon.get_size() == Vector2(256, 256), "Tianyi avatar keeps the 256px canvas")
	var pixels := icon.get_image()
	check(pixels != null and pixels.get_pixel(0, 0).a < .01, "Tianyi avatar leaves a transparent corner for the round mask")


## 同类控件同一状态共用一份样式：改一处即全生效，避免品牌色各自漂移。
func _check_shared_control_states(theme: Theme) -> void:
	for state in ["normal", "hover", "pressed", "disabled", "focus"]:
		var shared := theme.get_stylebox(state, "Button")
		for kind in ["MenuButton", "OptionButton"]:
			check(theme.get_stylebox(state, kind) == shared, "shared control state: " + kind + "/" + state)


## 界面底板统一由主题类型提供；场景只保留确有局部语义的样式。
func _check_surface_variations(theme: Theme) -> void:
	for entry in [["ChatSurface", "panel", 8], ["ChatComposer", "panel", 8], ["DynamicsSurface", "panel", 8],
			["DynamicsDetailSurface", "panel", 8], ["DropdownItem", "normal", 6], ["DropdownItem", "hover", 6],
			["DynamicInput", "normal", 8], ["MessageBubbleOwn", "panel", 8], ["MessageBubbleOther", "panel", 8],
			["MessageTimeChip", "panel", 8], ["TerminalPanel", "panel", 0], ["ImageEntry", "focus", 8],
			["ChatIconButton", "hover", 8], ["SettingsToast", "panel", 8]]:
		var style := flat_style(theme, entry[0], entry[1])
		if style != null:
			check(maxi(style.corner_radius_top_left, style.corner_radius_bottom_left) == entry[2], "surface radius: " + entry[0])
		check(theme.get_type_variation_base(entry[0]) != &"", "surface keeps a base control: " + entry[0])


func _check_styles_are_centralised() -> void:
	var source := FileAccess.get_file_as_string(THEME_PATH)
	check(not source.is_empty(), "theme source readable")
	check(not source.contains('id="StyleBoxFlat_'), "no anonymous stylebox in the theme")
	for path in ["res://scenes/ui/message_bubble.tscn", "res://scenes/ui/chat_view.tscn", "res://scenes/ui/dynamics_window.tscn",
			"res://scenes/ui/dynamic_detail.tscn", "res://scenes/ui/dropdown_item.tscn", "res://scenes/ui/log_window.tscn"]:
		check(not FileAccess.get_file_as_string(path).contains("StyleBoxFlat"), "shared surfaces come from the theme: " + path)

func flat_style(theme: Theme, kind: String, state: String) -> StyleBoxFlat:
	if not theme.has_stylebox(state, kind):
		check(false, "authored style: " + kind + "/" + state)
		return null
	var style := theme.get_stylebox(state, kind)
	check(style is StyleBoxFlat, "Godot rounded surface: " + kind + "/" + state)
	return style as StyleBoxFlat

func check_surface(theme: Theme, kind: String, state: String, radius: int) -> StyleBoxFlat:
	var style := flat_style(theme, kind, state)
	if style != null:
		check(style.bg_color.a == 1, "solid surface: " + kind + "/" + state)
		check(style.corner_radius_top_left == radius and style.corner_radius_top_right == radius and style.corner_radius_bottom_left == radius and style.corner_radius_bottom_right == radius, "rounded corners: " + kind + "/" + state)
	return style

func _check_button_states(theme: Theme) -> void:
	for kind in ["Button", "OptionButton", "MenuButton", "CheckBox"]:
		var normal := check_surface(theme, kind, "normal", 8)
		for state in ["hover", "pressed", "disabled"]:
			var alternate := check_surface(theme, kind, state, 8)
			if normal != null and alternate != null:
				check(not alternate.bg_color.is_equal_approx(normal.bg_color), "distinct interaction state: " + kind + "/" + state)
		check(not theme.get_color("font_disabled_color", kind).is_equal_approx(theme.get_color("font_color", kind)), "disabled text is distinguishable: " + kind)

func _check_focus_and_input(theme: Theme) -> void:
	for kind in ["Button", "OptionButton", "MenuButton", "LineEdit", "TextEdit", "HSlider", "CheckBox"]:
		var focus: StyleBox = theme.get_stylebox("focus", kind)
		check(focus is StyleBoxFlat, "explicit focus outline: " + kind)
		if focus is StyleBoxFlat:
			_check_check_focus_and_input_result(focus, kind)
			check(not focus.draw_center or focus.bg_color.a == 0, "focus does not obscure text: " + kind)
			check(focus.border_color.is_equal_approx(Color("168ac2") if kind == "CheckBox" else ACCENT), "focus accent: " + kind)
	for kind in ["LineEdit", "TextEdit"]:
		for state in ["normal", "read_only"]:
			var surface := check_surface(theme, kind, state, 8)
			if surface != null: check(surface.bg_color.get_luminance() > .85, "clear light input surface: " + kind + "/" + state)

## 勾选框与文字的间距必须由同一组内容边距决定，聚焦态不能参与布局偏移。
func _check_checkbox_focus_geometry(theme: Theme) -> void:
	for kind in ["CheckBox", "SettingsCheckBox"]:
		var normal := flat_style(theme, kind, "normal")
		var focus := flat_style(theme, kind, "focus")
		if normal == null or focus == null:
			continue
		check(
			focus.content_margin_left == normal.content_margin_left
			and focus.content_margin_top == normal.content_margin_top
			and focus.content_margin_right == normal.content_margin_right
			and focus.content_margin_bottom == normal.content_margin_bottom,
			"checkbox focus keeps the normal content margins: " + kind
		)

func _check_slider_icons(theme: Theme) -> void:
	for state in ["grabber", "grabber_highlight", "grabber_disabled"]:
		var icon: Texture2D = theme.get_icon(state, "HSlider")
		check(icon != null, "slider state icon loads: " + state)
		if icon != null:
			var pixels := icon.get_image()
			check(pixels != null and not pixels.is_empty(), "slider icon has pixels: " + state)
			if pixels != null and not pixels.is_empty():
				check(pixels.get_pixel(0, 0).a < .2 and pixels.get_pixelv(pixels.get_size() / 2).a > .8, "slider dot has a visible center and transparent corner: " + state)

func _check_readable_font_resource_and_15px_default(theme: Variant) -> void:
	check(theme.default_font != null and theme.default_font_size == 15, "readable font resource and 15px default")

func _check_log_severity_remains_distinguishable(theme: Variant) -> void:
	check(theme.get_color("ERROR", "LogEntry") != theme.get_color("INFO", "LogEntry") and theme.get_color("WARN", "LogEntry") != theme.get_color("INFO", "LogEntry"), "log severity remains distinguishable")

func _check_check_focus_and_input_result(focus: Variant, kind: Variant) -> void:
	check(focus.border_width_left > 0 and focus.border_width_right > 0 and focus.border_width_top > 0 and focus.border_width_bottom > 0, "focus visible on all edges: " + kind)

func _check_selection_colors(theme: Theme) -> void:
	for kind in ["LineEdit", "TextEdit", "RichTextLabel"]:
		check(theme.get_color("selection_color", kind).is_equal_approx(Color("0078d7")), "system blue text selection: " + kind)
		check(theme.get_color("font_selected_color", kind).is_equal_approx(Color.WHITE), "white selected text: " + kind)
