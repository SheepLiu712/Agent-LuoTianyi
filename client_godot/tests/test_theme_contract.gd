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

func run() -> void:
	var theme: Theme = load(THEME_PATH)
	check(theme != null, "shared theme loads")
	if theme == null:
		quit(1)
		return
	check(ProjectSettings.get_setting("gui/theme/custom", "") == THEME_PATH, "project uses app theme")
	check(theme.default_font != null and theme.default_font_size == 15, "readable font resource and 15px default")
	check(theme.get_type_variation_base("PrimaryButton") == &"Button", "primary actions share button behavior")
	check(theme.get_stylebox("normal", "PrimaryButton").bg_color.is_equal_approx(ACCENT), "primary action uses Tianyi blue")
	for kind in ["Label", "Button", "LineEdit", "TextEdit", "CheckBox", "RichTextLabel"]:
		check(theme.get_color("font_color", kind).is_equal_approx(INK), "dark body text: " + kind)
	for kind in ["Button", "OptionButton", "MenuButton", "CheckBox"]:
		for state in ["normal", "hover", "pressed", "disabled"]:
			check_surface(theme, kind, state, 8)
		var normal: StyleBoxFlat = theme.get_stylebox("normal", kind)
		for state in ["hover", "pressed", "disabled"]:
			check(not theme.get_stylebox(state, kind).bg_color.is_equal_approx(normal.bg_color), "distinct interaction state: " + kind + "/" + state)
		check(not theme.get_color("font_disabled_color", kind).is_equal_approx(theme.get_color("font_color", kind)), "disabled text is distinguishable: " + kind)
	for kind in ["Button", "OptionButton", "MenuButton", "LineEdit", "TextEdit", "HSlider", "CheckBox"]:
		var focus: StyleBox = theme.get_stylebox("focus", kind)
		check(focus is StyleBoxFlat, "explicit focus outline: " + kind)
		if focus is StyleBoxFlat:
			check(focus.border_width_left > 0 and focus.border_width_right > 0 and focus.border_width_top > 0 and focus.border_width_bottom > 0, "focus visible on all edges: " + kind)
			check(not focus.draw_center or focus.bg_color.a == 0, "focus does not obscure text: " + kind)
			check(focus.border_color.is_equal_approx(Color("168ac2") if kind == "CheckBox" else ACCENT), "focus accent: " + kind)
	for kind in ["LineEdit", "TextEdit"]:
		for state in ["normal", "read_only"]:
			check_surface(theme, kind, state, 8)
			check(theme.get_stylebox(state, kind).bg_color.get_luminance() > .85, "clear light input surface: " + kind + "/" + state)
	check(theme.get_stylebox("pressed", "CheckBox").bg_color.is_equal_approx(Color("d9f1ff")), "selected toggle uses light blue")
	check_surface(theme, "CheckBox", "hover_pressed", 8)
	for state in ["font_pressed_color", "font_hover_color", "font_hover_pressed_color", "font_focus_color"]:
		check(theme.get_color(state, "CheckBox").is_equal_approx(INK), "legible toggle text: " + state)
	check_surface(theme, "AppSurface", "panel", 12)
	for state in ["normal", "selected"]:
		check(theme.has_stylebox(state, "DynamicsPost"), "dynamic style is an editable resource: " + state)
	check(not theme.get_stylebox("normal", "DynamicsPost").bg_color.is_equal_approx(theme.get_stylebox("selected", "DynamicsPost").bg_color), "selected dynamic is distinguishable")
	check(not theme.get_color("delivery_failed", "MessageBubble").is_equal_approx(theme.get_color("delivery_status", "MessageBubble")), "delivery errors differ from ordinary status")
	check(theme.get_color("ERROR", "LogEntry") != theme.get_color("INFO", "LogEntry") and theme.get_color("WARN", "LogEntry") != theme.get_color("INFO", "LogEntry"), "log severity remains distinguishable")
	for state in ["grabber", "grabber_highlight", "grabber_disabled"]:
		var icon: Texture2D = theme.get_icon(state, "HSlider")
		check(icon != null, "slider state icon loads: " + state)
		if icon != null:
			var pixels := icon.get_image()
			check(pixels != null and not pixels.is_empty(), "slider icon has pixels: " + state)
			if pixels != null and not pixels.is_empty():
				check(pixels.get_pixel(0, 0).a < .2 and pixels.get_pixelv(pixels.get_size() / 2).a > .8, "slider dot has a visible center and transparent corner: " + state)
	check(load("res://assets/ui/round_avatar.gdshader") is Shader, "avatar material resource loads")
	print("Theme contract: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func check_surface(theme: Theme, kind: String, state: String, radius: int) -> void:
	check(theme.has_stylebox(state, kind), "authored style: " + kind + "/" + state)
	var style := theme.get_stylebox(state, kind)
	check(style is StyleBoxFlat, "Godot rounded surface: " + kind + "/" + state)
	if style is StyleBoxFlat:
		check(style.bg_color.a == 1, "solid surface: " + kind + "/" + state)
		check(style.corner_radius_top_left == radius and style.corner_radius_top_right == radius and style.corner_radius_bottom_left == radius and style.corner_radius_bottom_right == radius, "rounded corners: " + kind + "/" + state)
