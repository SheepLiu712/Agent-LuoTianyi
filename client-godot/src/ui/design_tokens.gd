extends RefCounted
## Unified UI design tokens: Tianyi cyan palette, surface hierarchy, spacing scale, and semantic status tokens.

const SPACE_NONE := 0.0
const SPACE_XXS := 2.0
const SPACE_XS := 4.0
const SPACE_SM := 8.0
const SPACE_MD := 12.0
const SPACE_LG := 16.0
const SPACE_XL := 24.0
const SPACE_XXL := 40.0

const RADIUS_FLAT := 8
const RADIUS_CRYSTAL := 12
const RADIUS_DROPDOWN_FLAT := 6
const RADIUS_DROPDOWN_CRYSTAL := 8

const ICON_SIZE := 20

# Brand & Ink
const ACCENT := Color("66ccff")
const ACCENT_HOVER := Color("52beff")
const ACCENT_PRESSED := Color("33a5eb")
const ACCENT_DEEP := Color("168ac2")
const ACCENT_LINK := Color("168ac2")
const ACCENT_LINK_HOVER := Color("0a5c87")
const ACCENT_SOFT := Color("e6f6ff")
const ACCENT_TINT_SELECTED := Color("d9f1ff")

const INK_PRIMARY := Color("304553")
const INK_SECONDARY := Color("4f6775")
const INK_MUTED := Color("6b8290")
const INK_PLACEHOLDER := Color("8299a6")
const INK_DISABLED := Color("9aabb5")
const INK_ON_ACCENT := Color("ffffff")

const SELECTION_BG := Color("0078d7")
const SELECTION_FG := Color("ffffff")

# Surfaces & Borders
const WINDOW_BG_FLAT := Color(0.953, 0.976, 0.992, 1.0)
const WINDOW_BG_CRYSTAL := Color(0.922, 0.961, 0.992, 1.0)
const SURFACE_WHITE := Color(1.0, 1.0, 1.0, 1.0)
const SURFACE_CARD := Color(0.984, 0.994, 1.0, 1.0)
const SURFACE_SUBTLE := Color(0.945, 0.973, 0.988, 1.0)
const SURFACE_DISABLED := Color(0.929, 0.945, 0.957, 1.0)

const BORDER_FLAT := Color(0.84, 0.90, 0.95, 0.92)
const BORDER_SUBTLE := Color(0.863, 0.910, 0.949, 1.0)
const BORDER_CRYSTAL := Color(0.72, 0.88, 1.0, 0.58)
const BORDER_CRYSTAL_SOFT := Color(0.72, 0.88, 1.0, 0.45)

# Chat Surfaces & Workspace Chrome
const NAV_RAIL_BG_FLAT := Color(0.941, 0.965, 0.980, 1.0)
const NAV_RAIL_BG_CRYSTAL := Color(0.940, 0.975, 1.0, 0.65)
const NAV_RAIL_BORDER_FLAT := Color(0.878, 0.914, 0.941, 1.0)
const NAV_RAIL_BORDER_CRYSTAL := Color(1.0, 1.0, 1.0, 0.70)
const BACKDROP_START_FLAT := Color(0.965, 0.976, 0.988, 1.0)
const BACKDROP_END_FLAT := Color(0.965, 0.976, 0.988, 1.0)
const BACKDROP_START_CRYSTAL := Color(0.84, 0.94, 1.0, 1.0)
const BACKDROP_END_CRYSTAL := Color(0.93, 0.975, 1.0, 1.0)
const CHAT_SURFACE_CRYSTAL := Color(1.0, 1.0, 1.0, 0.82)
const CHAT_COMPOSER_CRYSTAL := Color(1.0, 1.0, 1.0, 0.45)
const AVATAR_HEADING_FLAT := Color(1.0, 1.0, 1.0, 0.94)
const AVATAR_HEADING_CRYSTAL := Color(1.0, 1.0, 1.0, 0.82)
const AVATAR_RESET_STATES := {
	"normal": Color(1.0, 1.0, 1.0, 0.94),
	"hover": Color(0.94, 0.98, 1.0, 1.0),
	"pressed": Color(0.86, 0.95, 1.0, 1.0),
}

