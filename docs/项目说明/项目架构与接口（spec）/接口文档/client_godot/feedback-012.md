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

最初交付主导航五个入口统一左对齐；此对齐和入口数已被本文最后一节“四入口居中、退出登录迁入设置”替代。NavigationButton普通/悬停/选中背景比旧浅色版略深，字体保持深色，焦点描边保留。所有修改在.tscn和主题资源中。

复用client/res/gui/icon.svg与icon.ico，复制到Godot资源目录并记录来源。项目运行图标、自绘标题栏TextureRect和Windows导出图标使用同一原项目图形，不继续用“洛”文字或Godot默认图标。此为静态资源/构建配置，无运行时Red；验证源资源哈希一致、Godot导入、GPU标题栏与导出图标。

## 正式聊天图片发送

ImageAttachment（src/media/image_attachment.gd）静态from_file(path)、from_image(Image)、from_bytes(bytes,mime)返回{ok,code,bytes,mime,texture}或{ok:false,code}。支持PNG/JPEG/WebP与BMP文件（BMP转PNG）、剪贴板图片转PNG；单图不超过服务端6MiB且为8MiB协议包预留4096字节，尺寸每边至多8192、总像素至多1600万；格式/大小/解码失败给明确错误，不排队。不读取SVG等非图片协议格式。

ChatSession.send_image(bytes:PackedByteArray,mime:String)->String校验并通过既有durable user_image发送image_base64、mime_type、image_client_path=""、llm_mode.types；拒绝返回空串并报告错误。图片和文字共同服从首次历史屏障，先显示waiting_history气泡，放行后稳定本地ID关联wire ACK；现有可靠队列重试不换ID，最终uncertain不伪报成功。stop释放待发送数据，不跨账号恢复。

HistoryImages.store_local(id,bytes)->Error将已接受发送的图片放入当前账号图片缓存，复用原24张缩略图上限及原图预览；写失败保留本次内存图片并显示CACHE_WRITE_FAILED。未确认的附件仅在ChatView本次内存驻留、不落盘；完成发送接受后才缓存。ChatSession默认构造图片缓存依赖，已注入实例优先。

ChatView增加场景ImageButton、Windows原生ImagePicker、AttachmentBar（缩略图/查看/移除）、ImageStatus。Ctrl+V和选图先成为一个待发附件并打开共用预览；关闭预览不发送，附件留在输入区可重新查看/移除。attachment_requested(provider,confirm)由Application接入现有ImagePresenter；预览“发送图片”只发附件，聊天发送键有附件时先发图片，再发非空文字；任一步拒绝保留尚未接受的内容。is_dirty包含附件。当前只接受单张待发附件，更换图片替换旧附件。

ChatSession.set_image_selecting(active:bool)在ready时发送既有瞬时user_image_selecting/user_image_selecting_cancel，打开选择器/粘贴时开始，取消选择/移除时取消，成功发送由user_image完成选择。关闭原生文件选择器不丢已有附件；退出账号清附件与回调。通用图片窗确认按钮去掉“离线演示”固定文案，失败提示适用于正式/离线两种调用，不改变显式确认语义。

ChatView.attachment_cleared通知Application在移除/发送接受后调用ImagePresenter.close_confirmation(source)，只关闭仍归属该source且具有确认操作的预览，不影响已转属或只读历史图片，防止主输入区发送后留下可重复确认的旧预览。

## 系统窗框与Godot内部圆角（2026-09-21用户选择）

用户明确选择恢复桌面系统标题栏及最小化/最大化/关闭，应用内使用Godot圆角。本条替代window-redesign.md的自绘标题栏/八边控件要求。WindowChrome保留几何持久化、布局切换、open_window和关闭保存协调；删除被替代的自绘标题栏/边缘缩放节点与输入脚本，由系统处理拖动、缩放、双击最大化、Alt+F4。宿主原有close_requested草稿规则不变。各界面移除为自绘标题栏预留的48px空白。

恢复/重新打开普通窗口后，用Godot包含系统装饰的窗口矩形校正到当前显示器可用范围，避免旧版客户端区域坐标0把系统标题栏留在屏幕上方；不在用户拖动过程中反复改位置，最大化/最小化不参与此修正。几何存储仍使用Godot客户端位置与尺寸。

原Python MainWindow为普通QWidget，外轮廓交由系统；此处同样不添加DWM扩展或SetWindowRgn。内部圆角采用用户文章 https://blog.csdn.net/datakimiko/article/details/156681420 的Panel+StyleBoxFlat方式，但节点/资源固定写在.tscn/.tres，禁止文章示例的Panel.new、_draw和逐像素纹理生成。

UnifiedDropdown的PopupPanel改为嵌入所属Viewport，透明清屏背景，圆角由StyleBoxFlat绘制；不使用遮罩、裁切Shader或原生窗口区域。弹层按所属Viewport坐标及可见范围定位，长列表滚动、键盘/Esc/外部点击、移动/最小化收起规则保留。此Control/主题路径可用于手机界面，不依赖Windows圆角API；未执行移动端导出或硬件验收。

## 统一StorageService与缓存占用圆环（任务13）

