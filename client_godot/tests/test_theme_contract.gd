extends SceneTree
const THEME_PATH := "res://theme/app_theme.tres"
const SHADER_PATH := "res://assets/ui/round_avatar.gdshader"
const DOTS := {
	"res://assets/ui/slider_dot.png": Color("66ccff"),
	"res://assets/ui/slider_dot_highlight.png": Color("43b8f0"),
	"res://assets/ui/slider_dot_disabled.png": Color("b7c6d0"),
}
const ICONS := {
	"HSlider|grabber": "res://assets/ui/slider_dot.png",
	"HSlider|grabber_highlight": "res://assets/ui/slider_dot_highlight.png",
	"HSlider|grabber_disabled": "res://assets/ui/slider_dot_disabled.png",
}
const INK := Color("304553")
const ACCENT := Color("66ccff")
const TRANSPARENT := Color.TRANSPARENT
# 期望的字体色，键为 "<type>|<name>"。
const COLORS := {
	"Label|font_color": INK,
	"Button|font_color": INK,
	"OptionButton|font_color": INK,
	"LineEdit|font_color": INK,
	"TextEdit|font_color": INK,
	"RichTextLabel|font_color": INK,
	"PopupMenu|font_color": INK,
	"CheckBox|font_color": INK,
	"RichTextLabel|default_color": INK,
	"TextEdit|font_placeholder_color": Color("9aaeb8"),
	"LineEdit|font_placeholder_color": Color("8299a6"),
	"Button|font_hover_color": INK,
	"Button|font_pressed_color": INK,
	"Button|font_focus_color": INK,
	"Button|font_disabled_color": Color("9aabb7"),
	"OptionButton|font_hover_color": INK,
	"OptionButton|font_pressed_color": INK,
	"OptionButton|font_focus_color": INK,
	"OptionButton|font_disabled_color": Color("9aabb7"),
	"MenuButton|font_color": INK,
	"MenuButton|font_hover_color": INK,
	"MenuButton|font_pressed_color": INK,
	"MenuButton|font_focus_color": INK,
	"MenuButton|font_disabled_color": Color("9aabb7"),
	"TextEdit|selection_color": Color("b7e6ff"),
	"TextEdit|caret_color": INK,
	"LineEdit|selection_color": Color("b7e6ff"),
	"LineEdit|caret_color": INK,
	"PopupMenu|font_hover_color": INK,
}
# 期望的实底样式，键为 "<type>|<name>"，值为 [背景色, 圆角, 内边距]。
const BOXES := {
	"Button|normal": [Color("eef6fb"), 8, 9],
	"Button|hover": [Color("dff3ff"), 8, 9],
	"Button|pressed": [Color("b7e6ff"), 8, 9],
	"Button|disabled": [Color("edf1f4"), 8, 9],
	"OptionButton|normal": [Color("eef6fb"), 8, 9],
	"OptionButton|hover": [Color("dff3ff"), 8, 9],
	"OptionButton|pressed": [Color("b7e6ff"), 8, 9],
	"OptionButton|disabled": [Color("edf1f4"), 8, 9],
	"MenuButton|normal": [Color("eef6fb"), 8, 9],
	"MenuButton|hover": [Color("dff3ff"), 8, 9],
	"MenuButton|pressed": [Color("b7e6ff"), 8, 9],
	"MenuButton|disabled": [Color("edf1f4"), 8, 9],
	"PrimaryButton|normal": [ACCENT, 9, 10],
	"PrimaryButton|hover": [Color("8ad8ff"), 9, 10],
	"PrimaryButton|pressed": [Color("43b8f0"), 9, 10],
	"TextEdit|normal": [Color.WHITE, 8, 12],
	"LineEdit|normal": [Color.WHITE, 8, 12],
	"PopupMenu|panel": [Color.WHITE, 10, 8],
	"PopupMenu|hover": [Color("dff3ff"), 6, 6],
	"HSlider|slider": [Color("dcecf5"), 2, 2],
	"HSlider|grabber_area": [ACCENT, 2, 2],
	"HSlider|grabber_area_highlight": [ACCENT, 2, 2],
}
const FOCUS_BOXES := [
	"Button|focus", "OptionButton|focus", "MenuButton|focus",
	"TextEdit|focus", "LineEdit|focus", "HSlider|focus",
]
var failures: Array[String] = []
func check(value: bool,text: String) -> void:
	if not value:
		failures.append(text)
		print("FAIL: ",text)
