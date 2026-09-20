# Godot Windows 客户端

### 2026-09-19 相处偏好与统一草稿退出确认

- 交付行为：独立非模态相处窗口、预设/自定义四字段；先读取、保存前重读合并用户修改，未知字段和服务器最新未改字段保留；性格 canonical 列表/旧文本兼容，修改后双字段写入，失败保留草稿。
- 共享 DraftWindow 关闭确认默认取消；应用退出/退出账号同样检查打开的设置草稿，确认才继续；重复入口聚焦同一窗口。
- SPEC f1584b4、b93dd38；Red cb6096b、0f634a5、9b8d13d。测试中清理不存在目录和未等待表单加载等问题分别修正，不作为有效功能失败证据；测试运行器增加 PASS 标记与 FAIL 检查，防止意外提前退出被当通过。
- 验证：真实本地 HTTP 偏好默认值、重读合并、legacy/canonical 性格、加载失败不可覆盖、保存失败保留、关闭取消；真实 Application 登录/菜单/重复打开/退出程序取消/退出账号确认通过。账户全套与日志窗口回归通过。
- 作者自审：协议取自当前 POST 路由，未保存草稿不落盘，取消隔离迟到回调，HTTP 不记录秘密和错误正文；未修改服务端。未验证公共服务器偏好及人工多 DPI 窗口。

### 2026-09-19 可见历史图片与已有语音关联

- 交付行为：历史图片可见时按 UUID 请求 /get_image，按账户/服务器缓存原图、缩略图与内置预览、失败重试、退出取消；忽略旧绝对路径，不调用路径回写接口。历史消息只为新端已有完整语音缓存显示回放，不下载旧语音，不自动播放历史。
- SPEC e6fb9af；有效 Red 18f56ca，真实 UI/音频缓存关联回归 bf3051c 另发现非待发送 ImageOverlay 创建孤立 Label 导致退出泄漏，已修正。
- 验证：真实 HTTP 图片解码、跨实例缓存不重复下载、损坏重试、账户隔离/迟到取消；真实 ChatSession 历史图片可见下载/原图预览、UUID 完整音频缓存关联及缺失缓存不可回放全部通过。退出无该控件/RID 泄漏。check.ps1 全通过，历史同步回归通过。
- 作者自审：固定本地命名、网络大小和并发边界、原子文件提交、写盘失败保留当前显示、24 张内存缩略图边界；本轮没有图片发送入口。
- 未验证：公共服务器历史图片/唱歌听感、长时真实历史性能及不同设备缓存（不导入旧端缓存）。

### 2026-09-19 本机阅读位置与一次定位

- 交付行为：服务器/账户隔离的 UUID 已读存储，首批/后台加载不推进已读，首次最新、以后定位最后已读之后，找不到说明回到最新；用户滚动/发送后提供手动定位入口；前台实际可见且定位结束才单调推进，临时回复与本地发送 ID 不落盘。
- SPEC 9b55d29；有效 Red 85bdd5c；作者自审核对读取位置前不覆盖旧值、原子写失败保留旧记录、作用域重置不修改调用方数组、无正文数据库。
- 验证：test_reading_position.gd 的规范化、跨实例、等待/后台不写、顺序不倒退、自动/手动定位、缺失锚点和账户/服务器隔离通过；历史真实 loopback 测试及网络/文字/语音回归全部通过。应用账户窗口测试通过，原生尺寸 headless 跳过。
- 未验证：跨设备（无服务端接口）、真实公共历史、系统焦点人工验收及移动端。

### 2026-09-19 千条历史可视渲染

- 交付行为：VirtualMessageList 只保留可见气泡及少量缓冲，实际高度修正和历史前插保持 UUID/偏移锚点，宽度变化重新测量；正式聊天接入，播放状态仍定向刷新。
- SPEC 82ee0ec、6498b1a（避开 Control 原生 get_anchor 命名）；有效 Red 3387ee5。最初测试解析错误不作为 Red。
- 验证：1000 条历史、节点少于 40、跳到第 500 条、前插 100 条、窗口变窄和回到最新测试通过；播放状态更新保持正文选择。真实 voice_chat 回归通过，测试改为给真实视口并滚到语音所在记录，避免要求虚拟列表渲染不可见消息。check.ps1 原有测试通过。
- 作者自审：消息快照与节点生命周期分离、气泡正文仅改变时更新，删除原无限 VBox 消息路径；未新增正文落盘。
- 未验证：本机已读恢复、历史图片、千条真实服务及 OS DPI。

### 2026-09-19 历史首批边界与发送排队

- 交付行为：登录并行建立聊天与 GET /history，首批 50 条前本地消息显示等待；固定 start_index 后释放发送并向前同步，首批失败重试/跳过、后续失败重试、UUID 合并及异常/重复提示；退出隔离在途响应，历史不触发声音/表情。
- SPEC 4011254、29b2ed3（自审修正现有 GET + Bearer 契约）；有效 Red 0129739，前期测试构造参数解析问题已修正，不计 Red；分支 feat/agentluo-0.1.0。
- 验证：run_history_tests.py 真实 loopback HTTP/WebSocket 验证 120 条固定边界、认证并行、发送 ACK 保持本地 ID、先前/后续失败、跳过、不完整页/重复、在途取消和切账号；全部通过。check_network.ps1 全通过，test_application_window.gd 账户流程通过（headless 原生尺寸恢复跳过）。
- 作者自审：首批总量未知不能凭推测校验总量，只校验已知跨度/每页数量；坏测试首批索引预期按此修正。后台控制器没有长期正文落盘、服务器修改、旧路径信任或历史音频重放副作用。
- 未验证：本条尚不包含千条虚拟列表、本机阅读位置、图片恢复、公共服务器联调。

### 2026-09-19 终端日志窗口与应用生命周期

- 交付行为：登录前按钮与聊天更多菜单打开同一非模态日志窗口；深色等宽记录、实时追加、搜索/级别/模块筛选、复制、跟随开关、历史启动选择和原生 ZIP 保存对话框。账户、发送投递及安全引擎异常进入日志，应用退出结束归档，写盘失败显示提示。
- SPEC bc13c95；有效 Red f534b36（登录前无按钮、退出未关闭日志）；作者自审核对 UI 不读日志文件、筛选不修改数据、引擎回调转主线程并舍弃原始错误内容。
- 验证：test_log_window.gd 实际应用按钮、启动第一条、重复开关、关闭标记、真实引擎警告脱敏、实时追加及搜索保留存储通过；check.ps1 全通过，账户 API/会话/视图/应用回归通过。headless 原生窗口尺寸恢复跳过已明确记录。
- 未验证：原生保存对话框人工操作、OS DPI 和公共服务；日志 GPU 截图随整体交付核验，不以无头测试代替画面。

### 2026-09-19 完整启动日志存储与诊断导出

- 交付行为：每次启动独立归档、全程记录及关闭标记，保留最近 50 次且保护活跃 PID；旧三文件保留。完整 JSONL/可读中文/环境摘要诊断 ZIP、不覆盖目标；当前写盘失败仍可内存查询并报告错误。
- SPEC ad35bb7、d95e9d5；有效 Red fcf4bf1（缺少启动记录查询），8f40718（任意 code/phase 可带入秘密）；作者自审已检查归档清理范围、已知错误码过滤与无正文日志。
- 验证：test_client_log.gd 通过跨实例、启动前段、50 次边界、活跃保护、不可写路径、全部 ZIP 条目脱敏、重复关闭及不覆盖。check.ps1 全部通过；check_network.ps1 的文字/声音链路使用新查询入口通过。
- 独立核验提出 code-shaped secret 风险，新增失败测试后修复；异常归档仍受 50 次规则，启动标记由应用立即调用，二者不属于无限保留或构造自动写盘的承诺。
- 未验证：日志独立窗口和引擎错误汇入尚不属于本条交付；本条不代表完整日志产品功能已完成。

### 2026-09-19 agentluo 版本化构建

- 交付行为：release.json 单一版本来源、运行窗口标题及版本目录 agentluo-0.1.0，程序 agentluo.exe；旧包和用户数据目录保留。
- SPEC defa465，自审确认只更新已授权需求与当前构建契约；Red 不适用（构建配置与命名切片），未伪造运行失败。
- 验证：build.ps1 使用锁定 4.7.1 引擎完成 import、release 导出及独立启动；输出 dist/agentluo-0.1.0/agentluo.exe。作者自审核对版本格式、提前拒绝覆盖 ZIP 与固定用户目录。
- 未验证：最终 ZIP 及新版全部业务尚未作为本条验收；此次未打包为最终交付，不代表 0.1.0 已完成。分支 feat/agentluo-0.1.0。

- 大目标：新建与现有桌面端功能对齐的 Godot Windows 客户端，完成用户确认的界面改造和安装交付。
- PRD：[Godot-Windows客户端](../需求说明（PRD）/Godot-Windows客户端.md)
- 总体设计：[Godot 客户端总体设计](../../项目说明/项目架构与接口（spec）/Godot客户端总体设计.md)
- interface：[Godot 客户端](../../项目说明/项目架构与接口（spec）/接口文档/client_godot/README.md)
- 总体状态：进行中

## 已完成

### 2026-09-18 基线工程与 Windows 构建