# Chat Bubbles
const BUBBLE_OWN_FLAT := Color(0.80, 0.92, 1.0, 1.0)
const BUBBLE_OTHER_FLAT := Color(0.945, 0.969, 0.984, 1.0)
const BUBBLE_OWN_CRYSTAL := Color(0.863, 0.949, 1.0, 0.74)
const BUBBLE_OTHER_CRYSTAL := Color(1.0, 1.0, 1.0, 0.75)
const TIME_CHIP_FLAT := Color(0.93, 0.95, 0.97, 1.0)
const TIME_CHIP_CRYSTAL := Color(0.91, 0.95, 0.98, 0.72)

# Shadows
const SHADOW_CARD := Color(0.10, 0.25, 0.40, 0.08)
const SHADOW_BUBBLE := Color(0.12, 0.28, 0.42, 0.08)
const SHADOW_DIALOG := Color(0.063, 0.157, 0.227, 0.16)
const SHADOW_ACTION := Color(0.063, 0.157, 0.227, 0.10)
const SHADOW_CLEAR := Color(0.0, 0.0, 0.0, 0.0)

# Semantic Status & Toasts
const TOAST_COLORS := {
	"success": {"bg": Color(0.94, 1.0, 0.96, 1), "border": Color(0.18, 0.64, 0.40, 0.9)},
	"error": {"bg": Color(1.0, 0.95, 0.95, 1), "border": Color(0.78, 0.24, 0.24, 0.9)},
	"progress": {"bg": Color(0.94, 0.985, 1.0, 1), "border": Color(0.4, 0.8, 1.0, 0.95)},
	"warning": {"bg": Color(1.0, 0.972, 0.92, 1), "border": Color(0.84, 0.56, 0.14, 0.9)},
	"info": {"bg": Color(1, 1, 1, 1), "border": Color(0.259, 0.725, 0.929, 0.9)},
}

const STATUS_PALETTES := {
	"muted": {"text": Color(0.42, 0.5, 0.56, 1), "bg": Color(0.968, 0.98, 0.988, 1), "border": Color(0.86, 0.905, 0.94, 1)},
	"info": {"text": Color(0.117647, 0.407843, 0.6, 1), "bg": Color(0.945, 0.982, 1.0, 1), "border": Color(0.62, 0.86, 0.98, 0.95)},
	"progress": {"text": Color(0.117647, 0.407843, 0.6, 1), "bg": Color(0.945, 0.982, 1.0, 1), "border": Color(0.4, 0.8, 1.0, 0.95)},
	"success": {"text": Color(0.117647, 0.431373, 0.286275, 1), "bg": Color(0.94, 0.992, 0.96, 1), "border": Color(0.46, 0.79, 0.6, 0.9)},
	"warning": {"text": Color(0.611765, 0.341176, 0, 1), "bg": Color(1.0, 0.972, 0.92, 1), "border": Color(0.88, 0.66, 0.32, 0.9)},
	"error": {"text": Color(0.717647, 0.164706, 0.164706, 1), "bg": Color(1.0, 0.952, 0.952, 1), "border": Color(0.88, 0.48, 0.48, 0.9)},
}

# Data Visualization (Storage Ring & Waveform)
const RING_BACKDROP := Color(0.921569, 0.956863, 0.984314, 1.0)
const RING_CLIENT := Color(0.4, 0.8, 1.0, 1.0)
const RING_OTHER := Color(0.784314, 0.823529, 0.862745, 1.0)
const RING_FREE := Color(1.0, 1.0, 1.0, 1.0)
const RING_WARNING := Color(0.91, 0.62, 0.24, 1.0)
const RING_DANGER := Color(0.82, 0.34, 0.34, 1.0)

const WAVE_BAR_ACTIVE := ACCENT
const WAVE_BAR_INACTIVE := Color("9eb6c4")
const WAVE_PLAYHEAD := Color(0.08, 0.46, 0.68, 1.0)


static func surface_radius(crystal: bool) -> int:
	return RADIUS_CRYSTAL if crystal else RADIUS_FLAT


static func dropdown_item_radius(crystal: bool) -> int:
	return RADIUS_DROPDOWN_CRYSTAL if crystal else RADIUS_DROPDOWN_FLAT


static func icon_path(name: String, emoji: bool) -> String:
	return "res://assets/ui/icons/" + name + ("_emoji.png" if emoji else ".svg")
