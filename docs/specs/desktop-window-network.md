# 桌面账号与动态窗口的非阻塞网络操作

> 设计基线为 `ee718b21536e410ce5e4073b068f03b9bfcd68dc`。2026-11-17 C3 design attempt1/3 经非作者 Oracle PASS；账号phase经实施门禁及lead授权提交`42ffeb86`。随后动态phase按精确scope放行并形成局部证据，当前待动态实施门禁及完整CI，不能把局部通过等同整单合并/发布。

## 用户故事

1. 作为登录用户，我希望点击登录、注册、重置账号、验证服务器后仍能看到窗口重绘与请求状态，以便知道操作在处理，而不是应用卡死。
2. 作为登录用户，我希望在同一次请求未结束时重复点击或按键只提交一次，失败后保留输入并由我决定是否重试。
3. 作为浏览动态的用户，我希望打开窗口、刷新、翻页、选动态、加载评论时不阻塞聊天和当前窗口，迟到内容不能替换我后来选择的动态。
4. 作为发布者，我希望发布动态或评论期间不重复发送，失败保留草稿；关闭窗口后，不再出现迟来的弹窗、跳页或登录副作用。

### 交互示意

```text
登录/注册                       动态
┌─────────────────────┐       ┌───────────────┬────────────────────┐
│ 用户名、密码、…       │       │ 刷新中… [禁用] │ 当前动态 B          │
│ [登录中… 禁用]       │       │ 旧列表保留     │ 正在加载评论…       │
│ 相关账号/换服入口禁用 │       │ A / B 可选择   │ 草稿保留            │
│ 标题栏关闭仍可用     │       │ 页请求不重复   │ [发送中… 禁用]      │
└─────────────────────┘       └───────────────┴────────────────────┘
```

禁用只限制与当前请求冲突的操作，不禁用整个窗口；真正的 busy 守卫放在操作入口，不能只靠按钮置灰挡住键盘信号。原登录 Esc 防误退出、子窗口 Esc 与显式关闭策略保持。

## 验收标准

| 编号 | 状态与输入 | 可观察输出 |
| --- | --- | --- |
| A1 | 点击登录，令真实取公钥 transport 持续等待；期间重复点击并在提交按钮有焦点时按 Return | Qt 心跳/重绘/可用控件仍响应；对应按钮显示处理中并禁用；只有一条取钥链，没有第二次提交；输入快照不随之后编辑变化 |
| A2 | 登录、注册、重置的取钥成功后，令实际 POST 等待；重复点击/按键 | 取钥、加密、POST 整段离开 GUI；每次操作只提交一次，无隐式重试；失败后恢复操作、保留草稿，主动重试才发新链 |
| A3 | 请求未完成时关闭登录或其子窗口，再放回成功响应 | 不再弹窗、accept、切页、保存过期凭据/服务器或启动 WS；界面取消不被称为撤销已经送达服务端的写入 |
| A4 | 验证候选服务器时延迟返回，或关闭后换候选地址 | 验证期间 UI 响应；只有仍有效候选成功才保存并应用；旧结果不能覆盖新地址，失败可手动重试，TLS 不降级 |
| A5 | 从实际动态窗口入口打开，首屏请求未完成 | 构造立即返回，先显示加载态；窗口可交互；首屏成功才异步标读，失败不标读；本窗口所拥有的请求不在 UI 内执行 HTTP，外部未读回调仍见下述 #371 排除边界 |
| A6 | 刷新/翻页重复触发，页面请求失败或返回 | 同一列表槽最多一个请求；不会无限排队或重复追加同一 cursor；失败保留旧列表和 cursor，成功保留响应完成时的选中项/滚动位置，不把等待期间新选的 B 抢回请求开始时的 A |
| A7 | 先选 A 后选 B，让 A 的评论迟到；或评论刷新期间再次选择 | 只把符合当前 identity、feed/selection generation 和目标 ID 的内容放进详情；B 可见状态不被 A 覆盖；读请求仅合并一个最新目标 |
| A8 | 发送评论按钮与 CommentInput 的 Return 连续触发，或发布动态重复点击 | 写操作共享有界写槽，最多一次实际 POST；目标 ID 和正文在开始时固定；失败保留对应草稿并恢复操作；成功只处理一次，不自动重放 |
| A9 | 写入在途时换选择/关闭并重开动态窗口，随后释放旧结果 | 不把旧评论清草稿或追加到新动态，不重复关闭编辑器/提示成功；隐藏不释放仍在执行的写槽，重开不能绕过在途门禁；明确失败/成功未知均允许用户在终态后主动确认/重试 |
| A10 | 实际窗口 close/reject/deleteLater、身份/服务器失效、过期结果回收 | GUI 不 join HTTP；worker 无 Qt/Widget/Binder/可变 NetworkClient 引用；过期/失败结果也回收槽，不永久 busy；关闭时不启动新的排队工作 |
| A11 | 使用独立会话发送所有上述请求 | 保持原端点、query/body、Bearer、每次新公钥、强制 certifi/TLS1.2+/链/域名校验；不与主客户端共享 Session、Cookie、可变 headers 或身份；不记录密码/token |

