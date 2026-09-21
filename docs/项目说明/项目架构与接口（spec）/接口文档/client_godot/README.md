# Godot 客户端当前 interface

这里仅索引当前契约。旧窗口与场景化搬迁过程已移入[历史快照](history-before-platform-isolation.md)，不能据其恢复旧控件、构造函数或菜单。

| 职责 | 当前契约 |
| --- | --- |
| 模块边界、能力注入、应用生命周期、未来扩展 | [平台隔离](platform-isolation.md) |
| HTTP/WebSocket、回复顺序、缓存、历史、模型与动态控制器 | [核心业务契约](core-services.md) |
| 登录、账户历史、状态记忆、服务器验证、气泡与图片尺寸 | [0.1.3契约](release-013.md) |
| 窗口关系、草稿确认、统一设置保存 | [窗口契约](window-redesign.md) |
| 系统窗框、角色交互、缓存圆环和按天清理 | [反馈修正](feedback-012.md) |
| 测试职责与历史覆盖迁移 | [测试契约](testing.md) |

重叠条目的适用顺序：平台隔离规定当前装配/API边界；0.1.3规定最新账户和视觉行为；反馈修正覆盖旧自绘窗框、缓存及角色条目；其余业务行为沿用核心契约。历史完成记录不作为当前路径或接口声明。

## 当前依赖方向

场景/UI → 应用协调与业务控制器 → 明确注入的能力接口 → Godot/平台实现。

- `composition`：构造服务图和场景工厂，不管理账号业务状态。
- `application`：账号生命周期与窗口/草稿协调；主入口负责视图绑定。
- `domain`：纯地址规范化和账号作用域，无网络/文件副作用。
- `session`、`network`：业务状态与现有协议适配，不调用系统/文件/原生插件API。
- `storage`：各领域存储及实现；StorageService保留登录/容量接口，未知容量为-1 bytes。
- `media`、`avatar`：媒体行为与角色语义；原生解码/Cubism位于平台实现。
- `platform`：输入、文件交互、窗口、安全、环境及原生实现。选择不同实现不要求修改业务。
- `ui`：正式与预览共用控件，固定节点来自场景；`preview`仅承载离线样板。
- `extensions`：AppearanceService、WorldService、DeviceService，当前均明确不可用，无产品入口或协议。

运行与验证命令见[客户端README](../../../../../client_godot/README.md)和[测试入口](../../../../../client_godot/tests/README.md)。本轮只改源码，不升级或生成交付包；Android原生实现及真机验收仍未交付。
