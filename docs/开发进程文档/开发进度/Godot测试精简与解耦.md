# Godot 测试精简与解耦

- 大目标：按2026-09-21用户批准方案合并六组测试，保留需求覆盖和测试独立性，不改变产品行为。
- PRD：[Godot客户端](../需求说明（PRD）/Godot-Windows客户端.md)。
- 总体设计：[客户端总体设计](../../项目说明/项目架构与接口（spec）/Godot客户端总体设计.md)。
- interface与覆盖映射：[测试契约](../../项目说明/项目架构与接口（spec）/接口文档/client_godot/testing.md)。
- 总体状态：已完成本地实现与验证；纯测试重构，Red不适用。未推送、未打包。

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

### 2026-09-21 Python夹具解耦与重复编排清理

- server_crypto与tone原样迁入两个support模块，runner之间不再import。各Handler、超时、环境变量、命令行和错误判定保持原状，原服务端加密函数/旧端wire互验保留；可靠队列只在基础组直接执行。
- 四组整理后检查均通过：base 31项、accounts互操作+4项、network 4项、features 14项；release与dynamics GPU链路通过。提取前后3组WAV样本字节完全一致；两个crypto实例生成不同密钥，导入支持模块未加载runner；Python语法检查通过（正确处理仓库既有UTF-8 BOM文件）。
- SPEC 1c29614；Red不适用，Green为本记录提交。作者自审确认support没有服务启动/共享可变状态，波形样本不依赖WebSocket包，解密源码仍由文件相对仓库定位，不依赖运行目录。

### 2026-09-21 独立核验后的提示与失败诊断补回归

- 独立只读核验确认音频/缓存/动态的行为断言、独立实例/时钟/信号、随机几何路径及移动UID保留。clear的参数数量反射属于已移除的实现锁定，实际clear(-1/30/0)调用保留，不恢复反射门控。
- 场景输入/操作提示补充非空检查，保持可修改措辞；退出确认的动作与“不自动保存或发送”从实际弹框验证，不恢复运行时会覆盖的静态默认title/body。20个原场景的根/类型/setup/%入口清单逐项比较完全一致。
- 主题缺失/错误类型、分隔场景缺失时保留明确失败信息，避免测试自身访问空值；内存复制主题的缺失/错误类型探针均得到预期FAIL/退出1且无SCRIPT ERROR，未改产品资源。场景/主题独立测试及退出确认GPU测试PASS。
- 以上为整理自审与既有行为补回归，无新增产品行为或人为Red。WASAPI下合并后的回复音频混音/生命周期测试通过；不等同人工听感或真实TTS验收。

### 2026-09-21 最终验收与入口同步

- 本地提交：SPEC 1c29614；场景/主题3d9166a；模块合并55bbd18；GPU合并9defb2a；夹具解耦6840a5b；后置核验补充4937c7f。各提交已完成作者自审；独立只读核验不替代正式他人审核。
- 最后修改后重跑基础31项和功能14脚本全部PASS，账户互操作+4脚本、网络4脚本已在本轮整理后PASS；全部after日志无FAIL/ERROR/Exception。设置、下拉、动态、Application截图及退出确认GPU验证通过，WASAPI混音/生命周期通过。每个合并目标已分别独立运行。
- 统计53个test_*.gd（原59），50个由默认分组编排、3个单独图形验收；4个capture入口保留。静态检查确认20个原场景公开入口清单完整、六个被替代脚本/UID已删除、两个移动脚本UID与基线相同、所有可执行res://tests引用有效、Python runner之间无导入依赖。git diff --check通过。
- [现行入口](../../../client_godot/tests/README.md)记录分组/单脚本/GPU命令；历史架构和进度仅增加索引，不改写过去事实。产品src/scenes/theme、服务端/旧端与release.json相对5a82191均无变化；热重载DLL差异未纳入提交。
- 验证环境为本机Godot 4.7.1 Compatibility、NVIDIA GPU、Windows及本地HTTP/WebSocket夹具。移动端、Windows10、集显、真实系统DPI、多屏切换、公共服务及长期性能未在本次验证；本次未导出或覆盖交付包。
