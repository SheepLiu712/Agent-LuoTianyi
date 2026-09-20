# Godot 客户端窗口重设计

- 大目标：统一所有应用窗口操作、依附关系、草稿保护与现代视觉。
- PRD：[Godot Windows客户端](../需求说明（PRD）/Godot-Windows客户端.md)
- 总体设计：[客户端总体设计](../../项目说明/项目架构与接口（spec）/Godot客户端总体设计.md)
- interface：[窗口重设计](../../项目说明/项目架构与接口（spec）/接口文档/client_godot/window-redesign.md)
- 总体状态：本地实现与可执行验证已完成；跨设备平台矩阵尚未全部验收（具体边界见末条记录）。

## 已完成

### 2026-09-20 自绘窗口框架与几何

- 交付：主窗及现有业务窗口使用共用场景标题栏三键、系统拖拽/八边缩放；独立几何按键保存并约束到显示器可用范围，紧凑/展开分开记忆，重新打开恢复最小化前模式。
- SPEC b9821ef；Red 397ac07（框架资源不存在时明确失败）；Green 为本记录所在提交。契约见 window-redesign.md「自绘窗口框架与几何」。
- 验证：Window chrome 在 headless 与真实GPU窗口均PASS；几何跨键保存、负坐标及屏幕外恢复通过；check.ps1原24项、check_features.ps1全部通过；修复首次headless默认64×64污染紧凑布局后test_application_window与Window chrome再次PASS。
- 作者自审：明确保留宿主close_requested而非绕过草稿保护；未覆盖引擎回调。实际拖拽贴靠、八向缩放及不同系统DPI将单独验收，本记录不声称已验证这些鼠标动作。
- 未验证：Windows10、多屏硬件、集显和公共服务；仅本地提交。

### 2026-09-20 统一设置与场景化确认

- 交付：一个设置Window承载相处/模型Control页；所有修改统一预校验、保存和逐项结果提示；部分失败留稿、跨页留稿、保存期间关闭等待、全部成功才关闭。删除旧独立设置窗装配和资源。
- 所有确认界面改为decision_dialog.tscn，自绘取消/确认/保存并关闭/×按钮均预先存在于场景；旧脚本new确认框及add_button路径删除。此为用户追加的全部UI由Godot控件场景绘制要求。
- SPEC a29cfbd、de0ecb4；Red 9af2176（统一设置资源缺失）；Green为本记录所在提交。新增whole-window测试使用真实模型/偏好控制器与外部loopback HTTP故障fixture，覆盖非法JSON阻止所有写入、部分失败/重试、取消和保存中关闭；JSON解析失败不输出引擎错误。
- 验证：check.ps1 25项、check_features.ps1（含统一设置）全部PASS；真实GPU capture_release_ui PASS。曾有一次GPU启动超时，独立chrome GPU检查通过后重跑截图成功，不把超时记为通过。
- 作者自审：保持DPAPI显式选择、原接口业务逻辑和草稿隔离；新增确认场景与设置页/宿主是本次完整切片所必需，场景迁移占主要diff，未改服务端。
- 未验证：真实OS DPI、多屏硬件、Windows10、计费供应商和长期性能；仅本地提交。

### 2026-09-20 动态内发布浮层

- 交付：发布器改为动态窗口内部的场景浮层，含固定遮罩、正文、状态、关闭/取消/发布和场景确认框；不再创建原生发布窗。沿用controller.publish与published信号，父窗dirty仍汇总评论和发布草稿。
- SPEC cbaf65e；Red f911260（原发布控件属于不同Window，测试真实失败）；Green为本记录所在提交。
- 验证：test_dynamics_window、test_dynamics_detail、test_ui_scenes通过；成功发布选中、新旧草稿保留、失败显式提示均回归。作者自审确认所有UI是.tscn控件，遮罩外点击不触发关闭，Esc按当前层级请求关闭。
- 未验证：公共动态服务、真实系统DPI与多屏硬件；仅本地提交。

### 2026-09-20 无边框窗口恢复修复与动态原生验收

- 根因证据：窗口自身最小化后，仅切mode会使Godot报告visible=true而HWND缺少WS_VISIBLE；主窗最小化前就已经隐藏，并非主窗直接隐藏独立动态。
- Red 7769920通过公开open()复现；Green为本提交，WindowChrome恢复最小化窗口时先hide再恢复mode/show，使原生可见表面重新建立。
- GPU capture_dynamics_ui全部截图通过；真实HWND可见、非最小化、无owner、非TOOLWINDOW检查PASS。发布浮层在动态内部显示且未新增原生发布窗。作者已核查原生状态和实际测试输出；未把内容缩放当作真实系统DPI。

### 2026-09-20 全局单例图片窗口

- 交付：ImagePresenter创建/复用image_window.tscn，窗口转属当前来源，换图适应、原始比例、缩放、错误重试和关闭由场景控件提供；旧图片浮层资源删除。正式历史与离线待发送图片共用同一呈现约定，退出账号清回调与纹理。
- SPEC 32e5b22；Red 8f3ed19（独立图片场景缺失）；Green为本记录所在提交。
- 验证：test_image_window headless/GPU均PASS，覆盖单例转属、旧来源关闭不影响新来源、当前来源关闭释放、失败重试、原始比例、关闭释放纹理；GPU额外验证来源最小化/恢复。test_history_media真实loopback、test_preview_input、test_ui_scenes通过。
- 作者自审：图片窗仅存几何，原始图片仍由会话接口/离线provider提供，无新增协议；confirm回调仅离线显式点击，未后台发送。所有可见控件在场景中，代码只绑定与实例化。
- 未验证：实际系统DPI、Windows10、多屏硬件；仅本地提交。

