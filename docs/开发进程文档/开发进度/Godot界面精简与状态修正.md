# Godot 界面精简与状态修正

按用户2026-09-21批准的六项修正计划执行。当前契约见[feedback-012](../../项目说明/项目架构与接口（spec）/接口文档/client_godot/feedback-012.md)最后一节，仅记录完成事实。

## 动态详情文字精简

- 删除CommentTitle节点及其占位，成功评论/回复不再显示成功状态文字；空状态区隐藏，失败与结果不确定仍保留草稿及明确提示。
- SPEC 3e96eca；Red 4568bfa，确认因标题和成功提示仍存在而失败；Green为本记录提交。
- 真实loopback test_comment_feedback覆盖成功、503失败、连接中断结果不确定；test_dynamics_detail及test_ui_scenes均PASS。作者自审确认评论隐私、分页与回复行为未变，无新增平台调用。