遵守用户磁盘查询五条原则：业务/UI只依赖统一StorageService，不直接使用OS/FileAccess/DirAccess/Java/Objective-C/GDExtension；平台差异仅在服务子类或原生插件。所有容量为64位int bytes；未知必须-1，不能伪造0。真实空目录为0 bytes、真实满盘可为0 free bytes。

StorageService（src/storage/storage_service.gd，RefCounted）公开query_directory(path:String)->Dictionary，字段directory_bytes/total_bytes/free_bytes/file_count均为int，未知-1，另code:String描述错误。GodotStorageService为实现子类：用Godot文件接口统计该目录，平台卷容量委托原生StorageVolume.query(path)。禁止跟随目录符号链接递归，访问失败的目录大小为-1，不返回部分扫描结果冒充完整。容量不可用时仍可报告已成功统计的缓存大小。

StorageVolume只做只读容量查询，返回total_bytes/free_bytes或-1。独立C++实现文件按平台选择Windows GetDiskFreeSpaceEx或POSIX statvfs；当前随既有Windows扩展编译，其他平台复用同接口和实现源码，需要在对应移动端构建注册，不宣称已完成手机打包/实测。缺少容量适配时GodotStorageService返回total_bytes=-1，UI正常工作并显示未知。

AudioCache.get_directory()->String提供当前账号缓存目录；Application组装StorageService并注入SettingsWindow.setup(...,clear_cache,storage_service=null,cache_directory="")，AudioSettingsPage.setup(clear_cache,storage_service=null,cache_directory="")只调用该统一接口。目录按账号隔离，退出关闭页；UI不自行寻找路径或选择平台。

缓存页采用用户图片所示的场景圆环：TextureProgressBar圆形轨道、Godot渐变纹理资源、天依蓝Panel指示点、中间百分比和扫描状态。百分比=directory_bytes/total_bytes×100，小于0.01%的非零值明确显示“<0.01%”；无法读取显示“--%”，不显示0%。同时列缓存大小、磁盘总容量和可用容量，清理后重新扫描。所有可见控件预设在.tscn，脚本只更新数值/文字/指示点位置。

## 按用户天数清理缓存（任务14）

AudioCache.clear(older_than_days:int=0)->Error、ReplyAudio.clear_cache(older_than_days=0)、ChatSession.clear_cache(older_than_days=0)增加兼容的可选参数。0保留原全部清理；正整数只删除保存时间严格早于当前UTC时间减N×86400秒的本账号完整缓存及其元数据；负数拒绝且不删除。其他账号、未满足天数的缓存、正在接收的临时流保留。全清仍终止本次缓存写入并清临时流，在线声音继续；清理操作停止本地重放以释放文件占用。

新缓存元数据增加saved_at_unix整数UTC秒，version=1兼容旧记录；旧记录缺少字段时以音频文件修改时间判定，时间未知/元数据无效不进行按天删除。AudioCache构造增加可选now_seconds:Callable时间源用于确定性测试，默认使用当前UTC时间。统计查询仍只走StorageService，业务/UI不自行访问文件或平台API。

音频缓存页增加场景SpinBox天数输入，默认30、最小0、整数步长，可自行输入更大天数；明确注明“0表示全部缓存”。确认时显示并冻结选择的天数，取消不删除；清理后刷新占用圆环，部分失败明确提示，不将保留的新缓存误称为清理失败。不做定时或后台自动清理。

## 界面精简与状态修正（2026-09-21用户批准）

此节替代此前主导航五入口左对齐、账号菜单及设置固定底部说明。

- DynamicDetail删除CommentTitle及其占位；评论/回复成功以新增内容和输入清空体现，不再显示“评论已发送”或替代弹窗。状态区无文字时隐藏，加载/失败/结果不确定/重试提示保留，评论隐私规则不变。
- 主导航仅聊天/动态/设置/日志，按钮文字水平居中，保留现有尺寸/底色。删除AccountMenu装配。SettingsWindow新增logout_requested()信号，底部左侧LogoutButton点击只发请求，由Application转入既有_request_close("logout")，不由UI直接登出；退出应用仅经系统窗口关闭流程。保存中等待、全部草稿汇总、取消留稿、退出登录保留日志与账号隔离沿用。
- 设置底部采用状态行与操作行：Result初始为空且隐藏，操作行左侧退出登录、右侧关闭/保存全部。保存中显示处理中，完成显示成功/失败；再次编辑清除过期成功提示。状态行不挤压按钮，BusyBlocker归属页面区域，不再用固定底部像素偏移覆盖可变高度底栏。
- 统一主题补齐LineEdit/TextEdit的read_only样式与对应只读文字颜色，加载、失败和保存期间保持浅色实底且不可编辑；保留加载/失败说明。CheckBox完整定义normal/pressed/hover/hover_pressed/disabled/focus及对应字体色；焦点描边#168AC2、选中底#D9F1FF、深色文字#304553，API/JSON/thinking开关一致，避免白字浅底。
- 可见控件仍固定写在.tscn，样式集中app_theme.tres。此次不扩展StorageService或服务端协议，不新增业务/UI平台直接调用；既有其他平台调用另立问题迁移。

验证通过真实loopback延迟/失败偏好读取及保存，覆盖加载中/失败/恢复、开关全部状态、默认/最小和100/125/150/200%内容缩放。新的退出入口须验证无草稿、文字/图片/设置/动态草稿、取消与保存中请求，不能仅检查信号存在。