- 交付行为：独立 Godot 4.7.1 工程、版本锁定、headless 检查和 Windows x64 release 导出脚本；保持旧端和 App 入口。
- interface：Godot 客户端「工程与构建入口」。
- 分支：`feat/godot-build-baseline`；SPEC commit：`08fc568`。
- SPEC 自审：核对 PRD、架构、interface，明确用户提供的 4.7.1 与原计划 4.7.2 差异；无服务端接口变化。
- Red：工程/构建配置不适用运行时 Red；用明确失败的非法引擎路径检查代替。
- 验证：`scripts/check.ps1` 导入与启动通过；`scripts/build.ps1` release 导出和独立 EXE headless 启动通过；非法引擎路径返回退出码 1；`git diff --check` 通过。
- 实际引擎：`4.7.1.stable.official.a13da4feb`；同版本 Windows 模板；下载校验值记录在 lock 文件。
- 未验证：真实 GPU 画面、Live2D、业务功能、安装包、Windows 10 和性能均不属于此次完成事实。

### 2026-09-18 真实 Live2D 驱动与导出资源

- 交付行为：gd_cubism v0.9.1 Windows 动态库、完整模型资源、真实模型加载、表情命令、动作及口型控制；保留上游许可及来源。原生插件重建命令复验通过，二进制 SHA-256 与 lock 一致。
- interface：`AvatarDriver`；SPEC `adebd21`，Red `60e71a7`，分支 `feat/godot-avatar-display`。
- Red 证据：实际插件已加载，测试仅因驱动尚未实现加载而失败，退出码 1，`FAIL: complete model loads through AvatarDriver`。
- 验证：驱动契约测试通过；导入、主入口 headless、release 导出和导出 EXE 检查通过。修复打包纹理预检：导出纹理须使用资源存在性而非仅检查原始 PNG。
- GPU 验证：本机 NVIDIA RTX 4070 Laptop、Compatibility/OpenGL，独立导出 EXE 加载真实模型并截图成功，静态透明与遮罩可见检查正常。截图保存在本地 `client_godot/artifacts/avatar.png`。
- 构建检查纠正：GUI 子系统 EXE 不能依赖 PowerShell `$LASTEXITCODE` 或 stdout；现显式等待进程并检查引擎日志及退出码。Godot 官方 release 模板禁止主场景命令行覆盖，模型通过正式启动场景验证。
- 作者自审：核对 SPEC、Red 原因、驱动边界、资源原始来源和日志；未将 headless 冒充 GPU 检查。
- 未验证：Windows 10、集显、长期运行、物理/动作的完整人工验收、音频同步、用户视觉确认和业务接口。

### 2026-09-18 角色构图调整

- 交付行为：滚轮缩放、右键拖动、有限范围构图、相对位置保存与重置；静态背景；最小化暂停角色绘制。
- interface：`AvatarFraming`；SPEC `b94ef3f`，Red `8bec522`，分支 `feat/godot-avatar-framing`。
- Red：公开构图入口未实现时比例、位移及保存契约失败；未使用环境或语法错误作为 Red。
- 验证：`check.ps1` 导入、启动、真实角色及构图契约全部通过；`build.ps1` 导出和独立 EXE 启动通过；本机 GPU 导出截图 `artifacts/framing.png` 确认真实角色与静态背景正常显示。
- 作者自审：检查缩放/位移边界、配置失败保留状态、数据路径和左右键分工；未改变旧端及服务端。
- 未验证：真实鼠标完整操作、多档 DPI、双屏移动与集显性能；未将模型单页作为最终视觉样板确认。

### 2026-09-18 可运行离线聊天界面样板

- 交付行为：真实 Live2D 左侧角色与右侧聊天，默认 45:55 可保存分隔；浅色气泡、头像、可选择中文正文、输入及模拟发送；单张图片选择/粘贴预览入口、缩放和显式发送；五种演示场景；真实表情及无声音的模拟口型。
- interface：`OfflinePreview`；SPEC `1865609`，Red `518abff`，分支 `feat/godot-chat-preview`。
- SPEC 自审：沿用用户已确认的样板范围，UI 使用离线控制器与角色驱动；没有新增服务端协议，也未展开账户、偏好或动态页面。
- Red：公开控制器缺少消息追加、唯一 ID 和状态结束时测试退出 1；共 10 条行为断言失败，未使用环境失败作为证据。
- Green 验证：`check.ps1` 导入、启动、角色、构图、离线消息和主场景键盘输入回归全部通过；Enter、Shift+Enter、空白输入及可见消息经过实际 Godot 输入事件验证。输入回归是补充验证，未伪造单独 Red。
- 导出验证：`build.ps1` Windows release 导出、独立 EXE 启动通过，随包复制模型/引擎/插件许可及样板说明；本机 GPU 分别截取 1200×800、960×640、断网及加载失败画面，中文可读、角色/背景正常；禁用整体窗口内容缩放以保持小窗口文字尺寸。
- 作者自审：检查场景重置后的旧回调隔离、读副本、失败保留输入、图片刷新、浮层焦点、无网络调用及许可分发；修正 RichTextLabel 默认文字颜色和 headless 不支持 IME 查询的问题。
- 本地交付：`client_godot/dist/AgentLuo.exe`；完整目录压缩包 `client_godot/artifacts/AgentLuo-visual-preview-win64.zip`；截图 `artifacts/chat-preview.png`。未合并、未发布。
- 未验证：用户视觉确认、真实 Windows IME/剪贴板/鼠标操作、多档 DPI、Windows 10、集显性能、真实服务与流式音频；本样板没有实际声音，不表示完整客户端或安装程序已经完成。

### 2026-09-18 用户确认视觉样板

- 用户反馈“暂且满意，完善其他功能”，确认当前样板可作为后续业务集成的视觉基线。
- 确认对象：`6524fa2` 的真实模型与离线聊天样板；不视为业务、声音、性能或安装验收通过。

### 2026-09-18 Windows 原生凭据保护

- 交付行为：WindowsSecurity GDExtension 提供 CNG RSA-OAEP/SHA256（MGF1 SHA256）及当前 Windows 用户 DPAPI 字节保护，错误不包含秘密，无明文降级。
- interface：`WindowsSecurity`；SPEC `773a2e0`、Red `32fddc6`，分支 `feat/godot-windows-security`。
- Red：真实扩展加载成功，DPAPI 保护、无效公钥错误码和五组 RSA 加密断言因占位实现失败；退出 1，没有将编译/路径问题算作 Red。
- 验证：`run_security_interop.py` 使用临时密钥，隔离执行仓库 account.py 中原样的密钥生成与解密函数；ASCII、中文/emoji、2048 位密钥的 190 字节边界和 OAEP 随机性通过。DPAPI 往返、不同 scope、密文篡改和上限检查通过。
- 回归：`check.ps1` 全部通过；`build.ps1` release 导出和独立 EXE 启动通过。DLL SHA256 已写入依赖锁。
- 作者自审：检查 Windows 句柄释放、UTF-8 临时明文清零、SPKI RSA 类型/位数校验、无网络/文件副作用。只读独立核验未发现具体实现缺陷，指出跨 Windows 用户测试未覆盖；同用户 scope 测试不等同跨用户验收。
- 构建：MSVC 对中文绝对源码路径的响应文件存在编码问题，使用同一锁定源码的本地目录联接构建通过；目录联接与对象文件不导出。
- 未验证：跨 Windows 用户 DPAPI、干净 Windows 10 机器和完整服务端 HTTP 登录；当前切片没有修改旧端或服务端实现。

### 2026-09-18 异步账户 HTTP 接口

- 交付行为：AccountApi 通过既有 /auth 路由完成密码登录、注册、重置和自动登录，返回校验后的结果；地址规范化、请求取消、超时与并发拒绝，禁止重定向，不记录请求秘密。
- interface：`AccountApi`；SPEC `334c8ee`、Red `3dcb6f2`，分支 `feat/godot-account-api`。
- Red：本地随机端口服务已就绪，17 条目标行为因占位实现未提供账户请求而失败，退出 1。
- 验证：`run_account_tests.py` 使用真实 Godot HTTPRequest 和 CNG 加密，四种请求字段、Python 解密、401/503、公钥失败、JSON 错误结构、空 token、超时、取消和取消后的迟到 POST 成功均通过；未知请求字段不透传。
- 回归：`check.ps1` 现有角色、构图、样板和凭据测试通过；`git diff --check` 通过。
- 作者自审：核对当前服务端字段、响应数据最小化、TLS 默认验证、无重定向、请求生命周期及旧回调隔离。模拟测试不等同真实部署验收。
- 未验证：开发服务器实际登录、TLS 部署证书与端到端账户页面；本切片不保存 token，也不建立聊天连接。

### 2026-09-18 自动登录与账户生命周期

- 交付行为：CredentialStore 按规范化服务器/账户隔离 DPAPI token，以临时文件原子替换；AccountSession 发布已校验会话、恢复自动登录、保存旋转 token、明确 401 清理和退出清理。普通设置不保存 token。
- interface：`CredentialStore`、`AccountSession`；SPEC `e85f027`、Red `6e7c7fb`，分支 `feat/godot-account-lifecycle`。
- Red：真实原生扩展与本地 HTTP 服务正常，10 项持久化/会话行为因占位实现失败。
- 验证：`check_accounts.ps1` 原生互操作、HTTP 与会话全部通过；跨服务器/账户读取隔离、重新实例化恢复、旋转 token 保存、401 清理、退出清空、存储失败仍允许在线登录且禁用自动登录均有公开入口断言。
- 作者自审：核对 settings 与 token 分离、只保存 login_token、无明文降级、深拷贝会话、错误报告及临时文件清理；失败写入测试使用独立临时路径，不碰用户配置。
- 未验证：真实部署、跨 Windows 用户、系统掉电时文件系统持久性和实际账户 UI；该切片没有建立聊天连接。

