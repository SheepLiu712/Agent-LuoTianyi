# 04. Theme、外部资源和内嵌子资源

## 现有工程演示

[`app_theme.tres`](../../../client_godot/theme/app_theme.tres) 的根类型是 `Theme`。它通过 `[ext_resource]` 引用滑块和复选框图标，通过 `[sub_resource]` 在文件内部创建 `StyleBoxFlat`、`StyleBoxLine`、`SystemFont` 等资源。文件后面的 `[resource]` 将这些资源绑定到控件状态：

```ini
[ext_resource type="Texture2D" path="res://assets/ui/slider_dot.png" id="1_5ln1w"]
[sub_resource type="SystemFont" id="SystemFont_pul83"]
font_names = PackedStringArray("Microsoft YaHei UI", "Microsoft YaHei")

[resource]
default_font = SubResource("SystemFont_pul83")
default_font_size = 15
Button/styles/normal = SubResource("StyleBoxFlat_ykw30")
HSlider/icons/grabber = ExtResource("1_5ln1w")
```

`ExtResource(...)` 指向独立文件；`SubResource(...)` 指向当前 `.tres` 内部的对象。`Button/styles/normal`、`HSlider/icons/grabber` 是 `Theme` 的控件类型、资源类别和名称。文件中还有 `PrimaryButton/base_type = &"Button"` 等自定义主题类型变体。项目在 [`project.godot`](../../../client_godot/project.godot) 的 `[gui]` 段将该主题设为全局主题，多个 `.tscn` 也显式引用它。

## 独立练习：读取并局部改动按钮样式

给临时 `Control` 场景挂脚本：

```gdscript
extends Control

func _ready() -> void:
	var shared_theme: Theme = load("res://theme/app_theme.tres")
	var local_theme: Theme = shared_theme.duplicate(true)
	var normal: StyleBoxFlat = local_theme.get_stylebox("normal", "Button").duplicate(true) as StyleBoxFlat
	normal.bg_color = Color(0.08, 0.55, 0.42)
	local_theme.set_stylebox("normal", "Button", normal)

	var button := Button.new()
	button.text = "主题测试"
	button.theme = local_theme
	add_child(button)
	var icon: Texture2D = local_theme.get_icon("grabber", "HSlider")
	print(icon != null, " / ", icon.resource_path if icon else "<missing>")
```

预期按钮使用局部修改后的绿色常态样式，打印 `true / res://assets/ui/slider_dot.png`。如果导入尚未完成，图标可能为空；此时先查看 Output 面板。其他场景仍使用共享主题。按钮按下、悬停时会显示各自的状态样式，所以颜色可能暂时不同。

## 编辑器操作

打开 `app_theme.tres`，在 Inspector 的 Theme Editor 中选择 `Button`，查看 `normal`、`hover`、`pressed`、`focus` 等状态。需要多个控件共用一种视觉规则时，将样式放在 Theme；只属于一个控件的特例可在控件的 Theme Overrides 中设置。修改全局 Theme 会影响所有引用它的场景，保存前先确认影响范围。

## Theme 属性命名规则

Theme 的键不是任意字符串，而是由控件类型、资源类别和名称组成：

```text
Button/colors/font_color
Button/styles/normal
HSlider/icons/grabber
LoginField/fonts/font
```

脚本 API 对应为：

```gdscript
var theme: Theme = load("res://theme/app_theme.tres")
var button_color: Color = theme.get_color("font_color", "Button")
var button_style: StyleBox = theme.get_stylebox("normal", "Button")
var slider_icon: Texture2D = theme.get_icon("grabber", "HSlider")
```

自定义类型变体需要先在 Theme 中设置基础类型，例如项目的 `PrimaryButton/base_type = &"Button"`。控件使用 `theme_type_variation = &"PrimaryButton"` 后，会继承 `Button` 的基础规则并覆盖变体中存在的属性。

## 独立 demo：创建一个带 Theme 的控件树

```gdscript
extends Control

func _ready() -> void:
	theme = load("res://theme/app_theme.tres")
	var column := VBoxContainer.new()
	column.position = Vector2(24, 24)
	add_child(column)

	var normal := Button.new()
	normal.text = "普通 Button"
	column.add_child(normal)

	var primary := Button.new()
	primary.text = "PrimaryButton 变体"
	primary.theme_type_variation = &"PrimaryButton"
	column.add_child(primary)
```

运行时若看到两个按钮但变体样式没有生效，先确认 `app_theme.tres` 中真的存在 `PrimaryButton/base_type` 和对应的 `PrimaryButton/styles/*`，再检查控件属性拼写。Theme 变体名称是 `StringName`，建议复制项目中现有写法。

## 外部资源和子资源的选择

- 纹理、Shader、独立字体等可被其他资源复用的对象，通常使用 `ExtResource`。
- 只服务于当前 Theme 的 `StyleBoxFlat`、字体设置，可以使用 `SubResource`，减少文件数量。
- 如果某个样式需要多个主题或场景独立修改，把它拆成单独 `.tres` 更清楚。

## 全局 Theme 的影响范围

`project.godot` 设置了 `theme/custom = "res://theme/app_theme.tres"`，因此没有局部主题的 Control 会继承它。场景还可以通过 `theme = ExtResource(...)` 明确设置主题，子节点再继承父节点。调试样式时按“控件局部覆盖 → 场景 Theme → Project 全局 Theme”的顺序检查来源。