### 2026-09-20 主导航与完整草稿汇总

- 交付：左侧场景导航集中聊天/动态/统一设置/日志/账号，账号明确区分退出登录与退出应用；聊天顶部保留缓存入口，删除旧业务菜单转发路径。账户长表单滚动、注册/重置可明确返回登录。分栏按扣除导航后的可用宽度计算45:55。
- 主窗一次汇总聊天输入、设置、动态发布/评论；取消保留全部，确认放弃才退出。设置正在保存先等待结果。退出登录保留已打开的日志，关闭其它业务窗；重复打开设置保留所选页面。
- SPEC 44f8582；Red 4fcea0e（固定导航和聊天dirty契约缺失）；Green为本记录所在提交。
- 验证：check.ps1 27项、check_accounts、check_features、check_network全部PASS；Application drafts从真实loopback登录验证一次性汇总、取消留稿、退出账号保留日志；GPU capture_release_ui PASS。修复退出过程中控制器发未读信号时导航节点已释放的生命周期问题，回归无引擎错误。
- 作者自审：服务仍由Application注入，未新增全局service locator或协议；控件仅从场景取得。系统DPI、多屏与公共服务器未验证；仅本地提交。

### 2026-09-20 视觉统一、原生交互与验证收尾

- 交付：浅色场景标题栏/导航、主题圆角面板与焦点状态、实底聊天及表单、浅工具栏与深色日志正文。磨砂材质只采样应用Viewport；以屏幕纹理mipmap连续模糊修正发布遮罩的离散采样重影，无背景采样时使用同配色实底。波形替换为场景中24个预置控件，脚本只绑定数值。
- 修复：设置720×640时相处页底部被固定操作栏遮挡，增加场景ScrollContainer与焦点跟随；滚动后重新加载可达，保存/关闭栏保持可见。全部可见UI、确认按钮和测试语音场景均从.tscn取得，独立只读审查未发现产品代码创建可见控件或旧窗口活跃引用。
- SPEC bb94956，补充2822bbe；视觉Red 481a44c，最小布局Red 8249c5f；Green为本记录所在提交。最小布局测试初版headless无法反映可见原生窗口滚动，最终改为GPU专用，并在隔离副本再次验证旧场景FAIL、新场景PASS；不把headless布局结果作为视觉证据。
- 原生修正：标题栏统一48px、移动4px后才开始系统拖动；兼容引擎无边框最大化报告FULLSCREEN的实际行为，保留还原矩形。最小化子窗口恢复时重新建立可见表面；主根窗口不能hide，单独恢复mode。关闭保存几何后进入宿主草稿流程。设置显式跟随主窗隐藏/恢复，不把transient或GW_OWNER当作行为证明。
- 验证环境：Godot 4.7.1.stable.official.a13da4feb，Windows图形会话，Compatibility，NVIDIA RTX 4070 Laptop GPU；独立临时工程及AgentLuo-UI-Review-xpd5_wzy用户目录，无生产凭据/公共服务写入。
- 自动化：check.ps1全部28项PASS；check_accounts/check_network在本切片回归PASS；相处布局修改后重跑check_features全部PASS（历史、媒体、动态、统一设置、主窗草稿、模型保存与委托）。统一设置包含全量预校验、部分失败/重试、取消及保存中关闭。
- GPU：capture_release_ui、capture_dynamics_ui、capture_voice_ui、test_image_window、test_settings_layout均PASS；核查主窗默认/最小及125/150/200%内容缩放，设置、日志、动态发布与语音截图。实际HWND证明主窗最小化后动态/日志仍可见，设置隐藏并恢复；图片来源转属及随来源最小化/关闭通过。
- 原生输入：test_native_window_controls通过真实鼠标/键盘验证拖动、双击最大化/还原、八方向缩放、最小化与系统恢复、最大化/还原按钮；关闭按钮与Alt+F4共收到两次同一路径请求。native-window-controls.json为ok=true。
- 短时性能：1200×800各90帧，磨砂中位4.997ms/P95 5.152ms、实底中位5.016ms/P95 8.975ms；Godot静态分配均约71.4MB、绘制调用236/235。样本存在调度噪声，不据此宣称磨砂更快；不是进程总内存、显存或长期性能测量。
- 证据：[主界面](../../../client_godot/artifacts/window-redesign/agentluo-redesign-chat.png)、[发布浮层](../../../client_godot/artifacts/window-redesign/agentluo-011-dynamics-publish.png)、[最小设置](../../../client_godot/artifacts/window-redesign/agentluo-redesign-settings-minimum.png)、[本地验证汇总](../../../client_godot/artifacts/window-redesign/verification.md)。截图/JSON/检查日志保存在Git忽略的artifacts/window-redesign，源代码中保留可复运行的测试。
- 作者自审：已核查场景/主题资源、行为diff、测试证据与文档一致；保留场景节点和行为脚本分离，未改服务端协议、release.json或旧发布包。本轮只有本地提交，无push/PR；作者自审不替代他人审核。
- 未验证：Windows10、真实系统DPI切换、跨显示器及显示器移除、Windows贴靠动作、集显、长期性能/内存、真实中文输入法组合键、公共服务和安装发布包。模拟显示器矩形/内容缩放/截图不替代这些实机验收。