### 2026-09-19 真实账户页面与应用入口

- 交付行为：默认入口为真实登录/注册/邀请码重置表单，支持自定义服务器和自动登录；错误保留输入、确认密码校验、成功清空敏感字段、取消和退出。离线样板改用开发参数 --preview，与实际账户隔离。
- interface：`AccountView 与应用账户入口`；SPEC `439cda2`、Red `cb56b56`，分支 `feat/godot-account-ui`。
- Red：可加载的空视图未提供表单，公开可见控件断言失败；未用导入问题伪造 Red。
- 验证：真实 AccountSession + 本地 HTTP 服务的账户视图测试通过，检查错误密码保留草稿、密码确认拒绝、注册返回登录、清空密码和退出；`check.ps1`、`check_accounts.ps1` 全通过。release 导出与独立启动通过，GPU 截图确认账户页和真实角色正常显示。
- 作者自审：核对表单模式、忙碌时取消、错误提示、凭据保护注入与无模拟登录；修正 LineEdit 字体/占位文字色。headless 和截图入口不恢复真实账户连接。
- 未验证：真实开发服务器登录、Windows IME 和多档 DPI；账户页登录成功不表示聊天与媒体功能已完成。
### 2026-09-19 可靠消息投递队列

- 交付行为：稳定消息 ID、顺序投递、成功/负 ACK、超时与断线退避、最多 8 次重试和 240 秒龄期；瞬时事件独立发送，停止释放旧账户队列。
- interface：`ReliableOutbox`；SPEC `d67f829`、Red `12bab74`，分支 `feat/godot-message-outbox`。
- Red：可运行占位实现缺少投递行为，25 项公开行为断言失败，退出 1；没有环境/解析错误。
- 验证：`check.ps1` 全部通过，包含可控时钟队列测试；覆盖原 ID 重试、迟到/重复 ACK、终止 NACK、容量与包大小、跨龄期拒绝、断线及停止。独立核验指出图片取消事件名和迟到确认边界，新增测试先失败后修正通过。
- 作者自审：核对 SPEC、旧端事件名及退避策略、payload 深拷贝和终态释放；未改动旧端或服务端。
- 未验证：实际 WebSocket 连接及聊天 UI；本切片为投递队列，不表示真实聊天已接入。
### 2026-09-19 WebSocket 认证、心跳与重连

- 交付行为：真实 WebSocketPeer 连接路径前缀下的 chat_ws，以 message_token/user_auth/negative_ack_v1 鉴权；auth_ok 后心跳及业务投递；断线退避、超时、明确拒绝凭据停止重连、退出清理。
- interface：`WebSocketTransport`；SPEC `02ea78c`、补充 `048dbf4`，Red `d1a7ea9`、`9864666`；分支 `feat/godot-websocket-transport`。
- Red：本地服务正常，占位实现 19 项行为失败；补充认证关闭码 1008 用例先失败，修复后通过。测试服务普通拒绝保持连接与现有服务一致，单测另覆盖尝试耗尽立即关闭。
- 验证：`check_network.ps1` 使用真实 socket 与 loopback websockets 16.0 fixture，鉴权字段、心跳、ACK、回复、同 ID 重连、同凭据拒绝和新 token 恢复、认证超时、无效 JSON 全通过；`check.ps1` 全通过。
- 作者自审：核对 URL/TLS、队列资源、收包数量与字节限制、不输出原始秘密。发现 Godot 对立即关闭时最终帧的保留存在边界，认证关闭码 1008 单独终止，不依赖最后一帧错误文本。
- 未验证：真实开发服务、TLS 部署、复杂代理网络；当前尚未接入正式聊天界面。
### 2026-09-19 正式文字聊天与账户入口集成

- 交付行为：登录后进入真实文字聊天；发送状态由 ACK 更新，重连期间可排队，无法确认送达明确提示；同 UUID 分片聚合、回复与表情顺序、思考状态、隐藏/临时回复、语音错误保留文字。退出清理连接、队列和会话，返回账户页。
- interface：`ChatSession 与 ChatView`；SPEC `1659b9a`，Red `f7a95ee`，补充回归 Red `3e86dfc`、`745182d`；分支 `feat/godot-text-chat`。
- Red：可运行占位控制器/视图的 8 项真实聊天行为失败；后续复现同帧重启残留旧气泡和重复分片撤销终止状态，修复后通过。
- 验证：`check.ps1`、`check_network.ps1`、`check_accounts.ps1` 全部通过；真实输入事件经 ChatView/ChatSession/WebSocketPeer 到 loopback 服务后收到回复，验证发送确认、正文保留、隐藏消息、表情排序和退出清理。共享 `contracts/chat/reply_events.json` 同时由旧 Python 客户端实际解析器与 Godot 网络链路消费。
- 导出：`build.ps1` Windows release 导出和独立 EXE headless 启动通过，产物 `client_godot/dist/AgentLuo.exe`，随包说明明确正式功能与离线演示差别；旧客户端和既有样板压缩包保留。
- 作者自审：核对消息快照、重复终止、更新原气泡、延迟布局时的滚动、账户退出及分隔比例；未混入 project.godot 的原有编辑器修改。独立聊天核验代理因服务不可用而中止，没有独立审核结论；作者自审不能替代他人审核。
- 未验证：真实开发服务器、完整登录到聊天的部署联调、Windows 10、集显性能、多档 DPI 和系统 IME；当前正式聊天没有图片、历史、流式声音或回放，本次不是全功能替换验收或安装程序交付。
### 2026-09-19 紧凑账户窗口与旧端默认服务器

- 交付行为：未登录只显示 660×800 账户窗口，最小 480×640；成功登录展开角色/聊天，首次 1200×800，最小 960×640；失败和等待不展开，退出收起并释放角色绘制资源，重新登录恢复本次运行的普通窗口尺寸。离线样板保持原宽窗口。
- 默认地址：沿用 client/config/config.json release_config.base_url 的 https://www-api.u3493359.nyat.app:11664；有效自定义地址优先，空/坏配置回退且不自动登录，不读取旧端凭据。
- interface：账户窗口展开与默认服务器；SPEC `9947683`、Red `13d2e80`，分支 `feat/godot-compact-login`。
- Red：真实账户服务和视图正常运行，旧行为因默认地址为空、窗口未收起、退出后角色仍存在等断言失败，无环境/解析错误。
- 验证：check.ps1、check_accounts.ps1、check_network.ps1 全通过；新增应用测试以真实 AccountSession/AccountApi 和可见按钮验证初始、失败、成功、退出和地址恢复。headless 不支持原生窗口模式的尺寸恢复断言明确跳过，随后 --gpu 在本机 RTX 4070 Laptop 原生窗口执行相同测试全部通过、无跳过。
- 导出：build.ps1 release 导出与独立 EXE 启动通过；导出 EXE 截图 artifacts/compact-login.png，确认 660×800 账户页、无角色区、默认地址完整显示。截图模式没有自动登录或访问默认服务器。
- 作者自审：检查状态切换、角色生命周期、原生窗口尺寸、屏幕边界、自定义地址优先及无默认服务器探测。project.godot 仅提交本次两项宽度变更，保留原有编辑器改动；无远程合并/发布。
- 未验证：默认服务器实际登录、多屏/多档 DPI、Windows 10；本次截图和原生窗口测试不替代这些验收。
### 2026-09-19 客户端音频接收诊断日志

- 交付行为：应用启动、连接状态、回复音频是否存在/编码长度/终止标志及系统错误写入 user://logs/client.jsonl；最多三份轮换日志，聊天区提供打开日志入口。
- interface：ClientLog；SPEC d82ae42、Red 3397382；分支 feat/godot-audio-diagnostics。
- 验证：日志白名单、哈希关联 ID、轮换、不可写路径返回错误通过；check.ps1 和 check_network.ps1 通过，真实 loopback 回复产生接收日志，日志不含合成 token 或消息正文。
- 作者自审：未知字段丢弃、逐条 flush、有界文件、测试目录隔离；记录仅证明接收，当前切片不代表音频已播放。
- 未验证：真实服务器音频、实际声音输出；日志没有上传功能。

### 2026-09-19 原生增量 WAV/PCM 解码

- 交付行为：PcmStreamDecoder 接收跨片 WAV 头及连续 PCM，支持服务端未知 data 长度、常用整数/浮点位深及单/双声道；批量返回立体声帧与按播放帧查询的 RMS，错误释放缓冲。
- interface：PcmStreamDecoder；SPEC 156d497、Red b11c6a5、边界回归 Red 627415a；分支 feat/godot-pcm-decoder。
- 验证：check.ps1 全通过；原有 Python RSA 解密互操作通过；8 MiB 输入、1 MiB 头、128 MiB 未读帧及 30 分钟时长边界有执行断言。独立只读核验发现 data 头漏计 8 字节，回归先失败，修正后通过。
- 作者自审：核对完整 extensible GUID、半帧、非有限样本、辅助 chunk、已知长度尾部及错误粘性；DLL 已重建并更新锁定 SHA256。
- 未验证：本切片只验证真实原生解码，不代表扬声器输出、真实服务或口型同步已验收。

### 2026-09-19 回复语音实际播放与诊断闭环

