# Godot 界面精简与状态修正

按用户2026-09-21批准的六项修正计划执行。当前契约见[feedback-012](../../项目说明/项目架构与接口（spec）/接口文档/client_godot/feedback-012.md)最后一节，仅记录完成事实。

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
