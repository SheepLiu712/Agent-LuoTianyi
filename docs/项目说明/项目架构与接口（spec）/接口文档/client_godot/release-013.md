# 0.1.3 登录与气泡 interface

2026-09-21用户批准。仅Godot客户端、测试和文档；原服务端/旧端协议与代码不变。替代此前统一系统窗框中“未登录窗口”部分及76%定宽气泡，其他窗口关系/退出草稿规则沿用。

## 登录资料与账户状态

StorageService新增read_login_profile()->Dictionary {ok,code,data}、write_login_profile(data:Dictionary)->Error，以及read_login_token(server,username)->Dictionary {ok,code,token}、save_login_token(server,username,token)->Error、forget_login_token(server,username)->Error。基类不可用返回明确错误；query_directory的bytes/-1约定不变。

GodotStorageService(profile_path="user://account.cfg",credentials=null)实现文件原子替换与现有CredentialStore委托；未注入credentials时在实现类中取得现有WindowsSecurity并构造默认CredentialStore，不可用则返回错误，不存明文。业务/UI不调用文件或平台API。

本地profile版本2：version=2、server、username、accounts数组；条目为server/username/remember/auto_login/last_used（UTC秒）。普通文件无token/password。历史仅在成功登录后增加，按服务器隔离、最近使用优先；当前预填用户名允许尚未进入历史。旧server/username/remember配置迁移：remember=true映射两项为true，沿用既有令牌文件；原子写失败/未知版本/损坏数据不覆盖旧文件，禁止假报持久化成功。

AccountSession(api,storage:StorageService)取代直接接收CredentialStore和文件路径，唯一存储依赖是StorageService；调用者显式组装。perform(operation,server,fields,remember=false,auto_login=false)沿用原网络协议和结果，增加独立自动登录选项；auto_login要求remember。get_login_defaults返回当前server/username/remember/auto_login及storage_error。get_history(server="")返回该服务器历史副本，不含token。select_account(username)、remove_account(username)、set_login_options(username,remember,auto_login)返回{ok,code,storage_error}，不登录；操作忙碌时拒绝，失败显式报告。

login_saved(username)显式使用该账号令牌登录；resume()仅启动时尝试当前选中且两项均开启的账号，不遍历其他记录。成功保存轮换令牌；401或无法解密清除当前账号记住/自动状态并提示密码登录；普通网络失败保留凭据。logout仅清当前账号令牌及两项状态、保留历史，其他账号不变。取消记住同时取消自动并清令牌；删除记录只动本地登录资料，不删聊天/语音/服务端账号。无法安全保存时保留本次在线会话并明确storage_error，不降级明文。

AccountApi.probe_server(address)->Dictionary复用既有HTTP客户端：规范化后GET /auth/public_key，验证成功响应包含非空公钥；不发送用户凭据、不改服务端，沿用超时、禁止重定向、busy和cancel代次隔离。AccountSession.set_server(address)异步验证后原子保存地址，成功才切换至该服务器最近账号；失败/取消保留原服务器。恢复默认只填入编辑草稿，不自动应用。

## 登录场景与平台入口

AccountForm.setup(session)保留注入；公开log_requested、feedback_requested、exit_requested信号交Application处理。select_mode("login"|"register"|"reset")切换同窗页面，返回时保留用户名、清密码/确认/邀请码。注册与重置仍使用原字段与路由，成功回登录、填入用户名、不自动登录。新增场景固定控件提供顶部菜单/关闭、账号历史、两项勾选、记住状态提示/使用密码登录、底部忘记密码/注册、服务器编辑弹层及移除记录确认。

菜单只有设置服务器/日志/问题反馈，锚定右上按钮下方，点击外部/Esc收起。服务器弹层验证保存/恢复默认/取消，Esc取消在途验证且不能提交迟到结果，遮罩不关闭。请求期间禁用重复提交/改服务器，日志和反馈可用。浏览器服务ExternalLinkOpener.open_project()->Error由GodotExternalLinkOpener实现OS.shell_open固定项目URL；UI只发信号，不直接调用OS，失败显示可选择的URL与说明，不将浏览器能力放入StorageService。

纯白实底、无渐变，主题蓝色操作与焦点，透明桌面窗口+StyleBoxFlat圆角外轮廓，无裁切遮罩/Windows圆角插件。默认480×690，固定尺寸、空白标题区域可用Window.start_drag拖动，双击不最大化。小屏将窗口限制到可用区，表单滚动、顶部控制可达。静态头像由既有Live2D默认睁眼头部导出为资源，不在登录页运行模型。

WindowChrome.set_login_mode(enabled)管理未登录的borderless/transparent/transparent_bg/unresizable及恢复系统窗框；main场景/项目启动默认登录形态，避免首帧系统窗框/黑底。登录布局单独保存位置，不恢复旧compact最大化或尺寸；登录后恢复expanded几何与原最小尺寸，退出恢复登录形态。日志仍为独立系统窗口并跨登录保留。所有固定UI在tscn，样式在主题，脚本仅行为/布局绑定。

## 气泡与历史图片

MessageBubble既有configure/update_message/set_audio_state/set_image_state不改调用形式。文本自然宽度按实际字体排版和换行测量，加面板内边距；最大外宽min(消息行宽×0.90,消息行宽−头像宽−间距)。短文无140px/76%强制下限，长文自动换行并增高、保留手动换行，长URL/英文/emoji不溢出。系统消息仍只显示居中文字；正文可选择，更新未变文字不得重建控件或清选择。

文字面板与下方语音/发送状态独立横向布局，后两者不得撑大短文背景，状态可换行。图片按original_size计算，比例min(1,可用内宽/原图宽)，高随比例自然增长，无高度上限或裁切。HistoryImages.get_state/changed新增original_size:Vector2i，ready为解码原图尺寸，idle/error为ZERO；旧消费者可忽略字段。缩略图仍限制480最长边/24张，原图查看入口与磁盘格式/协议不变。离线直接纹理取自身原尺寸。

内容/图片/窗口宽度/主题变化后刷新尺寸；虚拟列表依真实最小高度重排并保持阅读锚点，底部才跟随，不扩大常驻消息节点数量。

## 验证与交付

按存储/会话、登录场景与窗框、文字气泡、图片与锚点行为分片SPEC→Red→Green→自审。实际loopback验证正常/失败/取消、迁移/账号服务器隔离/保存失败，GPU验证菜单/纯白透明圆角/窗框切换及四档内容缩放；中文英文emoji长文、横竖小长图、延迟加载与千条历史均需回归。

版本单一来源更新0.1.3，原Godot4.7.1 Windows x64模板/build.ps1生成dist/agentluo-0.1.3及artifacts/agentluo-0.1.3.zip，保留旧包；核对导出程序真实窗口/启动/关闭、ZIP CRC/全文件哈希/双DLL/许可/版本，提供SHA-256，仅本地提交不推送。未实测Win10、真实系统DPI、多屏、手机端和公共服务明确记载。