- 修复根因：ChatSession 原先只处理文字/表情，没有把 payload.audio 接入播放器。现通过 ReplyAudio 和原生解码驱动 AudioStreamGenerator，自动播放，按实际播放结束推进文本/表情/下一句；口型按消耗帧查询 RMS，结束恢复基础口型。
- 交付行为：音量调节并保存、停止当前语音、隐藏回复声音、音频错误保留文字、断线/退出清理；接收/格式/解码/开始/结束/错误日志与打开日志入口。没有写入音频缓存或新增回放按钮。
- interface：ReplyAudio、ChatSession；SPEC f3e6a51、4ffabce；Red 9b66997、87d4464，边界 Red 011c271；分支 feat/godot-streaming-playback。原生解码 Green d072d33，诊断日志 Green 368cec7。
- 验证：check.ps1、check_network.ps1 通过；账户全套回归通过，更新后的应用窗口/音量测试又在本机原生 GPU 窗口通过。真实 loopback WebSocket 验证跨片 WAV、先缓存后播放、隐藏音频、停止后最终文字、错误及断线；AudioEffectCapture 测得非零输出和静音效果。
- 原生输出验证：本机 WASAPI 激活双声道 192000 Hz 输出，Godot 报告 10ms 缓冲延迟，test_reply_audio.gd 通过；这不是人工听感结论。build.ps1 release 导出/独立 EXE 启动通过，随包 DLL SHA256 与 lock 一致。
- 导出资源验证：官方 release EXE 忽略外部 --script，已识别且未将其普通启动冒充测试；用同版本标准引擎加载实际导出的 AgentLuo.pck，并在同目录放置本次随包 DLL，WASAPI 播放测试通过，记录 artifacts/export-pack-audio-verified.log。
- 作者自审与独立核验：修正重复终止、容量拒绝后重复 UUID、停止覆盖错误码和越界音量配置；可控时钟验证 60 秒无续片超时，跨 UUID 累计缓冲及 16 个待处理回复上限有断言。中途停止导致提前丢弃最终文字的疑点经真实网络测试未复现，确认 STOPPED 完成信号等待终止包。未改动旧端或服务端，保留 project.godot 既有编辑器修改。
- 未验证：真实部署的 TTS/唱歌联调、人工听感、口型实测偏差、30 分钟运行、Windows 10 与集显性能；未合并、未正式发布，也不是安装程序或全功能替换验收。

### 2026-09-19 主题蓝与正式聊天布局

- 交付行为：#66CCFF 主题、主按钮/滑块/输入焦点状态、圆形头像、白/浅蓝气泡、更多菜单及底部音量；登录窗口行为保持。
- SPEC 7776cc6；Red 72b7194（真实聊天缺少更多菜单与菜单退出）；分支 feat/godot-blue-ui。
- 验证：check.ps1、真实 loopback 聊天测试、账户应用窗口测试通过；作者自审核对菜单退出、可读文字、原有配置和未实现入口隐藏。视觉截图与 DPI 检查在最终导出验收单独记录，不将 headless 当视觉验收。

### 2026-09-19 完整语音缓存与原生波形

- 交付行为：AudioCache 分块保存原始流，成功终止与文件提交后才可查询；规范化服务器/账户/UUID 隔离，无自动淘汰，手动清理。PcmStreamDecoder 原生输出 24 桶波形摘要。
- SPEC fbf3c44；Red a19fa19、e5866d4；分支 feat/godot-audio-cache。
- 验证：缓存及解码 focused tests 通过，包含跨实例、残缺/损坏文件、错误提交、只读临时文件清理失败、隔离、极短波形；原有全套检查除新增缓存用例外通过，修正缓存类型检查后该用例重跑通过；原生 RSA/Python 互操作通过。
- 作者自审：核对双文件提交顺序、只删除当前范围自有文件、无完整文件自动淘汰；日志原始 UUID 疑点经 ClientLog 的 SHA256 白名单逻辑确认不会落盘。DLL 重建及 SHA256 锁定更新。本切片尚未将缓存接入在线媒体与界面。

### 2026-09-19 完整语音重放媒体链路

- 交付行为：ReplyAudio 注入缓存，完整流提交后可重放；暂停/继续/停止、在线抢占、停止在线后继续完整缓存；断线中断清理、范围隔离、手动清理抑制当前流写入。原生波形与实际消耗帧提供进度/口型，重放完成与在线完成分开。
- SPEC ba5e025；Red 738f21a（可运行测试确认缺少重放能力）；分支 feat/godot-voice-replay。
- 验证：test_voice_replay.gd 的真实 AudioEffectCapture 输出、暂停静音/进度冻结、续播、停止/切换/抢占、完整缓存和不可写路径全部通过；test_reply_audio、test_audio_lifecycle、test_audio_cache 回归通过。
- 作者自审：核对缓存三项提交条件、重复操作、只有一个声音输出、无旧账户完成信号；本条只记录媒体公开接口，尚不表示正式消息按钮已接通。独立核验在限时内未返回结论，不能视为他人审核通过。

### 2026-09-19 正式消息重放控件与清理确认

- 交付行为：Application 注入按账户隔离缓存，ChatSession 提供消息音频操作；气泡下方重放/暂停/继续/停止、真实波形/进度，定向更新不重建文字。更多菜单提供清理确认，取消保留文件，确认移除重放按钮但保留正文。
- SPEC ba5e025；Red ad0ec6f（真实 loopback 声音可播，但没有消息重放控件及清理确认）；媒体 Green 57b96f0；分支 feat/godot-voice-replay。
- 验证：check.ps1、check_network.ps1、check_accounts.ps1 全部通过；voice_chat 验证文字选择保持、消息/表情不重复、取消/确认清理。账户窗口测试在本机 GPU 窗口另跑通过，没有 headless 尺寸跳过。
- 本机 WASAPI：test_voice_replay.gd 通过，双声道 48000Hz、10ms 缓冲；AudioEffectCapture 检查非零输出、暂停静音和进度冻结。日志 artifacts/replay-wasapi.log；不代表人工听感。
- 截图：真实 ChatView/ChatSession/WebSocket/Avatar 与合成语音，1200×800、960×640、暂停态、125%/150% 内容缩放通过控件边界检查；截图 artifacts/voice-ui-*.png。RTX 4070 Laptop GPU、NVIDIA 610.74；本次是内容缩放检查，不是操作系统 DPI 切换验收。
- 作者自审：正文选择与播放进度分别更新，UI 不接触音频路径；退出关闭范围，完整缓存保留；手动清理默认聚焦取消。project.godot 原有编辑器改动保留未提交；未改服务端协议及旧客户端。
- 未验证：真实服务器 TTS/唱歌听感、长期运行/内存、Windows 10、集显性能、系统 DPI 切换和双屏。未正式替换交付入口。

### 2026-09-19 重放版 Windows ZIP 导出核验

- 候选代码 869d3bd；build.ps1 导出/独立启动通过。同版本标准引擎加载实际 AgentLuo.pck 与随包 DLL，完整重放 WASAPI 测试通过（artifacts/export-replay-verified.log）。
- ZIP：artifacts/AgentLuo-replay-869d3bd-win64.zip，43,061,194 字节，13 个文件；CRC、EXE/PCK/DLL/许可核验通过，DLL 哈希与依赖锁一致。SHA256 eeacb6bef3cc3a61dfad385cc308e5f36e7d714c56402e5d3c66bd888264ee29。
- 旧 AgentLuo-voice-fix-win64.zip 保留；本地 PR 说明、提交/自审与实际测试记录见 artifacts/voice-replay-review.md。没有推送/合并或切换正式下载入口；未验证范围沿用上一条记录。

### 2026-09-19 动态用途模型设置与密钥保存

- 交付行为：从现有模型类型路由生成非模态设置表单；用途独立草稿、复制后保持目标类型/要求、纯本地能力及参数校验、DPAPI 密钥隔离持久化。保护失败明确明文确认，默认取消；窗口关闭不释放应用持有的运行配置，未保存内容参与退出确认。
- SPEC a58ba0e；Red 3993b65、4a8bc5a。Model settings 真实本地类型接口、DPAPI 跨实例恢复/账户隔离/明文选择与可见表单草稿保护通过；Application drafts 回归通过，git diff --check 通过。
- 作者自审：核对无固定用途 ID、无保存时供应商调用、深拷贝配置、目标要求不随复制改变；本条不代表模型委托或手动供应商测试已经接通。未验证公共服务模型类型、人工多 DPI 表单及跨 Windows 用户保护。

### 2026-09-19 实际模型委托与手动测试

- 交付行为：真实 WebSocket llm_request 转异步 OpenAI 兼容非流式调用，llm_response 回传；发送及历史屏障释放广告有效用途；配置快照、重复 ID 去重、文本/VLM、JSON 校验及安全失败码，退出取消。手动测试明确额度确认后发送固定短输入，不保存草稿、不发送历史。
- SPEC 85cfc67；Red 2b9173a。run_feature_tests.py/test_model_execution.gd 本地真实 HTTP+WS 通过重复请求仅一次供应商调用、参数优先级/正文保护、JSON/HTTP/超时、取消、手动测试及回传；模型设置和应用草稿回归通过。
- 作者自审：供应商无自动重试、错误不包含供应商正文、只回传 token 数字统计；补齐安全日志词表。独立核查超时未返回可用结论，已停止，不作为他人审核。未调用公共或收费供应商，未验证真实模型/服务器委托。

### 2026-09-19 动态分页与手动未读控制器

- 交付行为：现有 /dynamics 路由10条分页、评论20条分页、不透明游标编码、ID去重；账号代次与退出取消；登录及30秒定时查询未读，读取内容不清未读，只有显式标读成功清零、查询/写入失败保留数量。
- SPEC 936ec04；Red 2c9f7c6；run_dynamics_tests.py 真实 loopback HTTP 的分页、重复边界、评论合并、显式标读、失败保留及退出迟到回调全部通过。
- 作者自审：Bearer GET、现有 token POST、无服务端修改、正文仅内存、响应结构校验与请求并发上限；本切片仅控制器，不代表动态窗口及写入已完成。未验证公共服务及真实账号私有动态。