### 证据分工与最小预算

- 作者 desktop-ui：真实 Qt 点击/有焦点 Return、QTimer 心跳、门控 transport、窗口/信号及凭据/WS 边界观测。已有首红见备注，不要求设计阶段再造全部动态红灯。
- 实施按账号与动态两个紧密相关的小步验证，但仍以本规格全部交付为一个 #376 PR；只完成登录不能关闭整单。
- 账号四动作各一个参数化慢响应/单在途/失败手动重试场景，再补关闭迟登录不提交；动态用列表/选择和写槽两个受控竞态场景覆盖关键路径，不做机械上百组合。
- 复用真实本地 TLS 回归证明新会话；保留既有登录 Esc/关闭/成功语义，因异步仅调整等待方式，不降低断言。最终完整离线 CI 由 ci-verifier 统一调度。
- 已知验收范围：本规格不含 #371 的未读请求。基线 ChatWidget.open_dynamics 末尾以及标读成功传入的 on_read_callback 都仍可能同步调用 refresh_dynamic_badge；若从主窗口入口测试，必须把该已知独立请求隔离并披露，不能宣称本单独修复主界面所有网络。动态窗口自身构造及列出操作均须非阻塞。

## 模块与架构

### 实际调用链与副作用

以下行号均为独立基线已读实现，不引用 #371 增加后的行号作为本单基线。

| UI 入口 | 网络与副作用 | 本项 seam |
| --- | --- | --- |
| LoginDialog.do_login，172–185 | Binder.on_login→NetworkClient.login 55–73：AuthApi.login 21–49 取钥/加密/POST，随后改 user/token、写凭据、start WS | 把纯认证结果与本地有效结果提交分开；不能把整个 Binder/NetworkClient.login 丢进 worker |
| do_register，187–206 | Binder→NetworkClient.register→AuthApi.register 62–83；取钥+POST，成功提示并回登录 | UI 校验/快照→独立网络请求→仍有效的 UI 处理 |
| 重置子窗口闭包，249–271 | Binder→reset_account→AuthApi.reset_account 85–111；取钥+POST，成功改父窗用户名/页签 | 子窗口 owner ticket；关闭失效但实际请求未结束前父认证槽仍占用 |
| 换服闭包，299–325 | GET /auth/public_key，成功写服务器文件、调用 Binder.on_set_base_url→NetworkClient/AuthApi/WsTransport.set_base_url | 候选 URL 验证纯网络；有效结果的应用在 UI 守卫后一次执行 |
| DynamicsDialog.__init__，355–374 | 构造中同步 load_dynamics，成功立即同步 mark_read | 构造只装配 UI，用 Qt 首次事件发读；成功回调再调标读槽 |
| load_dynamics/load_more，587–646 | NetworkClient.get_dynamics；清/增列表，更新 cursor，选择首项引发评论读取 | 固定列表槽与 feed generation；同槽不重入 |
| on_dynamic_selected/load_comments，660–700 | 当前 dynamic ID 的评论 GET，返回改详情 | 独立详情读槽，单实际请求+一个最新选择意图；ID+generation匹配才画 |
| publish_dynamic/editor，325–340/708–717 | create_dynamic POST，成功刷新列表并 accept editor；旧实现虽禁按钮仍同步 | 动态写槽执行一次 POST；UI 有效成功再刷新/关闭；不重放写入 |
| publish_comment，719–735 | 按钮和键盘 signal 同入口；POST 后清草稿+刷新评论 | 入口 busy 守卫、固定 ID/正文；清草稿需还属于同一操作 |
| mark_read，655–658 | POST read，成功才 on_read_callback | 同一写序列、独立一次成功通知；不把失败当已读 |

