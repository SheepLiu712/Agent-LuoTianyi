# Godot 界面精简与状态修正

按用户2026-09-21批准的六项修正计划执行。当前契约见[feedback-012](../../项目说明/项目架构与接口（spec）/接口文档/client_godot/feedback-012.md)最后一节，仅记录完成事实。

总体状态：六项修正已完成本地实现与验证；仅本地提交，版本与已有交付包未改变。PRD：[Godot客户端](../需求说明（PRD）/Godot-Windows客户端.md)；总体设计：[客户端总体设计](../../项目说明/项目架构与接口（spec）/Godot客户端总体设计.md)。

## 动态详情文字精简

- 删除CommentTitle节点及其占位，成功评论/回复不再显示成功状态文字；空状态区隐藏，失败与结果不确定仍保留草稿及明确提示。
- SPEC 3e96eca；Red 4568bfa，确认因标题和成功提示仍存在而失败；Green为本记录提交。
- 真实loopback test_comment_feedback覆盖成功、503失败、连接中断结果不确定；test_dynamics_detail及test_ui_scenes均PASS。作者自审确认评论隐私、分页与回复行为未变，无新增平台调用。

## 主导航与设置底栏

- 主导航仅保留四个居中按钮，删除账号菜单。导航最小宽度106px保持此前账号菜单撑开的实际宽度；底色和按钮高度不变。
- 设置底部左侧退出登录、右侧关闭/保存全部，logout_requested交应用统一处理。默认说明删除；状态区初始隐藏，保存中/完成/失败显示结果，再次编辑清过期成功。长结果可滚动，页面阻挡层不覆盖底部按钮。
- SPEC 3e96eca；Red dfc9e1a；Green为本记录提交。test_main_navigation、test_application_drafts、test_unified_settings通过；真实GPU草稿测试覆盖文字/图片/设置/动态、取消留稿、保存中请求退出及日志保留。账户窗口回归验证无草稿退出与重新登录，最小设置GPU布局PASS。
- 作者自审：新入口只发信号，不直接处理账户或平台调用；独立AccountForm测试入口未误删，StorageService不变。

## 设置只读输入与开关状态

- 统一主题补齐LineEdit/TextEdit只读浅色实底和文字色；读取中、读取失败和保存中仍禁止编辑。CheckBox明确六种状态，API/JSON/thinking共用深色文字、浅蓝选中底和深蓝焦点描边。
- SPEC 3e96eca；Red 8ddce93，旧主题在延迟读取时实际GPU像素为深色，选中悬停文字不符；Green为本记录提交。实现仅修改主题资源，新增测试纳入check_features，附Godot生成的测试UID。
- 2026-09-21重跑test_settings_control_states（真实loopback、RTX 4070 Laptop GPU）：PASS。覆盖初次读取、503失败/重试、保存/恢复编辑、六种开关状态及默认/最小窗口100/125/150/200%内容缩放，底部操作均在可视范围。截图位于client_godot/artifacts/ui-refinement。
- check.ps1全部34项通过，含主题/场景/导航/存储/缓存回归。当前Godot 4.7.1运行时确认checkbox_checked_color及checkbox_unchecked_color均为有效主题项；作者自审未发现新增平台调用、提前开放表单或运行期创建控件。
- 本机GPU验证不代替真实系统DPI、多屏、Windows10、集显或手机端验收。

## 退出登录确认框的来源窗口与复用

- GPU补查复现：独立设置聚焦时，共用ExitDialog仍嵌入主窗口；visible和dialog.has_focus并不能证明在设置窗口可见。修正由Application在显示前把同一场景确认框归属当前触发窗口，取消/完成及关闭业务窗口前收回，不增加控件或新公开接口。
- SPEC d56bb66；Red 1d22e27：test_logout_confirmation实际失败于来源窗口和窗口内可达范围；Green为本记录提交。测试从设置视口注入鼠标点击退出与确认按钮，检查取消默认焦点、宿主与按钮范围，并截取settings-logout-confirm.png；覆盖取消、关闭重开设置、主窗退出切换、确认登出/日志保留、重新登录和保存失败后取消退出。
- GPU与headless均PASS；test_application_drafts GPU复测PASS，覆盖文字/图片/设置/动态草稿、取消保留、保存成功后退出和日志保留。作者自审：确认框收回先于业务窗口释放，保持一个汇总提示；不修改StorageService、服务端协议或平台适配。

## 2026-09-21 整体回归与文档同步

- 初始SPEC 3e96eca已覆盖批准的六项行为；评论Red/Green为4568bfa/cae615b，导航与底栏为dfc9e1a/91542b2，主题为8ddce93/1377173。各片已完成作者自审；独立只读审查不替代正式他人审核。
- 最终Application修改后重跑check.ps1（34项）、check_features.ps1（15个测试脚本）、check_accounts.ps1（互操作+4个账户脚本），全部通过；check_network.ps1（5项）已在本轮通过。日志未见FAIL/ERROR/Exception。git diff --check通过。
- 本机Godot 4.7.1 Compatibility / RTX 4070 Laptop GPU：设置加载/503失败/重试/保存、开关六态、默认/最小窗口100/125/150/200%内容缩放通过；主界面和动态GPU截图核对四入口居中与删除文字无占位。原生HWND验证动态/日志独立、设置随主窗最小化通过。确认框来源修正另有上述最终GPU回归。
- 证据保存在client_godot/artifacts/ui-refinement及其validation目录；GPU主界面/动态截图在client_godot/artifacts。可复跑命令见client_godot/README.md；新增确认框测试使用run_feature_tests.py --script res://tests/ui/test_logout_confirmation.gd --gpu。
- README、PREVIEW、PRD和窗口interface已同步（019467c）。[历史平台调用专项](../问题跟踪/Godot历史平台调用迁移.md)独立记录，未在本轮迁移。对比本轮src差异未新增OS/FileAccess/DirAccess/ClassDB直接调用；UI仍由场景提供。
- 未验证真实系统DPI切换、多屏移除、Windows10、集显、Android/iOS构建与真机、公共服务及长期性能；不把本地接口或内容缩放测试当作这些验收。未打包、未覆盖旧包、未推送。