### 2026-09-19 动态窗口、发布与评论回复

- 交付行为：聊天顶部动态与99+未读，独立单列头像/时间/文字卡片、六行展开、评论分页/点击回复/取消目标；文字发布与回复使用现有接口。失败保留独立草稿、不可评论禁止写入、单写入请求且无超时自动重试，关闭/退出纳入默认取消确认。
- SPEC 3682a14；有效 Red 0ae114a（874acba 的测试推断解析错误已纠正，不计有效 Red）。控制器与可见窗口本地 HTTP 测试通过；真实 Application 登录后徽标/动态入口/模型窗口/偏好草稿退出回归通过。徽标测试由固定100ms改为等待可观察结果，不把网络调度时间当功能缺陷。
- 作者自审：未读轮询不重建卡片、窗口不拥有账号控制器、失败不覆盖草稿；日志不记正文。未在公共服务器发布测试动态，未验证真实私有权限数据及人工多 DPI 卡片。

### 2026-09-19 角色资源描述与当前平台边界

- 交付行为：character.json 分离 luotianyi 身份/original 资源、模型入口和映射，AvatarPanel 使用描述加载；候选模型及映射成功后替换，失败保留现有模型/表情/身份。
- SPEC 3262803；Red 109cfed；真实 gd_cubism 角色加载、原表情/动作/口型回归及描述失败保留测试通过。作者自审核对旧 load_avatar 兼容路径。
- 当前 FileDialog 在 UI 边界，Application 持有业务生命周期，凭据与 PCM 原生类/源文件职责分离；Windows DLL 仍共同分发。没有移动端/换装/箱庭假成功接口；未交付这些未来功能。

### 2026-09-19 损坏模型配置恢复

- SPEC 71a980d；Red f63f89a。损坏的 capabilities/kind 等配置加载后禁用并报告，不向服务端广告，也不把错误结构交给表单。用途类型更新后可重新编辑保存。
- test_model_settings.gd 真实存储损坏配置恢复及原 DPAPI/草稿回归通过；模型表单补统一边距，作者自审核对恢复不调用供应商且不写回损坏文件。

### 2026-09-19 动态增量评论顺序与加载状态

- SPEC 71a980d；Red d8b566d。发出新评论后继续加载较早评论时，按服务端时间/ID合并，避免新评论被排到旧记录前；读写互斥避免旧响应覆盖提交结果。
- test_dynamics_window.gd 原先排序失败、修复后通过；加载成功清除加载提示，未选回复对象不显示取消按钮。作者自审核对草稿不随评论列表更新重建，尚未将模拟测试当公共服务验收。

### 2026-09-19 离线样板退出资源回归

- 既有 Application/演示入口 SPEC 已满足，无公开接口变化；Red 673a0c6，真实 --preview 退出出现未释放 Viewport/Canvas/Text RID。
- 修复：演示提前返回前释放仅正式账户入口使用的未挂树控件；同命令重跑无 RID/ObjectDB 泄漏错误，check.ps1 已加入该入口。作者自审核对正式账户流程不变。

### 2026-09-19 agentluo 整体离线回归与 GPU 界面核验

- check.ps1（角色/构图/凭据/音频/缓存/日志/虚拟历史/阅读/回放）、check_network.ps1（真实 loopback 文字及流式声音）、check_accounts.ps1（含现有 Python 解密互操作）全部通过。新增 check_features.ps1 汇总历史/图片/偏好/模型/动态8个测试入口，全部通过；不连接公共或收费服务。
- 真实 GPU 截图：artifacts/voice-ui-*.png（默认/最小窗口、暂停及125%/150%内容缩放），artifacts/agentluo-010-{login,logs,preferences,models,dynamics}.png 与动态125%/150%截图。RTX4070 Laptop/NVIDIA610.74；视觉检查确认新增按钮未越出主窗口、动态不再残留加载文案，设置可滚动。不是系统 DPI 切换验收。
- WASAPI 的 test_voice_replay.gd 通过，实际混音输出、暂停/继续/抢占由合成音测试断言；日志 artifacts/agentluo-010-wasapi.log。不是人工听感结论。
- 汇总脚本/截图入口/使用说明为既有行为回归与交付记录，Red 不适用；未伪造新功能失败。作者自审检查测试只用临时账号数据、旧包保留、project.godot 原有编辑器修改未纳入提交。未验证公共服务器、人工中文输入法/听感、30分钟性能、Windows10、普通集显、真实系统DPI和双屏。

### 2026-09-19 agentluo 0.1.0 Windows ZIP 交付核验

- 代码候选 4058b3f；build.ps1 -Package 完成 import、release 导出和独立 EXE 启动。产物 artifacts/agentluo-0.1.0.zip，43,154,698 字节、14条目，根目录 agentluo-0.1.0/、程序 agentluo.exe。
- SHA256：e9d4b35f71bdd70836efc43b3bbb3da059c926313f6852d47971fefe874af815。ZIP CRC通过；EXE/PCK/版本/许可与已验证目录一致，两份DLL哈希与dependencies.lock.json一致。
- 同版本标准引擎加载实际导出PCK，角色资源描述/Live2D、新业务脚本加载通过；完整重放 WASAPI 测试通过（双声道48000Hz、10ms缓冲），未把 release EXE 普通启动当外部脚本测试。
- 验收矩阵、截图索引、实际SPEC/Red/Green、自审/未验证范围与回退说明：artifacts/agentluo-010-acceptance.md。后续真机验收本地Issue草稿另存 artifacts/agentluo-010-issue-draft.md；未将未来工作混入本条完成事实。
- 旧两个Windows ZIP保留，未改服务端/旧端/App，未推送、合并或切换正式入口。project.godot 既有编辑器修改保留未提交。公共服务联调、人工听感/输入法、长期性能、Windows10/集显/系统DPI仍未验收，本包不是安装程序或完整旧端替换验收。

### 2026-09-19 统一下拉组件
- 交付行为：共享稳定 ID 选择器/操作菜单，白底圆角弹出层，禁用项、方向键/Enter/Esc、滚动及窗口变化收起。
- interface：client_godot/README.md UnifiedDropdown；SPEC 9260ab1，Red c2802b4（共享组件缺失）。
- 验证：Godot 4.7.1 headless test_dropdown.gd PASS；当前提交已自审。原生弹窗边界和缩放尚未真机验收。

### 2026-09-20 正式页面下拉迁移
- 账户、聊天更多、相处预设、模型用途/复制、日志筛选及启动选择使用 UnifiedDropdown；业务通过稳定 ID 操作。机械迁移 Red 不适用，保留既有业务断言。
- check_accounts.ps1、check_network.ps1、check_features.ps1 全部 PASS；覆盖原账户、聊天/语音、历史、设置及动态流程。作者自审核对无直接 PopupMenu 业务依赖。

### 2026-09-20 评论全分页刷新
- SPEC ccdddc7，Red 5dcce8d：缺少完整刷新调用。实现读取至末页后原子合并、循环游标拒绝、失败保留和账号代次隔离；发布返回 item_id。
- test_dynamics.gd 真实本地 HTTP 全页刷新及既有分页/已读/取消 PASS；作者自审核对服务端协议无变化。

### 2026-09-20 原生双栏动态与行内草稿
- SPEC b658d69，Red 353844e：缺少双栏选择边界；实现45:55可调原生窗口、完整详情、平铺评论、行内回复、独立发布、每动态草稿和关闭聚合确认；移除被替代的单列卡片。窗口/详情/发布共约500行构成可运行视图切片，保留应用控制器所有权。
- test_dynamics_detail.gd、test_dynamics_window.gd、test_application_drafts.gd PASS。capture_dynamics_ui.gd 使用真实GPU生成默认、最小、回复、发布及125%/150%内容缩放截图；分区比例断言PASS。Windows HWND无owner/非toolwindow、主窗口实际最小化后动态仍可见PASS。
- 作者自审修正force_native初始化顺序和分隔条偏移；未将任务栏资格检查或内容缩放截图宣称公共服务/实际OS DPI人工验收。

### 2026-09-20 原生下拉坐标与缩放修正
- 沿用 UnifiedDropdown SPEC，Red 8e9b066：真实GPU下125%/150%菜单没有跟随按钮物理宽度。修正原生窗口位置加Viewport最终变换，弹层按实际缩放绘制，蓝色选中标记。
- capture_dropdown_ui.gd 和 test_dropdown.gd PASS：底部向上、35项长列表、键盘跳过禁用项、Enter/Esc、父窗口移动收起、原生触发点对齐和缩放边界。作者自审确认无页面操作弹层内部。

### 2026-09-20 下拉当前值可读宽度
- SPEC沿用统一下拉，Red 249f164复现日志筛选当前值被挤压。统一选择器保留140px最小宽度、操作按钮90px；蓝色选中状态覆盖焦点。
- test_log_window.gd 和 test_dropdown.gd PASS；测试排除隐藏系统文件对话框内原生选择器。作者自审确认正式页面控件布局修复，不改筛选逻辑。