### 模块划分

1. **窗口操作模块**：新增独立命名的 `window_operation.py`，Qt/UI-owned operation runner。只给上述窗口用，不复用 #371 的未读 helper，也不改它。Interface 仅启动、使当前接收失效、停止/销毁；固定槽位由窗口明确装配，不建动态注册表、全局线程池、任务平台或自动重试策略。
2. **认证网络模块**：AuthApi/encrypt_pwd 允许显式独占 Session；worker 从冻结 URL/输入创建纯 AuthApi，取新公钥、加密、POST 在同一独立 Session 内完成。同步入口继续兼容，无公钥缓存回退。
3. **认证应用模块**：NetworkClient 提供纯请求准备和有效结果应用的两个具名 Interface；应用步骤由 UI-owned 调用方持 ticket/身份检查后同步短执行。`AgentBinder` 增加明确 prepare/apply 注入，`main.py` 明确接线；不靠 `callback.__self__` 反射、不把 QObject bound method 在 worker 执行、不生成第二套 NetworkClient。
4. **动态网络模块**：冻结服务器、user/token、请求参数/正文/ID/cursor，独立会话运行原端点/解析；不在 GUI 重新复制 HTTP 协议。现有同步 NetworkClient 方法共用这些纯请求解析，不改变公开响应形状。
5. **UI 窗口模块**：表单校验、pending 文案/禁用、页签/草稿、列表/详情渲染与所有 QMessageBox/accept/reject 只在 GUI。必要时把登录的两个闭包子对话框提成同文件私有小类，以使 owner 失效有明确位置，不做无关样式重写。

### 数据流

```text
真实点击 / 有焦点按键 / 选择 / 滚动
  → GUI 校验 + busy 守卫 + 冻结输入与身份
  → 窗口固定槽 runner.start(prepared request)
  → daemon：独立 TLS Session → 网络/加密 → close Session → Queue(1)
  → GUI-owned timer：先回收实际在途 → 校验 owner/operation/identity generation
  → 只在有效时 apply 本地登录/换服副作用或渲染/清对应草稿
```

worker 只拿纯请求、停止令牌和一条结果队列；不拿 UI callback、Widget、Binder 或可变客户端。停止令牌可在取钥完成后/POST前检查，尽量避免关闭后尚未发送的写入；但检查与网络发送之间不是跨进程事务，不能保证已经在途的 POST 被取消。

### 接口规范与状态机

**窗口 runner**：`start(request)` 在 busy 时返回未启动，不再发 HTTP；`invalidate()` 推进接收代际，不清仍实际运行的 busy；结果成功/失败/失效均先回收槽。只读槽允许一个明确的最新意图替换，写槽不保存重试意图。Queue 容量 1、非阻塞放取；Qt timer 仅实际在途时运行，关闭不 join。

**认证单槽**：登录、注册、重置、换服共享父登录窗口一个在途槽。pending 冻结相关提交、表单/页签及会改变身份的入口，标题栏关闭可用。子窗口关闭使结果失效但不提前释放实际槽；父窗不允许在旧重置/注册未终态时启动冲突操作。终态恢复控件/草稿，失败由用户显式点击再试，不自动队列 POST。

**认证结果应用**：网络认证阶段不改 `user_id/login_token/message_token`，不保存凭据、不 start WS。GUI 在 owner仍有效、ticket未消费、客户端上下文仍匹配时，标记ticket已消费，再执行本地身份/凭据和 WS线程启动，最后 accept。`WsTransport.start()` 当前仅启动线程、不等待就绪；不能在 GUI 调 `wait_until_ready`。保存凭据是现有本地操作，不新增 HTTP；异常和部分本地提交结果如实报告，不自动重放认证。模型绑定仍由原主入口在登录Accepted后构造主窗口，不搬进 worker。

