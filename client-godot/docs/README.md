# Godot Windows 客户端现行说明

当前源码版本为 **0.2.0.0**，版本权威为 `release.json`、`project.godot` 与 `export_presets.cfg`。文档及测试保存在客户端内，不依赖上游已移除的进度/spec 目录；本地个人笔记不随仓库分发。

## 阅读入口

- [日志规范](logging.md)：四域日志、字段、隐私、保留、导出与检索。
- [打包规范](packaging.md)：目录版、ZIP、单文件自解压、版本字段、图标与发布验证。
- [测试与门禁](testing.md)：依赖、四组入口、GPU 与验收边界。
- [原生 DLL 解析](native-dll.md)：`windows_security.dll` 的 PE 结构、四个源码文件、构建与 GDScript 调用链。
- [开发者查看 SQLite](dev-database.md)：数据库路径、VS Code 插件、表结构与 WAL 注意事项。
- [PR #186 整改归档](../../archive/worklog/pr-186/)：按轮次保留的历史记录；最新状态以 PR 评论与当前 head 为准。
- [PR 描述修正稿](../../archive/worklog/pr-186/pr-description-current.md)：提交推送后用于更新远端描述。
- [测试目录说明](../tests/README.md)：单脚本及截图入口。
- [构建与使用](../README.md)：锁定工具链、版本同步与便携包要求。

## 交付边界

客户端为独立 Windows x64 工程；现行改动不修改服务端、旧客户端或用户存储格式。版本与打包由 `release.json` 和 `scripts/build.ps1` 控制。触摸事件改用协议文档已规范的 `touch_area` 等 snake_case 字段名（服务端本就优先读取该名），属于对齐既有契约而非新增协议。公共服务、多屏、系统 DPI、Windows 10、集显、长期性能与移动端需另外验收。截图、历史 ZIP 和复杂度通过均不能代替相应行为验证。
