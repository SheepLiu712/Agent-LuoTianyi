# 05. 用 `.tres` 保存 ShaderMaterial

## 现有工程演示

[`frost_popup.tres`](../../../client_godot/theme/frost_popup.tres) 是 `ShaderMaterial`：

```ini
[gd_resource type="ShaderMaterial" load_steps=2 format=3]
[ext_resource type="Shader" path="res://assets/ui/frost_surface.gdshader" id="shader"]
[resource]
resource_local_to_scene = true
shader = ExtResource("shader")
shader_parameter/tint = Color(0.12,0.2,0.28,0.24)
shader_parameter/radius = 5.0
```

外部 [`frost_surface.gdshader`](../../../client_godot/assets/ui/frost_surface.gdshader) 声明了 `tint`、`radius` 两个 uniform；`.tres` 为它们提供具体值。[`publish_overlay.tscn`](../../../client_godot/scenes/ui/publish_overlay.tscn) 把此材质赋给 `Shade` 节点。`tint` 控制混合色，`radius` 传给 `textureLod`，表示屏幕纹理的 mip 采样层级和模糊强度，不是固定的像素半径。实际效果还取决于渲染器、底层画面及该场景的运行条件。

## 独立练习：调整一份局部材质

在临时 `Control` 场景中添加 `ColorRect`，命名为 `Shade`，使它覆盖需要处理的背景；脚本写在根节点：

```gdscript
extends Control

@onready var shade: ColorRect = $Shade

func _ready() -> void:
	var original: ShaderMaterial = load("res://theme/frost_popup.tres")
	var local_material: ShaderMaterial = original.duplicate(true)
	local_material.set_shader_parameter("radius", 2.0)
	local_material.set_shader_parameter("tint", Color(0.12, 0.2, 0.28, 0.35))
	shade.material = local_material
	print(local_material.get_shader_parameter("radius"))
```

预期打印 `2`。应先放一张作为底层的图片，再放覆盖全区域的 `Shade` 兄弟节点；不要把图片放在 `Shade` 后面，否则图片可能覆盖材质结果。此例先复制材质，避免运行时改变正在其他场景中使用的资源。`resource_local_to_scene` 在场景实例化时提供隔离，但如果代码直接 `load()` 同一路径，仍应自行复制再改参数。

## 编辑器操作

在 FileSystem 中打开 `frost_popup.tres`，Inspector 的 Shader Parameters 可直接调整 `tint`、`radius`。保存后，引用该材质的场景都会得到新的默认值。需要一个专用版本时，在 FileSystem 中复制这份 `.tres`，再把目标场景的 `Material` 属性指向新文件。

## Shader 参数是如何对应的

Shader 中的声明：

```glsl
uniform vec4 tint : source_color = vec4(0.95, 0.98, 1.0, 0.86);
uniform float radius : hint_range(0.0, 12.0) = 4.0;
```

在 `.tres` 中写成：

```ini
shader_parameter/tint = Color(0.12,0.2,0.28,0.24)
shader_parameter/radius = 5.0
```

`shader_parameter/` 后面的名字必须和 uniform 完全一致，包含大小写。改名后如果只改 Shader 而没改 `.tres`，旧参数不会影响新的 uniform；反过来，如果 `.tres` 写了 Shader 中不存在的参数，也不会产生你期待的效果。

## 运行时参数调整

```gdscript
var material: ShaderMaterial = $Shade.material as ShaderMaterial
material.set_shader_parameter("tint", Color(0.8, 0.95, 1.0, 0.2))
material.set_shader_parameter("radius", 1.5)
```

读取参数用于调试：

```gdscript
print(material.get_shader_parameter("radius"))
```

如果节点材质来自共享 `.tres`，先复制：

```gdscript
var local_material: ShaderMaterial = ($Shade.material as ShaderMaterial).duplicate(true)
$Shade.material = local_material
```

## 画面为空或参数没有效果时

1. 确认节点是 `CanvasItem`（例如 `ColorRect`、`Panel`），并且 `material` 属性确实指向 `ShaderMaterial`。
2. 确认 Shader 没有编译错误；查看 Godot Output 和 Shader Editor 的错误行。
3. `screen_texture` 依赖屏幕纹理，节点前面要有可采样的背景内容。
4. `radius` 受 Shader 中的 `hint_range(0.0, 12.0)` 约束；过大的值不一定产生更好的视觉效果。
5. 项目使用 GL Compatibility；在 headless 或不支持屏幕纹理的环境中，项目脚本可能主动清除材质。

临时场景中建议将 `Shade.mouse_filter = Control.MOUSE_FILTER_IGNORE`，避免覆盖层拦截底层按钮的鼠标事件。headless 验收只能检查场景没有崩溃和项目的降级逻辑，不能替代 GPU 画面验收。

## 为什么材质放在 `.tres`

Shader 代码和参数分开后，美术或 UI 开发者可以在 Inspector 调整颜色、透明度和模糊半径，而无需改动 GLSL。多个场景共享相同视觉效果时引用同一个材质；需要独立动画或运行时变体时复制材质对象。