### 2026-09-20 0.1.1 回归与交付候选
- check.ps1、check_accounts.ps1、check_network.ps1、check_features.ps1 全部PASS；新增补回归覆盖刷新后页失败保留、双账号私人评论/数量、退出取消、发布后选择、草稿/阅读位置/分隔比例恢复。补回归首次通过，不伪造Red。
- 新版账户/日志/偏好/模型/动态及语音默认/最小/暂停/125%/150%内容缩放GPU截图成功；原生动态独立最小化和菜单边缘/键盘测试PASS。日志筛选宽度修复后已重新截图核查。
- 测试布局隔离到临时目录；恢复错误提示、异常时间保留原文。版本单一来源设为0.1.1，使用说明与现行interface消除旧单列界面描述；原有project.godot编辑器修改保留未提交。作者自审与diff检查完成，未修改服务端/旧Python端/App。

### 2026-09-20 0.1.1 完整ZIP交付核验
- 打包SPEC b4f79ee、Red 303b960验证实际残包缺少EXE；构建改为临时ZIP、完整条目校验后原子发布正式名。失败不会留下同名正式包，同版本覆盖被拒绝。作者自审核对Windows路径规范与失败清理。
- agentluo-0.1.1.zip：43,172,555字节/14文件；SHA256 f22ec8da492c740244b9012a2f109a6ac4bcde254ac98658a91a52dc1bb9602d。verify_release_archive.py CRC/版本/逐文件字节比对PASS，两DLL与锁文件一致，0.1.0旧包哈希未变。
- 最终PCK的角色/新UI资源加载、0.1.1版本、完整重放WASAPI实际混音PASS；动态追加滚底自动分页和不可评论输入回归PASS。
- 截图/验证/提交/自审及未验证范围汇总：client_godot/artifacts/agentluo-011-acceptance.md。公共服务、真实系统DPI/Windows10/集显、人工听感与长期性能未验收；未推送合并或切换入口。

### 2026-09-20 界面场景化首片——主题与材质资源化
- 交付行为：主题与头像/滑块图形资源化，为后续把界面改为场景绘制提供共享主题与材质；外观、文案、字号、颜色与既有代码逐项等价，不改任何视图节点树。
- interface：PRD「界面以场景绘制（方案 B）」；接口文档 client_godot/README.md「界面场景化：主题与材质资源（0.1.2 起）」。新增 res://theme/app_theme.tres（默认字体族/字号15、各type颜色与占位/选区/光标色、Button/OptionButton/MenuButton五态、PrimaryButton变体、TextEdit/LineEdit normal、PopupMenu panel/hover/v_separation、HSlider slider/grabber_area及三个grabber圆点图标）、res://assets/ui/round_avatar.gdshader、res://assets/ui/slider_dot{,_highlight,_disabled}.png；project.godot 增 [gui] theme/custom。
- SPEC 5a28e7e；Red 697c61e（资源尚不存在，test_theme_contract 5 条失败）；Green 72cedba。preview_style.make_theme() 改为 res://theme/app_theme.tres 薄壳，avatar() 改引用外置 shader。
- 验证：Godot 4.7.1（4.7.1.stable.official.a13da4feb）headless test_theme_contract.gd PASS，断言主题条目、make_theme() 与资源全签名相等、项目默认主题、grabber 圆点像素公式、头像 shader 掩码；scripts/check.ps1 20 步全绿；check_network.ps1 PASS。
- 视觉：capture_dropdown_ui.gd 与 capture_voice_ui.gd 真实GPU截图成功。与基线差异已归因——下拉图差异为一整行悬停像素（基线无 hover），语音图差异全部落在左侧 Live2D 头像区且同代码两次运行同样出现，属运行态随机性，非本片回归。
- 作者自审：diff 仅含主题/材质资源、make_theme 薄壳化、project.godot 增默认主题与测试自身修正，无视图节点树改动、无顺手改进；原有 project.godot 编辑器修改与两个 addons DLL 删除未纳入提交。
- 未验证范围：check_accounts.ps1 与 check_features.ps1 因本机缺 fastapi 未运行（环境缺口，非代码失败）；未做人工多 DPI 复核；未推送、未开远程 PR。

### 2026-09-20 界面场景化第二片——publish_window 视图场景
- 交付行为：发布动态窗口改为「场景节点树 + 只做行为的脚本」。新增 res://scenes/ui/publish_window.tscn（根 Window「PublishWindow」挂 src/ui/publish_window.gd 与 app_theme.tres），标题、草稿框 %PublishDraft、状态 %PublishStatus、发布按钮 %PublishButton 与面板样式全部写在场景里；脚本删除 _init(controller) 与建树代码，改 setup(controller) 注入并用 %Name 绑定。published(id)、open()、is_dirty()、发布/清空/关闭/失败文案行为与公开面不变。
- interface spec：接口文档 client_godot/README.md「界面场景化：视图场景与 setup() 注入」；实测契约：场景属性先赋值、根脚本随后执行 _init()，_init() 赋值会覆盖场景同名属性，故 draft_window._init() 只保留 visible = false、不再赋值 transient（Window.transient 默认 false）。
- commit：SPEC c2eb44b 与 87ee1b3，Red 35d0079，Green 6e3d976。
- Red 证据：test_ui_scenes.gd 仅「scene exists: res://scenes/ui/publish_window.tscn」一条失败；run_dynamics_tests.py 报 Cannot open file 该场景（dynamics_window.gd:175）。两条都只因目标场景未实现而失败。
- 验证及结果：Godot 4.7.1 headless test_ui_scenes.gd PASS，逐项断言场景存在、根名与类型、根脚本、关键节点 unique_name_in_owner 与 %Name 解析、setup() 暴露且 _init 无参数、搬入场景的属性与样式盒（背景色/圆角/内边距）与原代码相等、根挂主题。scripts/check.ps1 21 步全绿；check_features.ps1（含 Application drafts）、check_accounts.ps1、check_network.ps1 全部 PASS；run_dynamics_tests.py 的 test_dynamics_window.gd 与 test_dynamics_detail.gd PASS。
- 视觉：真机 GPU 截图 capture_dynamics_ui.gd 产出 7 张 agentluo-011-dynamics-*.png，与改动前基线（1b7e770 独立 git worktree、同机同命令重跑）逐字节相同，含发布窗口截图。
- 作者自审：diff 仅含本视图场景、其脚本改造、基类一行删除与契约测试；无顺手改进、无其它视图改动；两个 addons DLL 既存删除未纳入提交。
- 未验证范围：未做人工多 DPI 复核；未推送、未开远程 PR。

### 2026-09-20 界面场景化第三片——preferences_window 与 model_window 视图场景
- 交付行为：相处模式窗口与 LLM / VLM 模型设置窗口改为「场景节点树 + 只做行为的脚本」。新增 res://scenes/ui/preferences_window.tscn（根 Window「PreferencesWindow」）与 res://scenes/ui/model_window.tscn（根 Window「ModelWindow」），两者根节点挂各自脚本与 app_theme.tres；标题、标签、输入框、状态、操作行、选择器插入位与窗口下的确认对话框全部写在场景里，原 _init 的 title / size / min_size、Style.label 的字号与字体颜色覆盖、Style.primary 的 PrimaryButton 变体、autowrap / 换行模式 / 最小高度 / 占位文本 / 密文与 size_flags 均由场景提供；脚本删除带参 _init 与建树代码，改 setup(controller) 与 setup(settings,executor) 注入并用 %Name 绑定。UnifiedDropdown 仍由代码创建，用场景里的不可见 Control 标记（%SelectorSlot、%CopySlot、%RelationshipPresets、%SpeakingStylePresets）配合 move_child 插位。published 类公开面不变，is_dirty()、open()、_update()、_save()、_copy_selected()、_test() 与全部提示文案保持原样。
- interface spec：接口文档 client_godot/README.md「preferences_window 与 model_window（0.1.2 第三片）」。本片实测更正两处契约：一是 executor 为 null 时不释放 %TestButton / %TestDialog，而是把 %TestButton 置为不可见、把两个成员置空且不连接信号（queue_free 的节点在下一个 process_frame 之前就已被回收，契约用例会找不到节点）；二是两个窗口场景都必须能不带依赖实例化，_controller / _settings 为空时 _ready() 只完成基类初始化便返回、不连接依赖信号。
- commit：SPEC c482a6e，Red a1d74e7，Green 5d5f8fe。
- Red 证据：test_ui_scenes.gd 仅两条「scene exists」失败；run_feature_tests.py 的 test_preferences.gd 报「FAIL: preference window exposes draft protection」，test_model_settings.gd 报「FAIL: model settings window available」；test_application_drafts.gd 运行时报「ERROR: Cannot open file 'res://scenes/ui/model_window.tscn'」（src/application.gd:236）。全部只因目标场景尚未实现而失败。
- 验证及结果：Godot 4.7.1 headless test_ui_scenes.gd PASS（断言两场景存在性、根节点名与类型、根脚本、setup() 暴露且 _init 无参数、关键节点 unique_name_in_owner 与 %Name 解析、搬入场景的属性 / 字号 / 字体颜色覆盖 / 样式盒）；test_preferences.gd、test_model_settings.gd、test_application_drafts.gd、test_application_window.gd 全部 PASS；scripts/check.ps1 21 步全绿；check_features.ps1、check_accounts.ps1、check_network.ps1 全部 PASS。
- 视觉：真机 GPU 截图 capture_release_ui.gd 产出 7 张 agentluo-011-*.png，与改动前基线（c482a6e 独立 git worktree、同机同命令重跑）逐字节比对：login、models、preferences、dynamics、dynamics-scale-125、dynamics-scale-150 六张 SHA256 完全相同；logs 一张不参与比对，因为它在两份改动前基线之间同样不同（日志文本含时间戳，属既有随机性）。
- 作者自审：diff 仅含两个视图场景、其脚本改造与 interface 文档契约更正；自审时发现并修回被漏写的 _plain.confirmed → _save(true) 连接与文件尾换行；无顺手改进、无其它视图改动；两个 addons DLL 既存删除未纳入提交。
- 未验证范围：未做人工多 DPI 复核；未推送、未开远程 PR。

