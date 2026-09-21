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
