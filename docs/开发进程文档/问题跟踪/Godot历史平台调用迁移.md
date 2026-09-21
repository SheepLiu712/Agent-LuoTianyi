# Godot 历史平台调用迁移

状态：原历史位置清单；本轮迁移事实见[平台隔离进度](../开发进度/Godot客户端平台隔离.md)，当前边界见[平台隔离契约](../../项目说明/项目架构与接口（spec）/接口文档/client_godot/platform-isolation.md)。以下保留原问题背景，不代表当前位置仍直接调用平台API。

原状态：未实施的独立专项。2026-09-21界面精简计划明确本轮只保持存储查询边界、不顺带迁移历史调用；本文件记录已发现的位置，不表示手机端已兼容。

## 现状与范围

磁盘/目录统计已通过StorageService.query_directory；GodotStorageService与StorageVolume封装平台差异，容量为int bytes、未知-1。保持该接口，不向其中塞入认证、媒体解码、Live2D或窗口能力。

本轮只读检索发现的历史调用（非全仓审计）：

| 位置 | 历史直接依赖 | 迁移时需保留的行为 |
| --- | --- | --- |
| client_godot/src/session/account_session.gd:18、93 | FileAccess、DirAccess读写账户配置 | 服务器设置与自动登录选择、原子替换、失败报告 |
| client_godot/src/media/image_attachment.gd:7 | FileAccess读取用户选图 | 图片格式/大小校验、失败保留附件、手机选图来源适配 |
| client_godot/src/media/cache_replay.gd:25 | FileAccess及原生PcmStreamDecoder | 完整缓存回放、停止释放文件、在线语音抢占 |
| client_godot/src/avatar/avatar_driver.gd:22、67 | FileAccess与Cubism原生类型 | 资源加载失败保留角色、真实模型状态和移动端插件适配 |
| client_godot/src/application.gd:53、78 | OS启动参数/日志及ClassDB插件组装 | 启动入口、诊断与依赖注入；组装根不承载具体平台实现 |

## 处理约束与验收

- 按账户持久化、图片来源、媒体、角色、启动组装分开确定统一能力接口；先确认归属及公开契约，再迁移调用者，不创建万能StorageService。
- 业务/UI只依赖统一能力接口。存储平台差异限制在StorageService子类或原生插件；其他能力由对应适配边界封装。
- 每片按SPEC → Red → Green验证正常/失败/取消及账号隔离，再删除已替代路径。
- 桌面与手机使用同一Godot客户端及同一接口；Android/iOS的插件注册、构建、真机权限与生命周期另行验收，不能以桌面测试或接口存在代替。

当前接口：[反馈修正](../../项目说明/项目架构与接口（spec）/接口文档/client_godot/feedback-012.md)。本问题未修改客户端、服务端、版本或交付包。
