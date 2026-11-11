# Godot Windows 客户端现行说明

当前源码版本为 **0.1.7.4**，版本权威为 `release.json`、`project.godot` 与 `export_presets.cfg`。文档及测试保存在客户端内，不依赖上游已移除的进度/spec 目录；历史 `docs-godot/` 仅作参考，不作为现行依据。

## 阅读入口

- [日志规范](logging.md)：九类日志、字段、隐私、保留、导出与检索。
- [打包规范](packaging.md)：目录版、ZIP、单文件自解压、版本字段、图标与发布验证。
- [测试与门禁](testing.md)：依赖、四组入口、GPU 与验收边界。
- [开发者查看 SQLite](dev-database.md)：数据库路径、VS Code 插件、表结构与 WAL 注意事项。
- [PR #186 第四轮整改证据](../../archive/worklog/pr-186/review-186-4th-round.md)：N22–N30 的处理与真实验证结果（原文已归档）。
- [PR 描述与复审回复草稿](../../archive/worklog/pr-186/pr-186-response-draft.md)：仅供提交推送后的人工更新，不代表远端已更新。
- [测试目录说明](../tests/README.md)：单脚本及截图入口。
- [构建与使用](../README.md)：锁定工具链、版本同步与便携包要求。

## 交付边界

客户端为独立 Windows x64 工程；现行改动不修改服务端、旧客户端或用户存储格式。版本与打包由 `release.json` 和 `scripts/build.ps1` 控制。触摸事件改用协议文档已规范的 `touch_area` 等 snake_case 字段名（服务端本就优先读取该名），属于对齐既有契约而非新增协议。公共服务、多屏、系统 DPI、Windows 10、集显、长期性能与移动端需另外验收。截图、历史 ZIP 和复杂度通过均不能代替相应行为验证。
