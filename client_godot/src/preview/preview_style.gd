extends RefCounted
const ACCENT := Color("66ccff")
const INK := Color("304553")
const SURFACE := Color("f5f8fb")
const USER_BUBBLE := Color("dff3ff")

static func box(color: Color, radius: int = 12, padding: int = 12) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = color
	style.set_corner_radius_all(radius)
	style.content_margin_left = padding
	style.content_margin_right = padding
	style.content_margin_top = padding
	style.content_margin_bottom = padding
	return style

static func make_theme() -> Theme:
	return load("res://theme/app_theme.tres")

static func primary(node: Button) -> void:
	node.theme_type_variation = "PrimaryButton"

static func avatar(path: String, pixels: int = 38) -> TextureRect:
	var node := TextureRect.new()
	node.texture = load(path)
	node.custom_minimum_size = Vector2(pixels,pixels)
	node.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	node.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	node.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
	var material := ShaderMaterial.new()
	material.shader = load("res://assets/ui/round_avatar.gdshader")
	node.material = material
	return node

static func label(text: String, size: int = 15, color: Color = Color("344c59")) -> Label:
	var node := Label.new()
	node.text = text
	node.add_theme_font_size_override("font_size", size)
	node.add_theme_color_override("font_color", color)
	return node

static func button(text: String, action: Callable) -> Button:
	var node := Button.new()
	node.text = text
	node.pressed.connect(action)
	return node
