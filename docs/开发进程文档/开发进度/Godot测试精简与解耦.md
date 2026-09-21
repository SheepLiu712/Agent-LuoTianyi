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

### 2026-09-21 音频、缓存和动态按职责合并

- 回复音频和生命周期合为media/test_reply_audio，缓存持久化与天数清理合为storage/test_audio_cache，保留目标原UID。每组使用独立被测实例；生命周期时钟/信号集合不复用混音场景，缓存两组临时目录分开。clear(days)以真实调用验证，去掉参数数量反射。
- 旧test_dynamics_window的写接口验证归入test_dynamics，发布失败/草稿/窗口生命周期归入test_dynamics_detail；两组重新创建控制器及窗口。详情几何文件从固定名称改为本次独占名称，消除跨运行依赖。
- 删除三个被替代脚本及UID，更新check入口和音频README命令。四个合并目标分别独立运行PASS（真实Godot混音/缓存及本地动态HTTP夹具）。SPEC 1c29614；Red不适用，Green为本记录提交；作者自审确认原独有断言保留，产品代码不变。

### 2026-09-21 GPU布局与圆角验证合并

- 设置最小布局并入test_settings_control_states的GPU分支，四档缩放均实际滚动Reload并检查视口/底栏可达范围；保留原检查的布局稳定等待。圆角背景/像素检查并入capture_dropdown_ui，保留圆角截图、原键盘/边界/移动收起行为；headless明确退出2，不能冒充视觉通过。
- 删除两个原GPU脚本及UID，更新README。Settings control states与Dropdown native screenshots独立GPU执行均PASS；已查看最小设置图确认Reload完整可见、底栏无覆盖。证据after-settings-gpu.log/after-dropdown-gpu.log位于artifacts/test-cleanup。
- test_*.gd数量为53（原59）；未注册的其余GPU/原生验收保留。SPEC 1c29614；Red不适用，Green为本记录提交；作者自审确认没有把headless结果当GPU结果，产品资源未变。
