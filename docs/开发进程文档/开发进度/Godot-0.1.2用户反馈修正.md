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

## 2026-09-20 语音缓存迁入设置、确认白框修复

- GPU复现旧确认框实际580×1073，取消按钮y=1011超出可见范围；根因为Window.wrap_controls与自动换行正文共同抬高窗口。取消wrap_controls、长正文放场景ScrollContainer后稳定580×240，底部操作可达。GPU test_decision_layout同时验证窗口/按钮范围和真实Esc输入。
- 新增设置“语音缓存”页并删除聊天顶部缓存入口；清理通过Application注入既有ChatSession.clear_cache，确认/取消、处理中和结果均由场景控件承载。只清当前账号，不参与保存全部或dirty判断。
- SPEC 0ac9c1d；Red 9becd67；Green为本记录提交。test_audio_settings headless/GPU均PASS，真实缓存文件验证取消保留/确认清理/结果文案；test_ui_scenes、test_voice_chat、test_unified_settings均PASS。GPU截图为artifacts/audio-settings-confirm.png。
- 作者自审：原白框有真实尺寸复现，不以pressed信号可触发代替按钮可见性；无新的缓存存储或清理策略，不写其他账号数据。

## 2026-09-20 原客户端模型用途卡片

- 模型页按服务器返回用途实例化场景卡片，调用要求与说明常显；勾选“使用自己的API Key”才展开字段，收起保留草稿。服务商、地址、Key和模型启用时必填；复制、能力、高级JSON和明确确认后的手动测试保留。
- 整窗全量预校验、部分成功更新基线/失败留稿规则不变；错误写回对应卡片和底部结果栏。新增刷新需求列表，无草稿才可刷新，刷新失败可重试。保存成功同步卡片与基线，避免旧格式参数造成伪dirty。
- SPEC bba8144；Red 7589cc1；Green为本记录提交。test_model_cards在GPU/loopback通过卡片数、独立展开/折叠留稿、必填校验、整窗保存与刷新；test_ui_scenes、test_editable_scene_children、test_unified_settings和test_model_settings回归PASS。
- GPU截图artifacts/model-purpose-cards.png和model-purpose-expanded.png已核查；底部操作栏固定，长表单滚动。用途数量来自fixture，不把两卡写死为正式服务用途数。
- 作者自审：卡片只负责控件绑定与信号，页面汇总草稿，ModelSettings保留存储/校验；没有供应商自动调用或服务端接口变更。

## 2026-09-20 导航对齐与原项目图标

- 五个主导航入口统一左对齐、相同内边距；普通/悬停/选中浅蓝底略加深，未读数字不改变文字起点。标题栏改用原项目SVG的TextureRect，运行窗口与Windows导出设置同步原项目SVG/ICO。
- SPEC fcdbb46；静态样式/导出配置的Red不适用，Green为本记录提交。复制资源与client/res/gui原SVG/ICO的SHA-256一致；Godot导入、临时release导出及导出启动均PASS。直接读取导出EXE的PE图标资源，6帧全部与原ICO图片数据逐字节一致。
- GPU capture_release_ui全流程PASS，新主界面截图已核查导航对齐/配色和标题栏原图标。临时导出位于隔离验证目录，未覆盖现有0.1.2交付包。
- 作者自审：只变更Godot场景/主题和图标配置，无脚本创建UI；原项目图标文件不修改。

## 2026-09-20 正式图片发送

- 选图按钮/原生文件选择器、Ctrl+V、附件缩略图/查看/移除均接入正式ChatView，待发图片参与退出草稿保护；全局图片窗显式确认发送，关闭仍保留附件。主发送键先接受图片再发送文字，失败保留未接受内容。原图预览去掉离线固定文案。
- 校验PNG/JPEG/WebP、BMP转PNG及剪贴板PNG，限制文件/协议包与解码像素；通过原user_image及瞬时选择/取消事件发送。图片与文字共用历史边界等待及原可靠队列，ACK保留稳定本地ID；图片接受发送后存入现有按账号图片缓存，未提交附件不落盘。
- SPEC 96accf8、a8da89e；Red 6b42bc7；Green为本记录提交。test_image_attachment通过格式/文件/大小/MIME/像素校验；test_image_sending headless/GPU通过真实协议、历史屏障、图片回执、本地图预览、粘贴/移除/确认、失败留稿与退出清理。test_history_sync、test_history_media、test_ui_scenes、test_preview_input及GPU test_image_window均PASS。
- 作者自审：沿用现有协议和outbox，不把选择成功当送达；不发送本机绝对文件路径，缓存缩略图仍有24张上限。当前图片格式范围已在使用说明明确，未验证公共服务真实图片处理或计费VLM。