**身份代际**：使用本单明确的账号/服务器上下文 revision，字段实际替换即升代际，不能等凭据保存/WS启动成功后才升。冻结对象还含客户端不复用标识、URL/user/token；动态结果和本地登录/换服apply均校验。实现不导入 #371 的 DynamicUnreadRequest；未来同点 revision 可在合流时局部对齐。

**动态固定并发预算**：最多一个列表读槽、一个评论读槽、一个串行写槽。首屏/刷新/翻页共列表槽；评论读有最多一个最新选择；发布动态、发表评论、mark-read 共写槽，写在途拒绝其他写且不排队重复POST。首屏成功需要的首次标读可以作为一次后续明确状态转换，若写槽忙只合并一个标读意图，不能挤出/重放用户写操作；优先用户操作、终态后最多一次标读。列表/评论GET可与固定写槽并发，但写完成使相关读 generation 失效，旧读不能覆盖写后状态。

**动态关闭与重开**：当前主界面缓存 DynamicsDialog，close 通常只是隐藏。隐藏时失效所有可呈现结果、清只读后续意图，不解除仍在途实际请求的写槽。保留最小终态接收以回收槽，但不弹窗/清草稿/accept。重开先读取当前 busy 状态，旧请求结束前不能再发相同写；旧结果终态后可恢复可用状态并提示刷新确认，不自动重发POST。直接删除时Qt timer随owner销毁，worker只有纯数据队列。若未来改为每次新建窗口，跨代并发/写幂等需要另审，当前不宣称全局取消。

## 备注

### 关键技术选型

- 独立PR从 ee718b21 实施。沿用已接受的 daemon/Queue/GUI timer机制思想，但本单窗口请求 runner独立命名、独立实现，不 import未合入#371专用徽标模块。确有多个窗口调用点才建立本单 seam，不推广其他窗口。
- 在本分支把会话创建从缓存工厂窄提取，保持 certifi/TLS1.2+/代理原保证；不变更全局 Session缓存策略，不共享 Session跨线程。
- daemon不等于强取消；Requests timeout不是墙钟总时限。超时后服务器可能已成功，尤其注册/重置/发布，不自动重放，不声称端到端exactly-once。

### 非目标

- #402 登录默认按钮修复不在本PR差异中；重复Return测试只把焦点放明确提交按钮。本单不硬拦Enter、也不把所有Enter直跳登录。未来#402的11行策略可在同文件按钮装配/切页处局部合流。
- #371 未读轮询、通用网络框架、服务端幂等协议、用户协议#359、自动网络重试、偏好/LLM设置窗口、Live2D/音频改造均不包含。
- `main.py`事件循环前的自动登录是旧同步启动契约，不在维护者本轮四类手动操作验收内；本PR不宣称它已异步。若后续纳入，应另锁定启动状态/自动登录失败回表单验收，不能把worker+UI wait当修复。
- 不改真实用户凭据/配置，不使用真实账号验收；不保证磁盘/DPAPI本地存储永远无延迟，不因此放宽全部HTTP必须离开GUI的要求。

### 首个真实红灯

`client/tests/test_window_requests.py`：真实 LoginDialog→Binder→NetworkClient→AuthApi→encrypt_pwd→Session.send；门控取公钥，失败用503，无服务端登录副作用。transport started后安排Qt探针，重复mouse+有焦点Return。预期 `(pending=True, heartbeat=True, enabled=False, requests=1)`，实际 `(False,False,True,3)`，`1 failed in 7.08s`。1秒watchdog只是防旧实现挂死，不是产品SLA。运行实现diff仍空；exact回执归档交设计审核。

### 未来目标与合流

本PR只交付#376。#402、#371在各自PR合入后，再用常规局部冲突处理对齐按钮策略、工厂新会话和身份revision；不在本source branch合入三个工单差异。不为预测冲突提前建集成框架。最终门禁必须单独验证本分支，再以实际合流内容复验，不复用历史数字作全量绿。