func _initialize() -> void:
	_run.call_deferred()
func _run() -> void:
	check(ResourceLoader.exists(THEME_PATH),"theme resource exists")
	check(ResourceLoader.exists(SHADER_PATH),"round avatar shader exists")
	for path: String in DOTS:
		check(ResourceLoader.exists(path),"slider dot exists: "+path)
	if not failures.is_empty():
		quit(1)
		return
	var theme: Theme = ResourceLoader.load(THEME_PATH,"",ResourceLoader.CACHE_MODE_IGNORE)
	check(theme != null,"theme resource decodes")
	if theme == null:
		quit(1)
		return
	check(theme.default_font_size == 15,"theme default font size is 15")
	var font := theme.default_font
	check(font is SystemFont,"theme default font is SystemFont")
	if font is SystemFont:
		check(font.font_names == PackedStringArray(["Microsoft YaHei UI","Microsoft YaHei"]),"theme font family unchanged")
	check(theme.get_type_variation_base("PrimaryButton") == &"Button","PrimaryButton varies Button")
	check(theme.get_constant("v_separation","PopupMenu") == 12,"popup menu v_separation is 12")
	for key: String in COLORS:
		var parts := key.split("|")
		check(theme.get_color(parts[1],parts[0]) == COLORS[key],"color matches spec: "+key)
	for key: String in BOXES:
		var parts := key.split("|")
		var expected: Array = BOXES[key]
		check_box(theme.get_stylebox(parts[1],parts[0]),expected[0],expected[1],expected[2],0,TRANSPARENT,"stylebox matches spec: "+key)
	for key: String in FOCUS_BOXES:
		var parts := key.split("|")
		check_box(theme.get_stylebox(parts[1],parts[0]),TRANSPARENT,8,0,2,ACCENT,"focus stylebox matches spec: "+key)
	for key: String in ICONS:
		var parts := key.split("|")
		check(theme.get_icon(parts[1],parts[0]) != null,"icon exists: "+key)
	check(theme.get_icon("grabber","HSlider") == load(ICONS["HSlider|grabber"]),"grabber icon uses slider dot asset")
	for path: String in DOTS:
		check(dot_pixels_match(path,DOTS[path]),"slider dot pixels match formula: "+path)
	check(ProjectSettings.get_setting("gui/theme/custom","") == THEME_PATH,"project uses app theme")
	var shader: Shader = load(SHADER_PATH)
	check(shader != null and shader.code.contains("smoothstep(0.47,0.5,length(UV-vec2(0.5)))"),"round avatar shader keeps circular mask")
	print("Theme contract: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
func check_box(style: StyleBox,bg: Color,radius: int,padding: int,border: int,border_color: Color,label: String) -> void:
	check(style is StyleBoxFlat,label+" is flat")
	if not (style is StyleBoxFlat):
		return
	var flat: StyleBoxFlat = style
	check(flat.bg_color == bg,label+" bg")
	check(flat.corner_radius_top_left == radius and flat.corner_radius_top_right == radius and flat.corner_radius_bottom_right == radius and flat.corner_radius_bottom_left == radius,label+" corner radius")
	check(flat.content_margin_left == padding and flat.content_margin_right == padding and flat.content_margin_top == padding and flat.content_margin_bottom == padding,label+" content margin")
	check(flat.border_width_left == border and flat.border_width_top == border and flat.border_width_right == border and flat.border_width_bottom == border,label+" border width")
	if border > 0:
		check(flat.border_color == border_color,label+" border color")
func dot_image(color: Color) -> Image:
	var image := Image.create(16,16,false,Image.FORMAT_RGBA8)
	image.fill(Color.TRANSPARENT)
	for y in 16:
		for x in 16:
			if Vector2(x-7.5,y-7.5).length() <= 6:
				image.set_pixel(x,y,color)
	return image
func dot_pixels_match(path: String,color: Color) -> bool:
	var texture: Texture2D = load(path)
	if texture == null:
		return false
	var image: Image = texture.get_image()
	if image == null or image.get_width() != 16 or image.get_height() != 16:
		return false
	var expected := dot_image(color)
	for y in 16:
		for x in 16:
			var actual := image.get_pixel(x,y)
			var wanted := expected.get_pixel(x,y)
			if actual.a != wanted.a:
				return false
			if wanted.a > 0 and (actual.r != wanted.r or actual.g != wanted.g or actual.b != wanted.b):
				return false
	return true