### 2026-09-20 界面场景化第四片——account_view 与 main.tscn 就地节点化
- 交付行为：登录表单改为「场景节点树 + 只做行为的脚本」。新增 res://scenes/ui/account_view.tscn（根 PanelContainer「AccountForm」，挂 src/ui/account_view.gd 与 app_theme.tres）：标题「和天依再见面」与副标题、%Form 内的 %AccountMode 下拉、五组输入框（%Server/%Username/%Password/%Confirm/%Invite，占位与 tooltip 文案、secret、纵向最小高度 40、#f0f5f7／圆角 8／内边距 10 的 normal 样式盒）、%Remember「下次自动登录」、%Submit「登录」（PrimaryButton 变体、高 42）、%Cancel「取消请求」/%Identity/%Logout「退出登录」（默认不可见）、%Status（智能按词换行、13 号字、#607f8d）与 %Logs「打开日志」全部由场景提供；白底圆角 18 内边距 28 的 panel 样式盒与主题也改由场景根承担。res://scenes/main.tscn 就地节点化为组合根：%Split（HSplitContainer，全幅锚点、DRAGGER_HIDDEN_COLLAPSED、默认不可见）、其唯一子 %Center（custom_minimum_size.x=440、横向扩展填充）、%Center 下 %AccountForm 内嵌实例（custom_minimum_size.x=390）、%LogProblem（顶边通栏、智能按词换行、#b72a2a）与 %ExitDialog（ConfirmationDialog，标题/正文/按钮四个文案）。脚本侧删除 Style 依赖、带参 _init 与全部建树代码：account_view 改 setup(session)，依赖到位后由私有 _initialize() 一次性接线；application 改 setup(account_session, layout_path)，_split/_center/_log_problem/_exit_dialog/_account_form 改为 @onready + %Name 绑定，正式路径在原来 add_child(_split) 的位置改为 _split.show()，预览分支的 free() 改为 queue_free()。avatar 与 chat_view 仍登录后运行时实例化，节点命名契约（AccountMode 等）与全部公开信号/方法不变。
- interface spec：接口文档 client_godot/README.md「account_view 与 main.tscn 就地节点化（0.1.2 第四片）」。实现与契约一致，未增删契约条目；实现细节补充：场景骨架默认不可见、只有正式路径 _split.show()，因此 --preview 与「凭据保护组件缺失」两条早退路径不会多出控件。
- commit：SPEC 001700b，Red 42bb9e0，Green 38f662d。
- Red 证据：test_ui_scenes.gd 报「FAIL: scene exists: res://scenes/ui/account_view.tscn」「FAIL: script exposes setup(): res://scenes/main.tscn」「FAIL: script needs no _init arguments」「FAIL: node %Split/%Center/%AccountForm/%LogProblem/%ExitDialog is unique…」并因 application.gd 缺 setup 出现「ERROR: Error calling method from 'callv'」；run_account_tests.py --script test_account_view.gd 报「FAIL: account view scene exists」并以 RuntimeError 退出；test_application_window.gd / test_log_window.gd / test_application_drafts.gd 因 Nonexistent function 'setup' 超时失败。全部只因目标场景尚未实现，未伪造 Red。
- 验证及结果：Godot 4.7.1 headless test_ui_scenes.gd PASS（新增 account_view.tscn 与 main.tscn 两条契约：场景存在性、根节点名与类型、根脚本、setup() 暴露且 _init 无参数、13+5 个关键节点 unique_name_in_owner 与 %Name 解析、从代码搬入场景的属性与样式盒，main.tscn 条目以临时布局目录注入后实例化并清理）；test_account_view.gd、test_application_window.gd、test_application_drafts.gd、test_log_window.gd PASS；scripts/check.ps1 21 步全绿；check_accounts.ps1、check_features.ps1、check_network.ps1 全部 PASS。
- 视觉：真机 GPU 截图 capture_release_ui.gd 产出 7 张 agentluo-011-*.png，与改动前基线（001700b 独立 git worktree、同机同命令重跑）逐字节比对：login、models、preferences、dynamics、dynamics-scale-125、dynamics-scale-150 六张 SHA256 完全相同；logs 一张不参与比对，因为日志文本含时间戳（既有随机性）。capture_voice_ui.gd 需要 loopback WebSocket fixture，独立运行时在基线与本片都因 WS 握手 404 失败，属本机环境限制而非本片回归。
- 作者自审：diff 仅含 account_view 场景与其脚本、main.tscn、application.gd 三处加一个新增场景；%Center 的 440/横向扩展填充、%AccountForm 的 390 与 dragger_visibility 均由场景携带，契约用例的取值断言可证；%ExitDialog 默认不可见与原代码 new() 后 add_child 的实测行为一致（实测 ConfirmationDialog 加入树后 visible=false）；自审时发现并修回两处被漏写的文件尾换行，并按契约去掉误加到「凭据保护组件缺失」分支的 _split.show()；两个 addons DLL 既存删除未纳入提交。
- 未验证范围：未做人工多 DPI 复核；未推送、未开远程 PR。

### 2026-09-20 界面场景化第五片——日志窗口与下拉控件（unified_dropdown + dropdown_item + log_window）

