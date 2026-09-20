# Godot 客户端窗口重设计

- 大目标：统一所有应用窗口操作、依附关系、草稿保护与现代视觉。
- PRD：[Godot Windows客户端](../需求说明（PRD）/Godot-Windows客户端.md)
- 总体设计：[客户端总体设计](../../项目说明/项目架构与接口（spec）/Godot客户端总体设计.md)
- interface：[窗口重设计](../../项目说明/项目架构与接口（spec）/接口文档/client_godot/window-redesign.md)
- 总体状态：进行中

## 已完成

### 2026-09-20 自绘窗口框架与几何

- 交付：主窗及现有业务窗口使用共用场景标题栏三键、系统拖拽/八边缩放；独立几何按键保存并约束到显示器可用范围，紧凑/展开分开记忆，重新打开恢复最小化前模式。
- SPEC b9821ef；Red 397ac07（框架资源不存在时明确失败）；Green 为本记录所在提交。契约见 window-redesign.md「自绘窗口框架与几何」。
- 验证：Window chrome 在 headless 与真实GPU窗口均PASS；几何跨键保存、负坐标及屏幕外恢复通过；check.ps1原24项、check_features.ps1全部通过；修复首次headless默认64×64污染紧凑布局后test_application_window与Window chrome再次PASS。
- 作者自审：明确保留宿主close_requested而非绕过草稿保护；未覆盖引擎回调。实际拖拽贴靠、八向缩放及不同系统DPI将单独验收，本记录不声称已验证这些鼠标动作。
- 未验证：Windows10、多屏硬件、集显和公共服务；仅本地提交。
