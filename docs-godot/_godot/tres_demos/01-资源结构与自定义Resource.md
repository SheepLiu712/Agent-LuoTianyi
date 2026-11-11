# 01. 资源结构与自定义 Resource

## 项目中的例子

[`decoder.tres`](../../../client_godot/resources/platform/decoder.tres) 只有四个有效行：

```ini
[gd_resource type="Resource" load_steps=2 format=3]
[ext_resource type="Script" path="res://src/platform/native_decoder_factory.gd" id="1"]
[resource]
script = ExtResource("1")
```

这不是脚本文件的副本。它是一个可序列化的 `Resource` 实例，`script` 属性指定该实例的实际行为。`native_decoder_factory.gd` 继承项目的解码工厂接口；主场景通过这个资源选择具体实现。

| 语法 | 含义 |
| --- | --- |
| `[gd_resource type="Resource" ...]` | 根对象的 Godot 类型；`format=3` 是 Godot 4 的文本资源格式。 |
| `load_steps=2` | 加载步骤元数据；当前例子包括一个外部依赖和根资源。由编辑器维护，不宜手工计数。 |
| `[ext_resource ... id="1"]` | 声明另一个文件，`id` 只在本文件内部使用。 |
| `[resource]` | 根对象的序列化属性。 |
| `ExtResource("1")` | 取上面声明的外部脚本对象。 |

## 独立练习：做一份有数据的 `.tres`

在 Godot 项目中临时创建 `res://tests/manual/tres_demo_profile.gd`：

```gdscript
extends Resource
class_name TresDemoProfile

@export var display_name: String = "Luo Tianyi"
@export_range(0, 100) var volume: int = 60
@export var tags: PackedStringArray = PackedStringArray(["demo"])
```

在编辑器的 FileSystem 面板右键，选择 **New Resource**，搜索 `TresDemoProfile`，保存为 `res://tests/manual/tres_demo_profile.tres`。在 Inspector 中将 `volume` 改为 `75`。Godot 保存后会生成类似内容：

```ini
[gd_resource type="Resource" script_class="TresDemoProfile" load_steps=2 format=3]

[ext_resource type="Script" path="res://tests/manual/tres_demo_profile.gd" id="1"]

[resource]
script = ExtResource("1")
display_name = "Luo Tianyi"
volume = 75
tags = PackedStringArray("demo")
```

文件头的 `script_class`、UID、ID、空行和属性顺序可能因编辑器版本而异，以编辑器实际保存结果为准。默认值相同的属性也可能不写入文件。

验证脚本：

```gdscript
extends Node

func _ready() -> void:
	var profile: TresDemoProfile = load("res://tests/manual/tres_demo_profile.tres")
	print(profile.display_name, " / ", profile.volume, " / ", profile.tags)
```

预期输出包含 `Luo Tianyi / 75 / ["demo"]`。修改 `.tres` 中的 `volume` 后重新运行，输出跟着变化，脚本逻辑无需修改。

## 什么时候使用

把多处共享、希望在 Inspector 中编辑的数据或实现选择保存为 `.tres`。运行中的临时计算结果和用户会话状态通常不适合直接写回工程里的 `.tres`。

## 从脚本到资源的完整生命周期

以上 demo 中，`TresDemoProfile` 是一个脚本类，`.tres` 是这个类的一个序列化实例：

1. `extends Resource` 让脚本可以作为 Godot 资源承载数据。
2. `class_name TresDemoProfile` 让编辑器能在 **New Resource** 对话框中找到它。
3. `@export` 让字段进入 Inspector，并告诉 Godot 如何序列化它。
4. 编辑器把字段值写入 `[resource]` 区域。
5. `load()` 返回资源对象；脚本读到的是实例属性，不是文本行。

如果删除 `@export`，例如 `var runtime_only_value := 10`，该字段仍能在运行时使用，但不会出现在 Inspector，也不会作为普通属性保存进 `.tres`。这正是资源配置和运行时状态的边界。

## 字段类型和 Inspector 显示

```gdscript
@export var title: String = "默认标题"
@export_range(0.0, 1.0, 0.05) var opacity := 0.8
@export var icon: Texture2D
@export var style: StyleBox
@export_flags("Read", "Write") var permissions := 1
```

- `String` 显示文本框。
- `@export_range` 显示带范围的数字控件，并限制编辑值。
- `Texture2D`、`StyleBox` 等 Resource 类型显示资源槽，可拖入文件。
- `@export_flags` 把多个布尔选项压缩为位标记。

如果调用者只要求“有一个 Resource”，可以使用 `Resource`；如果必须是某个自定义资源，建议使用具体类型，例如 `TresDemoProfile`。类型越具体，Inspector 越能提前发现错误。

## 如何手工读懂一份文本资源

阅读项目的 [`dynamics.tres`](../../../client_godot/resources/platform/dynamics.tres) 时按这个顺序：

1. 看 `[gd_resource]`：根类型是 `Resource`。
2. 看 `[ext_resource]`：它挂载 `godot_settings_store.gd`。
3. 看 `[resource]`：脚本被赋给 `script`，并设置了 `file_path`。
4. 看 `resource_local_to_scene`：它影响场景实例化时的资源隔离。

不要把 `load_steps` 当成业务字段，也不要手动根据空行修改它。编辑器保存资源时会维护这些序列化元数据。

## 常见错误

| 现象 | 原因 | 检查方式 |
| --- | --- | --- |
| New Resource 找不到自定义类型 | 缺少 `class_name`、脚本有解析错误，或脚本不在当前项目 | 查看 Script 面板错误并确认脚本路径 |
| 资源能打开但字段不见了 | 字段没有 `@export`，或脚本不是该资源的 `script` | 检查脚本和 `.tres` 的 `script = ...` |
| 修改脚本字段后旧资源报错 | 字段被重命名、类型改变或脚本路径移动 | 先保留备份，再用 Inspector 重新保存 |
| `load()` 返回 `null` | 路径错误或资源解析失败 | 使用 `ResourceLoader.exists()` 并查看 Output 面板 |
