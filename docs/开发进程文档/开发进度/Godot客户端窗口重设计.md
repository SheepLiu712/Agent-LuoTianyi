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
