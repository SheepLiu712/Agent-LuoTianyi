# 0.1.2 用户反馈修正 interface

本文件记录用户反馈后交付的增量契约；冲突的旧呈现约定由本文件对应条目替代。业务协议不变。

## 角色默认睁眼与眨眼恢复

AvatarDriver.load_avatar/load_character成功后使用normal表情，正常待机双眼完全睁开；周期性眨眼结束必须恢复。切换表情保留该表情对眼睛的明确配置，例如ease闭眼；回到normal恢复睁眼。语音口型不能改变眼睛规则。加载失败保留当前模型。

AvatarDriver.get_status()增加eye_openness:Vector2，读取实际模型左右眼参数；未加载返回Vector2.ZERO。它是只读状态，不暴露Cubism对象。测试通过此状态观察正常待机、眨眼后恢复、闭眼表情及回到normal。GPU画面单独核查，不以headless代替视觉验收。

## 角色视线与触摸

AvatarDriver.set_gaze(target:Vector2)接收[-1,1]的视线目标，非有限数值忽略；按旧端60Hz下0.15插值平滑、写ParamEyeBallX/Y，get_status增加gaze:Vector2实际眼球参数。AvatarPanel从本区域鼠标位置换算目标，鼠标离开或窗口失焦回正；右键拖动不触摸。

AvatarDriver.hit_test(local_position:Vector2)->Array[String]只在真实可见模型三角形命中时返回去重头/手/身体；局部坐标由视图变换，缩放/拖动后仍对应实际绘制。部件表保存在角色映射资源，按本项目Moc文件的Cubism Core drawable-parentPart关系生成，引用原端Part24/8/11、Part21及两组Skinning、Part18/17；不使用包围角色的大矩形，不新增Cubism原生接口。

AvatarPanel.touched(areas:Array[String])只在左键命中时发出，同时实例化touch_ripple.tscn：Panel圆环、忽略鼠标、半径渐变至60、0.5秒淡出并释放。固定UI仍由场景承载。

Application把touched连接ChatSession.record_touch(areas:Array[String])->void。会话ready且在线音频未播放才累计，最多每秒一次、点击触发合并上报；不改变旧端瞬时user_touch协议，payload为touchArea数组、touchCount、timeSinceLastSentTouch秒数，durable=false。在线音频期间不计数、不发送但本地圆环正常；本地重放不禁止触摸；断线/退出清理累计，禁止跨账号延迟发送。测试覆盖真实网格命中、离开回正、原协议内容/节流及语音抑制。

## 设置内语音缓存与可关闭的确认框

SettingsWindow.setup(preferences,models,executor=null,clear_cache:Callable=Callable())新增末尾可选注入，不改变旧调用。select_page增加audio；设置侧栏提供语音缓存页，替代聊天顶部CacheButton。AudioSettingsPage.setup(clear_cache:Callable)仅调用注入的ChatSession.clear_cache既有接口；无注入时禁用操作。页面说明只清当前服务器/账号完整语音、不删聊天文字、已清语音无法重放；单独清理按钮需确认，取消不清理，成功/失败留在页内明确报告，可重试。缓存操作不参与设置dirty或保存全部，不自动执行。退出账号销毁设置页，不能延续旧账号操作。

DecisionDialog不再使用wrap_controls随子控件自动增高，避免文本初始窄宽换行把窗口撑出屏幕。保持固定初始尺寸、取消默认焦点、×/Esc等同取消；长正文由场景ScrollContainer承载，底部操作始终可见。嵌入式确认背景透明，圆角由Godot StyleBoxFlat提供，不创建矩形白底遮挡。GPU验收必须实际断言操作按钮在窗口与所属窗口可见范围内，不能只发pressed信号宣称可点。

## 原客户端模型用途卡片

ModelPage保留setup/is_dirty/validate_changes/save_changes公开接口，移除用途选择器单表单，改为滚动用途卡片列表。每个用途实例化model_purpose_card.tscn，标题/调用要求/说明常显，“使用自己的API Key”勾选后展开该用途字段，取消勾选收起但保留本次草稿。服务商/Base URL/Key/模型名/能力/高级参数均来自该卡片；不写死四个用途，使用服务器返回顺序。启用用途的provider同原端一样必填。

同UI模块ModelPurposeCard.setup(purpose,draft,purposes,can_test=false)填入场景；set_draft(draft)、set_editable(enabled)、show_error(text)更新内容。edited(id,draft)/copy_requested(id,source_id)/test_requested(id,draft)由页面汇总。卡片不自行保存、不访问网络或密钥存储。错误定位对应卡片并滚动可见。

原端的整页保存映射为现有整窗保存，仍先全量预校验、逐项更新成功基线、失败留稿；保存或手动测试中禁用编辑/刷新，手动供应商请求仍明确额度确认，不包含在保存里。原复制配置功能保留且按目标用途校验。

ModelSettings.reload()复用最近start的账号/服务器重新读取需求；stop清空该上下文。UI“刷新需求列表”只在无修改且非测试/保存中可用，避免丢弃草稿；刷新失败明确显示错误并可重试。查询仍使用既有GET /llm/client-model-types，不改服务端协议。

## 导航对齐与原项目图标

主导航五个入口统一左对齐，使用相同主题内边距；动态未读数字不改变文字起点。NavigationButton普通/悬停/选中背景比旧浅色版略深，字体保持深色，焦点描边保留。所有修改在.tscn和主题资源中。

复用client/res/gui/icon.svg与icon.ico，复制到Godot资源目录并记录来源。项目运行图标、自绘标题栏TextureRect和Windows导出图标使用同一原项目图形，不继续用“洛”文字或Godot默认图标。此为静态资源/构建配置，无运行时Red；验证源资源哈希一致、Godot导入、GPU标题栏与导出图标。
