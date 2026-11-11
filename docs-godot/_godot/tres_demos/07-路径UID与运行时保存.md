# 07. 资源路径、UID 和运行时保存

## 两类路径

| 前缀 | 所指位置 | 本项目示例 |
| --- | --- | --- |
| `res://` | Godot 工程根目录；导出后多为打包资源 | `res://theme/app_theme.tres` |
| `user://` | 应用的用户数据目录；可写 | `user://dynamics-window.cfg` |

本工程根目录是 `client_godot/`，不是本教程所在的 `client/_godot/`。[`project.godot`](../../../client_godot/project.godot) 使用自定义用户目录 `AgentLuo-Godot`。可运行以下临时脚本查看真实绝对路径：

```gdscript
extends Node

func _ready() -> void:
	print(ProjectSettings.globalize_path("res://"))
	print(ProjectSettings.globalize_path("user://"))
	print(ResourceLoader.exists("res://theme/app_theme.tres"))
```

预期最后一行是 `true`。前两行在不同机器、编辑器和导出包中可能不同，不应硬编码进 `.tres`。

## UID 与移动文件

当前项目的 `.tres` 使用 `res://...` 路径引用；这些 `.tres` 文件头没有显式 `uid=...`。`ExtResource` 的 `id`（例如 `id="shader"`）只是当前文本资源内部的名字，不是全局 UID。移动、重命名 `.tres` 或其依赖时，应在 Godot 编辑器中操作，并检查引用它的 `.tscn`、`project.godot` 和测试脚本。不要把 `.godot/` 导入缓存或 `.import` 文件当成手写资源的替代品。

## 独立练习：运行时保存一份新的 `.tres`

项目目前使用 `ConfigFile` 保存用户配置，没有将运行时状态通过 `ResourceSaver` 写回项目资源。下面是独立练习，展示 ResourceSaver 能保存**导出属性**。

先创建 `res://tests/manual/tres_demo_data.gd`：

```gdscript
extends Resource
class_name TresDemoData

@export var note: String = ""
@export var count: int = 0
```

再在临时 `Node` 的脚本中运行：

```gdscript
extends Node

func _ready() -> void:
	var data := TresDemoData.new()
	data.note = "saved from runtime"
	data.count = 3
	var path := "user://tres-demo-data.tres"
	var error: Error = ResourceSaver.save(data, path)
	if error != OK:
		push_error("资源保存失败: %s" % error)
		return
	var loaded: TresDemoData = ResourceLoader.load(path, "", ResourceLoader.CACHE_MODE_IGNORE)
	if loaded == null:
		push_error("资源读取失败: %s" % path)
		return
	print(loaded.note, " / ", loaded.count)
```

预期打印 `saved from runtime / 3`。`CACHE_MODE_IGNORE` 用于此演示，确保示例读取文件内容，而不是误把仍在内存中的缓存对象当成磁盘验证。资源中没有 `@export` 的普通变量通常不会随 `.tres` 序列化。运行时自定义用户数据应写入 `user://`；导出后 PCK 内的 `res://` 通常不可写，不能把它作为用户数据目录。

## 与项目现状的对应关系

[`dynamics.tres`](../../../client_godot/resources/platform/dynamics.tres) 保存 `file_path` 这种配置；[`godot_settings_store.gd`](../../../client_godot/src/storage/godot_settings_store.gd) 使用 `ConfigFile` 写入 `user://*.cfg`。因此 `ResourceSaver` 的例子是 API 教学，不是建议把项目现有存储方案替换掉。

## `ResourceLoader` 的错误处理

不要把 `load()` 的失败当成普通空值继续使用：

```gdscript
func load_theme_or_null(path: String) -> Theme:
	if not ResourceLoader.exists(path):
		push_error("Theme 不存在: %s" % path)
		return null
	var resource = ResourceLoader.load(path)
	if resource == null or not resource is Theme:
		push_error("资源不是 Theme: %s" % path)
		return null
	return resource as Theme
```

调用方还要判断返回值：

```gdscript
var theme := load_theme_or_null("res://theme/app_theme.tres")
if theme == null:
	return
```

`ResourceLoader.exists()` 只能说明路径对应的资源文件可被找到，不能保证脚本没有解析错误、外部依赖都能加载或资源类型符合预期。

## `res://` 不能当作普通磁盘路径

`res://` 是 Godot 的虚拟资源路径。读取资源时用 `load()` 或 `ResourceLoader`；只有需要和操作系统 API 交互时，才通过 `ProjectSettings.globalize_path()` 得到绝对路径。编辑器运行时，项目目录下的 `res://` 可能可写；导出后资源可能在 PCK 中，通常不对应一个可以用 `FileAccess` 修改的普通文件，因此不要依赖向 `res://` 写用户数据。

相反，`user://` 适合 `FileAccess`、`ConfigFile` 和 `ResourceSaver` 保存用户数据：

```gdscript
var file := FileAccess.open("user://notes.txt", FileAccess.WRITE)
if file:
	file.store_string("hello")
	file.close()
```

## ResourceSaver 的版本和安全注意事项

使用 `ResourceSaver.save()` 前确认：

1. 目标路径在 `user://` 或明确可写的开发目录。
2. 资源字段使用 `@export`，否则可能不会序列化。
3. 保存返回值为 `OK`，失败时不要删除原文件。
4. 写入重要数据时使用临时文件再替换；项目的 `godot_settings_store.gd` 已采用这种原子替换思路。
5. 保存出的 `.tres` 只在资源结构稳定、确实需要 Resource 格式时使用；普通偏好设置优先沿用项目的 `ConfigFile`。

## UID、路径和版本控制

Godot 可以在资源中使用 UID 来辅助重命名后的引用，但当前项目的 `.tres` 主要是路径引用，并且文件头没有显式 `uid=...`。因此本项目的实际规则是：

- 用 Godot 编辑器移动、重命名资源。
- 搜索所有 `.tscn`、`.gd`、`project.godot` 中的旧 `res://` 路径。
- 不提交或手工编辑 `.godot/uid_cache.bin` 作为源码修复。
- 在干净导入或导出环境中重新验证资源是否存在。

## 项目级排错清单

| 错误 | 先检查 |
| --- | --- |
| `Cannot get class` | 脚本语法、`class_name`、脚本路径和 Godot 版本 |
| `Failed to load resource` | `res://` 路径、大小写、外部资源和脚本解析错误 |
| 导出后找不到资源 | 资源是否被场景或脚本引用、导出过滤规则、依赖是否在 PCK |
| 保存 `res://` 失败 | 改写为 `user://`，不要向安装目录写入 |
| 运行时样式互相影响 | 检查共享缓存，使用 `duplicate(true)` 或场景本地资源 |