- 交付行为：统一下拉改为场景承载。res://scenes/ui/unified_dropdown.tscn 根 Button（UnifiedDropdown）挂 src/ui/unified_dropdown.gd 与 app_theme.tres，场景提供 custom_minimum_size (140,40)、alignment LEFT、clip_text 与私有弹层节点树 %Menu（PopupPanel，默认不可见、force_native、白底圆角 10 内边距 6、1 像素 #dce1e5 边框、shadow_size 4、12% 黑阴影）、%Menu/%Scroll（ScrollContainer 禁用横向滚动）、%Menu/%Scroll/%Rows（VBoxContainer 间距 0、横向扩展填充）；原 _init(actions) 删除，动作菜单模式改为普通属性 action_menu，赋值时在 90 / 140 之间切换 custom_minimum_size.x。新增 res://scenes/ui/dropdown_item.tscn + src/ui/dropdown_item.gd 承载单行：静态外观（左对齐、(0,42)、白底圆角 6 内边距 12 的 normal、#f0f2f4 圆角 6 内边距 12 的 hover、#353c43 字体色）在场景，setup(item) 注入 text / set_meta("id") / disabled；_build() 每行改由该场景实例化，分隔项仍是代码插入的 HSeparator，选中态 ✓ 前缀与四个字体颜色覆盖仍在 open_menu()。日志窗口改为 res://scenes/ui/log_window.tscn：根 Window（LogWindow）size (960,620)、min_size (660,400)、不可见、transient=false；场景提供 Panel(#111923、圆角 0、内边距 14)、Column、Filters(%RunsDropdown 横向扩展填充 / %LevelDropdown / %ModuleDropdown)、%Search（占位「搜索时间、活动或错误码」）、%Text（RichTextLabel 可选中、纵向扩展、#d6e5ee、字号 14、等宽 SystemFont）、Actions(%Follow「跟随最新」默认勾选、%CopyButton「复制显示记录」、%ExportButton「导出完整诊断 ZIP」)、%Status(#ffd58a、智能按词换行)、%Picker（FileDialog 保存模式 / 文件系统 / *.zip / 原生对话框）。标题含发行版本号，仍由代码用 src/release_info.gd 拼装，避免版本号漂移。脚本侧删除带参 _init 与 Style 建树代码：log_window 改 setup(logger)，_ready() 在依赖缺失时只设标题并返回，setup() 在 is_node_ready() 时经私有 _initialize() 一次性接线，open()/_refresh()/_matches()/_append() 与全部文案不变；unified_dropdown 改 @onready + %Name 绑定，原生坐标换算（open_menu() 的 Transform2D 与屏幕夹取）、键盘导航（_key_input）、每帧自动收起（_process）与全部公开方法/信号原样保留。
- interface spec：接口文档 client_godot/README.md「日志窗口与下拉控件场景化（0.1.2 第五片）」。实现与契约一致；实现细节补充两条：① 两个根 Button 需在场景里显式写 alignment = 0，因为 Button 的 alignment 默认是居中（契约用例的取值断言正是靠这条抓到了漏写）；② unified_dropdown.tscn 的根脚本没有依赖注入方法，契约守卫以 setup 记空串的方式只断言 _init 无参数。
- commit：SPEC 31b60ff，Red b3cdfc7，Green 0092244。
- Red 证据：test_ui_scenes.gd 报「FAIL: scene exists: res://scenes/ui/unified_dropdown.tscn」「FAIL: scene exists: res://scenes/ui/dropdown_item.tscn」「FAIL: scene exists: res://scenes/ui/log_window.tscn」；test_dropdown.gd 报「FAIL: shared dropdown scene available」并以退出码 1 结束；test_log_window.gd 报「FAIL: log window scene available」并以退出码 1 结束。全部只因目标场景尚未实现，产品实现未动，未伪造 Red。
- 验证及结果：Godot 4.7.1 headless test_ui_scenes.gd PASS（新增三条契约：场景存在性、根节点名与类型、根脚本、_init 无参数、%Menu/%Scroll/%Rows 与 %RunsDropdown/%LevelDropdown/%ModuleDropdown/%Search/%Text/%Follow/%CopyButton/%ExportButton/%Status/%Picker 的 unique_name_in_owner 与 %Name 解析、从代码搬入场景的属性与样式盒、根带 app_theme）；test_dropdown.gd、test_log_window.gd PASS；scripts/check.ps1 21 步全绿（含 virtual-history 的 RichTextLabel < 40、voice-chat 的气泡复用与选区、application-window 未登录 TextEdit 数为 0、dynamics-detail 的分栏子节点顺序）；check_accounts.ps1、check_features.ps1、check_network.ps1 全部 PASS。
- 视觉：真机 GPU 截图 capture_dropdown_ui.gd 与 capture_release_ui.gd 产出 10 张 agentluo-011-*.png，与改动前基线（e626299 独立 git worktree、同机同命令重跑）逐字节比对：dropdown、dropdown-125、dropdown-150、login、models、preferences、dynamics、dynamics-scale-125、dynamics-scale-150 九张 SHA256 完全相同，说明独立原生弹层的圆角、边框、阴影与缩放后宽度未变；logs 一张不同，但在同一基线上连跑两次的差异指纹与「基线与本片」完全相同（差 275 行 / 25 个差异带，首带 29-39 是带时间戳的运行标题，其后是每行日志时间戳），属日志含时间戳的既有不稳定性，非本片引入。capture_voice_ui.gd 与 capture_dynamics_ui.gd 需要 loopback WebSocket fixture，独立运行时因 WS 握手 404 失败，属本机环境限制而非本片回归。
- 作者自审：diff 只含三个新增场景、一个新脚本与其 .uid、五个消费点与两个既有脚本的行为收敛；公开信号与方法逐个对照未变（set_items/get_items/set_selected_id/get_selected_id/set_item_enabled/open_menu/close_menu/is_menu_open/activated 与 open/_refresh/_matches/_append）；account_view.tscn 里 %AccountMode 由「Button + 脚本」换成下拉场景实例后，契约用例断言的 (140,40)/左对齐/clip_text 仍成立；自审时发现并补回四个新文件的文件尾换行，并修掉两处漏写的 alignment；两个 addons DLL 既存删除未纳入提交。
- 保留项（有意）：unified_dropdown.gd 仍保留对 src/preview/preview_style.gd 的唯一引用 Style.ACCENT（open_menu() 的选中行字体色）。按计划「颜色/字号的语义化收敛留作后续独立切片」，本片不做外观改动，第十片删除 preview_style.gd 前必须先收敛这一处。
- 未验证范围：未做人工多 DPI 复核；未推送、未开远程 PR。
### 2026-09-20 界面场景化第六片——消息气泡、语音条与虚拟列表场景化
- 交付行为：聊天消息的渲染单元改为「场景节点树 + 只做行为的脚本」。新增 res://scenes/ui/message_audio.tscn（根 VBoxContainer「MessageAudio」，挂 src/ui/message_audio.gd 与 app_theme.tres）：%Row（间距 6）、%Play 与 %Stop（12 号字，「停止」）、%Wave（96×26、忽略鼠标）、%Time（11 号字、#304553）与 %Error（「语音未能保存」、12 号字）全部由场景提供；波形自绘保留，原内部类 Waveform 落成独立脚本 src/ui/message_waveform.gd 挂在 %Wave 上，两个描线颜色改 @export var played_color（#66ccff）与 remaining_color（#9eb6c4）由场景赋值。新增 res://scenes/ui/message_bubble.tscn（根 HBoxContainer「MessageBubble」）：%System（居中 12 号、#8a9ba4、默认不可见）、%Avatar（38×38、EXPAND_IGNORE_SIZE、STRETCH_KEEP_ASPECT_CENTERED、纵向 SHRINK_BEGIN、round_avatar.gdshader 材质）、%Body（间距 5）→ %Bubble（白底圆角 12 内边距 13）→ %Content 内的 %Text（fit_content、可选中、scroll_active=false、AUTOWRAP_WORD_SMART）、%HistoryPicture/%ImageButton/%Picture 与 %Body 下的 %Caption（11 号右对齐）全部由场景提供，自己气泡的 #dff3ff 样式以 @export var own_style 在场景赋值，configure() 按角色覆盖/移除；头像纹理仍按角色在代码取 user_icon / tianyi_icon，自己气泡仍用 move_child 把 %Avatar 移到末尾。新增 res://scenes/ui/virtual_message_list.tscn（根 ScrollContainer「VirtualMessageList」）：根承担 SCROLL_MODE_DISABLED、%Canvas 横向扩展填充，行的创建改为 message_bubble.tscn 实例化。三个脚本删除带参建树代码与对 preview_style.gd 的依赖，改 @onready + %Name 绑定；system 角色改为隐藏 %Avatar 与 %Body、显示 %System 而不新建节点（消息树里因此多一个空文本 RichTextLabel，可见渲染路径不变）；公开信号与方法（action / audio_action / image_opened / image_action / visible_messages / interacted、configure / update_message / set_audio_state / set_image_state / set_messages / scroll_to_message / scroll_to_latest / get_visible_ids / get_reading_anchor / is_at_latest）与全部文案、颜色、时间格式逐字不变。消费点 chat_view.gd 的消息列表与 chat_preview.gd 的离线样例行改为 preload(...tscn).instantiate()。
- interface spec：接口文档 client_godot/README.md「消息气泡与虚拟列表场景化（0.1.2 第六片）」。实现与契约一致；实现细节补充一条：三个根脚本都没有依赖注入方法（无外部依赖），契约守卫以 setup 记空串的方式只断言 _init 无参数；自己气泡样式用 @export 资源在场景赋值，非自己的白底样式即 %Bubble 的场景默认值，configure() 只在自己气泡时覆盖、否则移除覆盖，因此契约用例可以按样式盒断言白底 / 圆角 12 / 内边距 13。
- commit：SPEC c5147c7，Red 0d5f270，Green d4abc1f。
- Red 证据：test_ui_scenes.gd 报「FAIL: scene exists: res://scenes/ui/message_audio.tscn」「FAIL: scene exists: res://scenes/ui/message_bubble.tscn」「FAIL: scene exists: res://scenes/ui/virtual_message_list.tscn」并以退出码 1 结束；test_virtual_history.gd 报「FAIL: history has virtual message list」并以退出码 1 结束（其余断言在此之后才执行）。全部只因目标场景尚未实现，产品实现未动，未伪造 Red。
- 验证及结果：Godot 4.7.1 headless test_ui_scenes.gd PASS（新增三条契约：场景存在性、根节点名与类型、根脚本、_init 无参数、无注入方法的场景 setup 记空串、%Row/%Play/%Wave/%Time/%Stop/%Error 与 %System/%Avatar/%Body/%Bubble/%Content/%Text/%HistoryPicture/%ImageButton/%Picture/%Caption 与 %Canvas 的 unique_name_in_owner 与 %Name 解析、从代码搬入场景的属性（含 Wave 的两个 @export 颜色、TextureRect 的展开/拉伸/光标、RichTextLabel 的 fit_content/scroll_active/autowrap、Label 的对齐与字号颜色）、%Bubble 的样式盒、根带 app_theme）；test_virtual_history.gd PASS；scripts/check.ps1 21 步全绿（含 virtual-history 的 RichTextLabel 数 < 40、按 UUID 跳转与未知 UUID 不伪造跳转、前插与改宽后的精确阅读锚点、语音状态更新保留选区）；check_accounts.ps1、check_features.ps1、check_network.ps1 全部 PASS（含 voice-chat 的气泡实例复用与选中文本保持、live-chat 的单输入框与气泡文案、history-media 的「打开原图」按钮与「图片预览」、application-window 未登录 TextEdit 数为 0、dynamics-detail 分栏子节点顺序）。
- 视觉：真机 GPU 截图 capture_release_ui.gd 与 capture_voice_ui.gd 产出 12 张 agentluo-011-*.png，与改动前基线（8297592 独立 git worktree、同机同命令重跑）比对：login、models、preferences、dynamics、dynamics-scale-125、dynamics-scale-150 六张 SHA256 完全相同；logs 与五张 voice-ui 参与的是像素级比对而非字节比对——logs 的差异是含时间戳的既有不稳定性（两次基线自比对同样不同，差异带位置相同），五张 voice-ui 截图的聊天区（右半屏）在「基线与基线」「基线与本片」两种比对下都是零差异像素，差异只出现在会动的 Live2D 头像区（左半屏），且两次基线自比对的差异量级与本片相近（例如 paused 15243 vs 15108、scale-150 66869 vs 66589 个差异像素）；人工查看 1200×800 与 paused 两张：自己气泡蓝底圆角、对方气泡白底、左右头像圆形遮罩、语音行的「重放/继续」「停止」按钮、波形与「0.5/2.4 秒」时间文本、以及「已发送」说明的字体、颜色、位置均与基线一致。capture_dynamics_ui.gd 未纳入本片比对（其覆盖的动态窗口不在本片范围）。
- 作者自审：diff 只含三个新增场景、一个新脚本及其 .uid、三个既有脚本的行为收敛与两个消费点的一行改造；公开信号与方法逐个对照未变（未新增、未删除、未改名）；自审时确认三个脚本不再引用 src/preview/preview_style.gd（本片因此少掉三个 preview_style 消费者，第十片删除它前仍需先收敛 unified_dropdown.gd 的 Style.ACCENT）；两个 addons DLL 的既存删除未纳入提交；无顺手改进、无其它视图改动。
- 未验证范围：未做人工多 DPI 复核；capture_voice_ui 的差异区域未逐像素归因到 Live2D 动画的具体帧（只证明聊天区零差异）；未推送、未开远程 PR。