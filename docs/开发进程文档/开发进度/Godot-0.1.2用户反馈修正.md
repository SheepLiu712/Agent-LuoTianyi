# Godot 0.1.2 用户反馈修正

> 历史测试路径保留原完成事实；2026-09-21测试整理后的现行命令见[测试入口](../../../client_godot/tests/README.md)，迁移与验证见[测试精简进度](Godot测试精简与解耦.md)。

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

## 2026-09-21 系统窗框与Godot圆角下拉

- 用户选择恢复系统标题栏与三键，主窗及独立业务窗由系统提供窗框/外轮廓；WindowChrome仅保留几何与关闭协调，删除旧自绘标题栏和八方向控件，并移除各页48px预留。关闭仍进入原草稿检查。
- 已阅读用户提供的CSDN文章，采用其Panel+StyleBoxFlat思路并保持场景资源化。下拉改为嵌入所属Viewport的PopupPanel、透明背景和StyleBoxFlat圆角，无遮罩/裁切Shader/原生区域；定位按逻辑坐标并为阴影预留边界，适配桌面内容缩放及未来手机Control布局。
- SPEC 79c8491；Red 12deb81；Green为本记录提交。GPU test_rounded_dropdown通过实际边角透明像素/正文不透明像素及窗口边界；capture_dropdown_ui在100/125/150%通过长菜单边界、定位、键盘和移动收起。长菜单最初超界8px，已按4px阴影修正。
- 原生鼠标/键盘测试改为读取系统标题栏按钮矩形，测试三键、拖拽、双击最大化/还原、八向缩放、系统恢复与Alt+F4 PASS。首轮拖动位置断言失败，未计通过；相同产品代码复跑完整测试通过，该次输入偏差原因未定位。
- GPU capture_release_ui通过主窗/动态/日志/设置联动与全部截图，原有可见性规则不变。未新增DWM或窗口裁切原生实现；未执行Android/iOS导出或硬件验收，不宣称客户端已完成手机移植。

## 2026-09-21 StorageService与语音缓存占用圆环

- 依用户五条原则新增统一StorageService，UI按注入路径调用接口，不直接访问OS/FileAccess/DirAccess/原生类。GodotStorageService子类负责目录统计与容量适配，未知directory/total/free为-1，真实空目录为0；字段均64位int bytes。统计不跟随符号链接，失败不把部分扫描当完整。
- StorageVolume只读查询封装Windows GetDiskFreeSpaceEx，源码含POSIX statvfs分支；在现有扩展编译注册，Windows构建和查询已验证，POSIX/移动构建尚未实测。无法提供容量的平台返回-1，界面仍能显示已知缓存大小。
- 圆环由场景TextureProgressBar、渐变纹理、圆角Panel指示点与Label组成，按参考图呈现。统计真实当前账号缓存目录/所在磁盘总容量，非零微量显示<0.01%，不可用显示--%，扫描和清理后刷新数据。
- SPEC 2c1a527；Red 43ff989；Green为本记录提交。test_storage_service通过真实字节统计、64位容量、空目录和不可用-1；test_cache_usage_ring headless/GPU通过百分比/字节文案及未知态。test_windows_security、test_pcm_decoder、test_audio_settings回归PASS。
- 原生DLL新SHA-256为b02cd546835d0f87f8b618a2b45951251de4213edb18dc7b7760d78069705f47，已同步依赖锁。作者自审确认未给UI新增平台查询、未用0掩盖不可用容量，旧交付包未覆盖。

## 2026-09-21 用户可选天数的缓存清理

- 缓存页增加整数天数输入，默认30，可输入更大天数，0明确表示全部。确认文案冻结所选天数，取消不删除，清理后刷新圆环与字节统计；没有自动定时清理。
- AudioCache/ReplyAudio/ChatSession沿用clear接口并增加可选天数参数，旧无参调用仍为全清。新增saved_at_unix元数据，旧记录使用文件修改时间；只删除严格早于截止时间的本账号完整缓存，未知时间保留。按天清理不终止当前缓存接收；全清保持原行为。清理停止本地重放，在线声音继续。
- SPEC a5fe412；Red ac0c4e4；Green为本记录提交。test_cache_retention通过旧/近期/精确边界/旧格式修改时间、其他账号、正在接收、负数拒绝、只读文件部分失败与重试、0全清。GPU/headless test_audio_settings通过真实清理、确认天数冻结、近期缓存保留、全清；test_audio_cache、test_voice_replay回归PASS。
- 作者自审：时间判断与文件删除留在存储模块，UI不读文件或调用平台接口；磁盘统计继续经StorageService，缓存清理不会隐式随设置保存执行。

## 2026-09-21 模型刷新生命周期回归

- 全功能回归发现校验失败后立即刷新时，延迟滚动回调仍持有已移出的旧卡片，报Must be an ancestor。增加节点有效性及当前滚动容器归属检查，旧卡片不再参与延迟定位。
- 原卡片SPEC已满足，使用既有test_model_cards复现失败后修复；聚焦测试和check_features完整回归全部PASS，无新增公开接口。作者自审已核对延迟回调与卡片释放顺序。

## 2026-09-21 原生窗框完整可见与最终窗口证据

- 临时导出验证发现旧客户端位置0未包含新系统标题栏，导致标题栏可能位于可见区上方。恢复/打开原生普通窗口后，使用Godot窗口装饰矩形校正到显示器可用区；用户拖动、最大化、最小化和嵌入窗口不反复套用此修正。
- SPEC 1255ef4；Red 96cf58f；Green为本记录提交。GPU test_window_chrome复现原点恢复失败后通过；系统三键、拖动、八向缩放、双击与Alt+F4完整输入回归PASS；capture_release_ui包含实际原生窗框截图，联动回归PASS。
- 原生截图工具验证目标PID与遮挡，拒绝把其他应用覆盖的画面作为客户端证据。最终临时release导出、独立启动和系统关闭通过，原项目图标与完整系统标题栏已实际查看。未覆盖旧交付ZIP。

## 2026-09-21 全项复核记录

- 当前14项反馈的本地实现已完成，用户后续的系统窗框选择与StorageService原则已纳入权威interface；问题跟踪表逐项对应实现。
- check.ps1共34项PASS；check_accounts、check_network、check_features完整分组PASS。模型页旧回调问题已修正后重跑功能分组；确认没有用旧失败日志充当通过记录。
- 实际GPU验收覆盖角色/触摸、主窗及独立窗口联动、模型卡片、图片预览与发送、最小设置、确认取消/Esc、圆角下拉、缓存圆环。系统原生三键、拖动/双击/八向缩放/恢复/Alt+F4通过；最终临时Windows release导出和独立系统关闭通过。
- 独立只读审查未发现可复现的StorageService越层、容量未知值伪0、近期/其他账号缓存误删、图片重复/错图或账号状态泄漏。主代理完成代码与截图自审；可见UI仍由Godot场景控件承载。
- 测试普通运行曾出现1个ObjectDB实例退出告警，两次独立verbose回放复测均PASS且未复现；日志保留，长期内存/性能未获认证。
- 证据保存在client_godot/artifacts/feedback-012-final；包括原生窗框、缓存圆环、模型卡片、触摸、图片和下拉截图、原生操作JSON及检查日志。只做本地提交；正式旧0.1.2包未覆盖。Android/iOS、POSIX构建、多屏、真实OS DPI、Windows10、集显、真实IME和公共服务未验证。
