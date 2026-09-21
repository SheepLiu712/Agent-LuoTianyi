# Godot 测试精简与解耦

- 大目标：按2026-09-21用户批准方案合并六组测试，保留需求覆盖和测试独立性，不改变产品行为。
- PRD：[Godot客户端](../需求说明（PRD）/Godot-Windows客户端.md)。
- 总体设计：[客户端总体设计](../../项目说明/项目架构与接口（spec）/Godot客户端总体设计.md)。
- interface与覆盖映射：[测试契约](../../项目说明/项目架构与接口（spec）/接口文档/client_godot/testing.md)。
- 总体状态：进行中；纯测试重构，Red不适用。

## 已完成

### 2026-09-21 场景与主题契约精简

- SPEC 1c29614；本记录所在提交为Green整理提交，Red不适用。场景契约改按公开根类型/名称、setup、ready前%控件及语义属性检查；移除内部容器路径和脚本/构造反射锁定。密码/API遮蔽、原生文件选择、正文复制/换行和必要操作提示保留。
- editable_scene_children的下拉子场景来源、SecurityError与分隔场景检查迁入test_ui_scenes；动态选中样式迁入test_theme_contract，原脚本/UID及入口删除。主题保留当前色彩/圆角/状态需求，移除固定Windows字体、Shader源码和纹理生成算法镜像。
- 修改前四组基线全部通过：base 34项、accounts互操作+4项、network 5项、features 15项；设置布局、圆角下拉、完整下拉、设置状态和动态GPU均PASS。基线日志位于client_godot/artifacts/test-cleanup/before-*.log。
- 整理后test_ui_scenes和test_theme_contract逐项独立执行PASS；作者自审对照迁移表，场景、主题及产品脚本均未修改。GPU基线只代表本机Compatibility/NVIDIA环境，不代表手机或系统DPI验收。
