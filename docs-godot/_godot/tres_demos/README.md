# Godot `.tres` 实例教程

本目录用当前 Godot 4.7.1 工程解释 `.tres` 的主要用法。实际可运行工程位于仓库根目录的 `client_godot/`；本目录 `client/_godot/tres_demos/` 只放教学 Markdown，不是 Godot 项目根目录。下面代码中的 `res://` 均以 `client_godot/project.godot` 为根。

## 阅读顺序

| 篇章 | 功能 | 项目实例 |
| --- | --- | --- |
| [01 资源结构与自定义 Resource](01-资源结构与自定义Resource.md) | 创建资源、读懂文本格式 | `decoder.tres` |
| [02 场景注入平台实现](02-场景注入平台实现.md) | `@export`、Inspector、`.tscn` 外部引用 | `main.tscn`、`window_chrome.tscn` |
| [03 配置参数与持久化](03-配置参数与持久化.md) | 把参数放在 `.tres`，把用户数据写到 `user://` | `dynamics.tres` |
| [04 Theme 与子资源](04-Theme与子资源.md) | 外部纹理、内嵌 StyleBox、全局主题 | `app_theme.tres` |
| [05 ShaderMaterial](05-ShaderMaterial.md) | 保存 Shader 和 uniform 参数 | `frost_popup.tres` |
| [06 加载缓存与实例隔离](06-加载缓存与实例隔离.md) | `load`、`preload`、共享、复制、`resource_local_to_scene` | `window_host.tres` |
| [07 路径、UID 与运行时保存](07-路径UID与运行时保存.md) | `res://`、`user://`、资源保存和导出限制 | 本项目路径与独立练习 |

## 如何运行示例

1. 用 Godot 4.7.1 standard / Windows x64 导入 `client_godot/project.godot`。
2. 文中标为“现有工程演示”的步骤可直接在编辑器中操作；代码块标为“独立练习”的内容需放入临时脚本或临时场景。请不要覆盖项目的正式资源。
3. 单独试运行 GDScript 片段时，建一个临时 `Node` 场景，将片段放在其 `_ready()` 中并运行该场景。涉及 `Control` 的例子可使用 `Control` 根节点。
4. 修改正式 `.tres` 前先复制一份；这些资源已被多个场景引用。

## 五分钟跑通第一个 demo

1. 用 Godot 4.7.1 standard 打开 `client_godot/project.godot`，等待 FileSystem 导入完成。
2. 在 `client_godot/tests/manual/` 新建一个脚本，把 01 篇的 `TresDemoProfile` 类代码粘进去并保存。
3. 在同一目录创建 `Node` 场景，挂一个脚本，把 01 篇的 `load()` 代码放进 `_ready()`。
4. 按 **F6** 运行当前场景，在底部 **Output** 面板查看 `Luo Tianyi / 75`。
5. 运行后删除临时场景和脚本；如果测试写入了 `user://`，可在脚本中用 `DirAccess.remove_absolute(ProjectSettings.globalize_path(path))` 清理测试文件。

不要按 F5 运行这些临时场景来验证功能：F5 会启动项目正式入口 `res://scenes/main.tscn`，而不是当前手工练习场景。

## 先建立整体模型

在这个项目里，一个 `.tres` 通常经历下面的链路：

```text
脚本声明接口或导出属性
        ↓
编辑器创建/保存 .tres
        ↓
.tscn 或 project.godot 引用 .tres
        ↓
场景实例持有 Resource
        ↓
脚本调用 Resource 的方法或读取属性
        ↓
必要时把用户状态写入 user://
```

建议先区分四种文件：

| 文件 | 保存什么 | 是否适合写用户运行时状态 |
| --- | --- | --- |
| `.gd` | 行为、方法、信号、导出属性声明 | 否 |
| `.tres` | Resource 实例的类型、外部引用和导出属性值 | 通常否，尤其是导出包中的 `res://` |
| `.tscn` | 节点树以及节点到资源的装配关系 | 否 |
| `user://*.cfg` | 当前用户的可变设置、窗口位置、缓存索引 | 是 |

## 项目中的 `.tres` 分类

当前工程的 `.tres` 可以按用途分为三组：

1. **平台适配资源**：`resources/platform/*.tres`。例如 `windows.tres` 选择窗口系统实现，`decoder.tres` 选择原生解码工厂。它们是依赖注入的装配点。
2. **设置存储资源**：`dynamics.tres`、`framing.tres`、`preview.tres`、`geometry.tres`。它们保存脚本和 `user://` 文件路径；真正的读写由脚本完成。
3. **视觉资源**：`theme/app_theme.tres` 和 `theme/frost_popup.tres`。前者是全局 `Theme`，后者是磨砂 `ShaderMaterial`。

## 每篇教程的验证清单

读完一篇后，至少完成以下三步：

1. 在 FileSystem 中找到文中指出的项目资源，并打开 Inspector，确认类型和导出属性。
2. 对照文中的 `.tres` 或 `.tscn` 片段，找出 `ExtResource(...)`、`SubResource(...)` 的声明和使用位置。
3. 运行独立 demo，记录控制台输出；若 demo 修改了资源，确认它操作的是 `duplicate()` 或 `user://` 副本。

## 常用检查命令

在仓库根目录执行 PowerShell：

```powershell
Get-ChildItem -LiteralPath client_godot -Recurse -Filter *.tres
rg -n 'type="Resource"|type="Theme"|type="Material"|\.tres' client_godot/scenes client_godot/project.godot
rg -n 'resource_local_to_scene|ResourceSaver|ConfigFile|user://' client_godot
```

如果引用路径存在但 Godot 仍报资源加载错误，先查看 Output 面板中的第一条脚本解析错误，再检查资源路径和外部依赖。不要直接删除 `.godot/` 或 `.import` 来“修复”源码引用；这些目录是生成物。

这些教程说明资源机制，不代表工程中所有平台功能已通过正式验收。工程入口和测试命令见 [Godot README](../../../client_godot/README.md)。
