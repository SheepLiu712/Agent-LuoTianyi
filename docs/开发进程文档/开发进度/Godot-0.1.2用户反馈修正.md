# Godot 0.1.2 用户反馈修正

问题范围及未完成项见[问题跟踪](../问题跟踪/Godot-0.1.2用户反馈.md)，本文件仅记录完成事实。

## 2026-09-20 角色默认睁眼

- 修复原眨眼仅在0.18秒窗口内写入、结束后不恢复的问题：默认睁眼，每次眨眼回到表情对应的开合值；ease等明确闭眼表情保留，回normal恢复。口型不改变眼睛规则。
- SPEC 2c7e79a、Red 6fc4daa，Green为本记录提交。get_status只读暴露实际eye_openness，无插件对象泄漏。
- 真实模型test_eye_restoration与test_avatar_driver通过，覆盖跨完整眨眼周期、闭眼表情与normal/口型恢复；GPU角色场景截图另行核查。所有测试使用隔离APPDATA。
- 作者自审：只修改角色眼部恢复及诊断状态，不修改旧资源、其他业务或已发布0.1.2包。

## 2026-09-20 真实模型触摸与眼部跟随

- 按原Moc文件的drawable-parentPart关系配置头/手/身体映射，由AvatarDriver检查实际可见网格三角形；视图坐标通过模型变换换算，背景点击无反馈。触摸圆环使用Panel场景，0.5秒渐大/淡出。眼球按旧端60Hz下0.15插值追踪鼠标，离开/失焦回正。
- Application连接触摸信号至ChatSession，ready时最多每秒一次合并区域及次数，通过既有瞬时user_touch协议发出；在线声音播放时本地反馈保留但清理累计、不上报，退出/断线清理。
- SPEC e116c42；Red 5601b16、c1946da；Green为本记录提交。GPU test_avatar_interaction通过真实网格头/手/身体与背景、视线跟随/回正、圆环出现/释放；loopback test_touch_delivery通过协议、冷却合并、在线语音抑制和重新登录清计数。
- headless根窗口报告MODE_MINIMIZED，角色按产品规则停绘，因此完整视图交互测试仅用于GPU，不通过修改产品停绘规则迁就测试。眨眼基础测试仍可headless验证独立驱动。
- 作者自审：未给旧资源加臆测HitArea或矩形热区，映射附Moc SHA-256及Core API来源，未新增原生扩展或改变服务端协议；可见反馈由场景控件绘制。
