# PR #437 决策记录

# AI 决策记录

## 2026-11-17 #371：仅对动态未读轮询使用有界后台请求与 UI 结果接收

**待定问题**：怎样把 30 秒轮询、400ms 首刷和已有显式刷新入口的未读 HTTP 请求移出 Qt 线程，同时保留身份、TLS、错误保持及窗口销毁语义，而不把 #376 的全部动态读写异步化混进来。

**背景约束**：固定 `ee718b21536e410ce5e4073b068f03b9bfcd68dc`，独立 `bugfix/desktop-unread-async` 工作树；#402 的修改不合入本分支。阶段一只新增本记录与真实 Qt 红灯测试，设计 gate 前不改运行代码。`NetworkClient` 同步 getter 在执行时读取可变 URL/用户名/token，工厂按 `(True,)` 缓存同一个 `requests.Session`，不能把现有 bound getter 直接丢进线程。现有 HTTPS 强制 certifi CA、TLS 1.2 起、链/主机名校验，即使调用方传 `verify=False` 也不能降级。关闭不得在 UI 线程 join HTTP；不存在为徽标造通用异步任务平台的需要。

**调研参考**：

- [Issue #371](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/371)：本轮复核 open / should be solved，无评论；验收为慢 transport 等待期间界面仍可交互。
- 仓库已有 Binder 历史请求使用 daemon Python 线程，LLM 设置使用 Qt Network 异步；只借鉴与本局部适配的机制，不照搬其未覆盖的身份/TLS假设。
- [Qt QThreadPool](https://doc.qt.io/qt-6.9/qthreadpool.html)：pool 析构会等全部 runnable，饱和时 `start()` 入队；全局池不等于每窗口请求自然有界。Context7 已核实 globalInstance/start/waitForDone 语义。
- [Qt QObject 自动连接管理](https://doc.qt.io/qtforpython-6/overviews/qtcore-signalsandslots.html)：销毁接收者可移除连接，但不能据此证明 worker 要 emit 的 bridge 仍存活；已排队回调断连后也可能送达。本项选不用 worker 内 Qt 对象，减少这类生命周期债务。
- [Requests timeout](https://github.com/psf/requests/blob/main/docs/user/advanced.rst)：connect/read timeout 不是墙钟总上限；不能把 `timeout=15` 表述为“后台最多 15 秒”。Context7 已查询确认。
- [Requests Session context manager](https://github.com/psf/requests/blob/main/src/requests/sessions.py)：退出上下文会 close adapters / 连接池；适合为后台只读请求建立独立会话，复用既有工厂装配和 TLS 策略。
- desktop-repair 独立研究确认共享缓存 Session 与可变身份问题；讨论后建议为当前单 ChatWidget 使用 daemon + 单结果队列，排除窗口持有 pool / QThread 析构风险。

**候选方案**
1. **专用 daemon 线程 + 单结果队列 + Qt 自有结果计时器**：UI 线程快照不可变请求上下文；worker 只持快照和容量 1 队列，独立 Session 执行同一解析逻辑并关闭后发布 terminal 结果；UI 20ms 结果计时器只在在途时运行。每 owner 只有一个实际请求与一个合并 dirty 位；无 worker→Qt 引用或窗口捕获。
2. **QRunnable / QThreadPool + Qt queued slot**：Qt 集成较直接，但还需 bridge 独立所有权、销毁断连与队列限制；全局池退出仍可能等 requests，窗口自有池析构也可能阻塞。关闭不能真正取消同步 requests。
3. **QNetworkAccessManager 专用未读请求**：可 abort 且无后台 requests 线程；但必须另做 certifi CA、VerifyPeer、TLS 1.2+、重定向和代理语义对齐，并独立证明认证和响应解析。已有 LLM 样例不包含这些等价保证。

**选择**：方案 1，专用于当前徽标刷新；保留方案 3 为确实需要取消底层网络或严格进程退出期限时的替代。Oracle C2 设计 gate attempt1/3 已通过，lead 随后明确放行最小运行实现；本记录保留设计阶段的提案和实际验证区别。

**选择理由**：保留已有 HTTP/TLS 和公开响应形状；worker 不触碰 UI/Qt 对象，也不读取执行中的可变 NetworkClient。纯数据结果由仍存活的 UI 事件循环消费，窗口销毁自动移除结果计时器，不存在“已销毁 C++ signal bridge 仍被 emit”或 running QThread 析构。daemon 只负责读请求，不新增自动重放写操作；实现不引入依赖或全局 executor。

**未选原因**
- 方案 2：Qt pool 不替本功能提供队列/生命周期预算，采用它仍要处理同步请求不可取消，而应用退出有等待所有任务的附加边界；本局部采用纯数据队列更少所有权风险。
- 方案 3：只为一个只读接口复制受约束 TLS/CA 网络栈，扩大兼容与验证面。不是说 Qt 网络不安全，而是未经显式装配不能声称与现有 requests 强制 CA 策略相同。

**实现接缝（已按设计 gate 授权落地）**：

1. `HttpClientFactory` 提取创建新会话的窄入口，缓存旧入口仍维持旧语义；后台用新会话，和其他网络请求不共享 Session 或可变 headers。
2. `NetworkClient` 在 UI 调用处生成 frozen 未读快照：客户端独立身份标识、身份 revision、URL、用户名、token 与强制 TLS 策略。成功 login / auto_login / set_base_url 推进 revision，防同账号重登或换服再返回的 ABA；现有同步 getter 保持可用，与后台请求复用同一请求/响应解析而非复制第二套契约。
3. `async_request.py` 如需要，仅承载本未读请求的 daemon 启动和 bounded Queue；参数不含 Widget / bound getter / Qt 对象。网络完全退出并 close 独立 Session 后才投递一次 terminal 结果，使用 `put_nowait`，即使界面销毁也不阻塞 worker。
4. `ChatWidget` 维护一份在途记录、一个 dirty 标志与 generation。普通轮询/手动触发只合并，不反复推进 generation；否则每次 timer 都可能把慢请求永久作废。身份改变、已读成功和停止接收才使旧 generation 过期。结果先回收实际在途，不论成功/失效都只允许消耗最多一次 dirty 重请求。
5. 在 UI 线程比对 frozen 上下文与当前身份/revision，只有仍有效 generation 才改徽标。成功保持原计数、99+ 和图标规则，网络失败保留上次已知徽标，不把失败当成已读。身份替换/登出与网络错误分别处理，不把旧账号徽标展示为新账号事实。
6. `on_read_callback` 改为独立“已读成功失效后刷新”接缝，只在既有 mark-read 成功回调触发，读前在途结果不得重新点亮；不修改 DynamicsDialog 的同步列表/评论/标读网络实现。
7. 直接 ChatWidget 关闭停止 polling/result timer、generation 失效并清 dirty；实际 MainWindow 关闭也显式调用相同停止入口，因为子 widget 不保证收到独立 closeEvent。直接销毁时 worker 只有纯数据引用，父 QObject 清理结果 timer，不同步 join、不销毁 running QThread。400ms 首刷在停止后也由停止守卫忽略。

**验证方式与预算**：owner desktop-ui 只跑相关局部证据；全量离线 CI 与 PySide6 6.9.2 由独立 ci-verifier 统一调度，不重复抢资源。

- 已建立首个真实 Qt 红灯，测试创建完整 ChatWidget，通过 `requests.Session.send` 唯一外部 transport 接缝门控真实未读请求，保持 15 秒未完成；0ms 原刷新入口、10ms Qt 心跳、40ms QTest 输入、100ms 探针。预期在请求仍等待时可读到输入 draft 和 Qt 心跳。无实现属性断言、无 mock 立即返回、无手写“创建了线程”验收。
- gate 后复用该测试建立绿灯；再用少量行为场景覆盖叠加刷新只一请求/一次合并、正常计数和99+、失败保留并可重试、身份/revision ABA失效、已读成功与旧结果竞态、真实 owner close / deleteLater 不等待网络且迟结果安全、独立 Session/认证/TLS 原保证。保留现有 TLS 与相关 GUI 测试，不为局部行为机械扩上百组合。
- 实际 Python 3.10.21，PySide6 / Qt 6.11.0，pytest 9.0.3；指定 `C:\Users\Administrator\.conda\envs\agent\python.exe`，不改共享环境。导入和工作目录固定本 worktree；CI 固定 PySide6 6.9.2，版本不同不冒充其证据。

首个红灯实际命令，工作目录为 `client`：

```powershell
& 'C:\Users\Administrator\.conda\envs\agent\python.exe' -c 'import os; os.environ["QT_QPA_PLATFORM"] = "offscreen"; import pytest; raise SystemExit(pytest.main(["tests/test_dynamic_badge.py", "-q", "--tb=short", "-p", "no:cacheprovider"]))'
```

回执：`1 failed in 21.51s`，业务断言实际探针 `(True, False, 'draft', False)`，预期 `(True, True, 'draft', True)`。请求退出后输入才处理、等待期间心跳没有执行，直接复现 UI 饥饿。唯一 job `pwsh-3e204281213243e5` 已收集 exit 1；不是导入或夹具异常。Qt 字体/平台提示原样保留，不将该红灯写成产品通过。

**实施验证记录**：

- 初次绿灯尝试在固定 100ms 探针处得到 `(False, True, 'draft', True)`：独立 TLS Session 尚未进入 transport，但 UI 已响应；`1 failed in 5.19s`。这不是同步阻塞复发，也不能据此宣称通过。依 lead 同意，将测试改为 Qt timer 非阻塞等待 transport started，再安排原输入/心跳探针；5 秒只是测试预算，不是产品启动 SLA。原 15 秒同步红灯仍保留。
- 修正启动探针后真实绿灯：`1 passed in 7.73s`；通过内存替换 `ChatWidget.refresh_dynamic_badge` 为同步 getter、只把测试 15 秒 Event watchdog 缩为 0.3 秒，修正后的测试仍产生预期业务 AssertionError，证明未弱化为“创建了线程”。最初一次内存探针错误绑定 Event.wait 造成 TypeError，不计业务证据；修正为类未绑定原方法后完成敏感性验证，不改项目运行代码。
- 最终局部命令在 `client` 运行，环境仍为指定 Python3.10.21 / Qt6.11.0：

```powershell
& 'C:\Users\Administrator\.conda\envs\agent\python.exe' -c 'import os; os.environ["QT_QPA_PLATFORM"] = "offscreen"; import pytest; raise SystemExit(pytest.main(["tests/test_dynamic_badge.py", "tests/test_tls_connections.py", "tests/test_login_dialog.py", "-q", "--tb=short", "-p", "no:cacheprovider"]))'
```

- 最终结果 `38 passed, 4 warnings in 23.55s`：未读行为 12 个场景、TLS 9 个（原 WSS3 / 缓存 HTTPS3 / 新独立 Session HTTPS3）、本分支原登录窗口回归17个。4 条均为既有 websockets legacy 弃用提示，不将其藏掉。
- 未读场景覆盖真实输入/Qt 心跳、单在途与8触发一次合并、计数7/99+/0、超时与非法count保留9后重试、真实动态窗口标读成功回调失效、实际同字段登录且凭据保存异常后的 revision、URL/用户名/token变更旧结果丢弃、实际 MainWindow close 与 deleteLater、不经 close 的 ChatWidget删除，以及关闭早于400ms不启动首刷。删除后 worker 仍只持纯数据；测试 transport 释放后检查无 Qt excepthook 错误。
- 真实发送观测验证 URL/query/Bearer、timeout15/verifyTrue、每次 Session 与缓存和前次都不同，前次 Session关闭后下一次才开始；独立 Session 真实本地 HTTPS 证据保留 trusted/wrong-host/untrusted 和环境失效CA、verifyFalse不可降级。
- 实际导入源均为 `issue-371` 树的 main_ui / async_request / network_client；未拿 #402 的77测试数字充当本分支登录回归。全量离线 CI、CI固定PySide6 6.9.2、真实服务/打包视觉仍待独立 verifier / 后续验收，本轮不宣称已完成。

**风险与回滚**：选 daemon 意味着取消的是结果接收，不是底层 HTTP；进程结束可直接中止 daemon，不能保证 abrupt shutdown 时 Session finally 一定执行，更不能声称“请求已取消”或“15 秒清完”。有界承诺为现有单 ChatWidget owner：最多一个实际 HTTP、一个合并意图、一个 terminal 结果；不承诺任意反复创建多代窗口的全局上限，不引入全局平台来解决不存在的路径。后续若出现多窗口重建或要求强取消，另审预算/方案。最终可独立回退本徽标异步接入、快照和新会话创建入口；无数据迁移、服务器协议、凭据格式、轮询周期或 #376 写操作变更。完成 runtime 后另经 Oracle C2 gate 才 commit，不 push / GitHub 写。

# PR #436 决策记录

# AI 决策记录

## 2026-11-17 #402：由当前页面显式拥有 Qt 默认提交按钮

**待定问题**：登录输入框的 Return/Enter 应触发登录，而非低频入口；还需决定低频按钮获得焦点时以及切换注册页后的默认动作归属。

**背景约束**：维护者已授权非人在回路，在固定 `ee718b21536e410ce5e4073b068f03b9bfcd68dc` 基线上仅修改登录对话框、其测试和本记录。保留 Esc 防误退出、显式关闭、鼠标与焦点按钮 Space、登录及注册原校验，不混入 #376 异步网络或未合并 #359 协议。原有 17 个测试不得删除或弱化。实现后须经 Oracle gate 才能提交，不推送或写 GitHub。

**调研参考**：通过 Context7 核对 Qt 官方 Qt for Python 文档，采用框架自己的默认按钮机制，不另造键盘分发逻辑。

- [QPushButton default / autoDefault](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QPushButton.html)：默认按钮处理 Return/Enter；聚焦的 auto-default 按钮可以抢占默认按钮；一个对话框只有一个默认按钮；焦点按钮仍可用 Space 激活。
- [QTabWidget currentChanged](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QTabWidget.html)：页面索引改变发出通知，可在所有按钮完成父子装配后初始化并随切页更新默认按钮。
- [QSignalSpy](https://doc.qt.io/qtforpython-6/PySide6/QtTest/QSignalSpy.html) 与 [QTest](https://doc.qt.io/qtforpython-6/PySide6/QtTest/QTest.html)：真实发送按键/点击，观测 clicked、accepted、finished，而非把 isDefault/autoDefault 内部属性当验收。
- [Issue #402](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/402)：本轮复核为 open、bug / should be solved，正文的输入框误开重置与离屏复现均落在本修复范围；无评论。UI/UX 技能的初次检索只得到通用提交反馈与网页键盘导航，未据此扩展 UI；具体桌面策略以 Qt 官方语义为准。

**候选方案**
1. **原生显式默认策略**：所有顶层表单按钮关闭 autoDefault；初始化与 currentChanged 时将当前页主提交按钮设为 default、另一页取消 default。低频按钮保留鼠标与 Space，不再因焦点改变 Return/Enter 的主动作。
2. **只设登录按钮 default**：代码最少，但不处理聚焦 auto-default 的抢占，也不处理注册页、隐藏页与历史默认状态。
3. **硬拦 Enter 或逐输入框接 returnPressed**：可直接调用提交，但硬拦全部 Enter 会误走登录；逐框连接会新增重复入口，并可能与 QDialog 原生默认处理叠加，需要额外处理焦点、注册及子窗口边界。

**选择**：方案 1。登录页 Return/Enter 统一由登录主提交处理；注册页由注册主提交处理。次要按钮的有焦点激活保留 Space 与鼠标。

**选择理由**：只增加 11 行运行代码，使用 Qt 原生行为、无新依赖、无认证/数据改动。需要在布局装配完成后初始化，因为无 QDialog 父级时的 setDefault 不足以建立对话框级默认。显式切页管理配合关闭 autoDefault，也避免主按钮先获得焦点时残留的隐藏页默认状态。

**未选原因**
- 方案 2：真实 QTest 已证实，仅设登录 default 后仍有 4 个聚焦低频按钮场景误激活；加入按页 default、但主按钮仍保留 autoDefault 时，有 16 个“主按钮焦点历史→注册成功返回登录”场景在登录输入框按键未激活登录。不是仅凭内部属性推测。
- 方案 3：超出本次小范围默认策略；绕过原生提交路径易破坏注册、空表单校验和子对话框，且引入不必要的分发分支。不存在为本缺陷拦截全部 Enter 的需要。

**验证方式**：在 `client` 目录使用指定解释器执行：

```powershell
& 'C:\Users\Administrator\.conda\envs\agent\python.exe' -c 'import os; os.environ["QT_QPA_PLATFORM"] = "offscreen"; import pytest; raise SystemExit(pytest.main(["tests/test_login_dialog.py", "-q", "--tb=short", "-p", "no:cacheprovider"]))'
```

本轮实际环境：Python 3.10.21、PySide6 / Qt 6.11.0、pytest 9.0.3；解释器为 `C:\Users\Administrator\.conda\envs\agent\python.exe`，实际导入源码为当前 `issue-402` 工作树的 `client/src/gui/login_dialog.py`。CI 固定 PySide6 6.9.2，未安装/切换共享依赖，本轮结果不冒充该版本或远端 CI 证据。

| 阶段 | 真实结果 | 观测依据 |
| --- | --- | --- |
| 改动前既有基线 | 17 passed | 原 Esc、关闭、登录、注册和子窗口测试原样运行 |
| 输入框 Return/Enter 红灯 | 4 failed, 17 passed | 用户名/密码 × 两键：reset clicked=1，login clicked=0 |
| 完成装配后显式登录 default | 21 passed | 原 17 + 输入框 4 个场景 |
| 聚焦低频按钮红灯 | 4 failed, 21 passed | reset/server × 两键：次要 clicked=1 |
| 低频按钮关闭 autoDefault | 25 passed | 聚焦次要按钮的 Enter 改由登录处理 |
| 注册/切页红灯 | 16 failed, 25 passed | 4 个注册框 × 两键 × 两条切页路径，注册主提交未激活 |
| 增加按页 default 管理 | 41 passed | 注册正确提交，成功回登录后仍能键盘登录 |
| 空表单与显式入口安全网 | 61 passed | 实际 QMessageBox 文案；鼠标/Space 打开正确子窗口，返回后仍能键盘登录 |
| 主按钮焦点历史红灯 | 16 failed, 61 passed | 先聚焦主按钮再切页/提交，返回登录后主动作缺失 |
| 所有顶层按钮关闭 autoDefault | 77 passed | 旧 17 原保证全部保留；新增 60 个参数化场景全部通过 |

运行代码不拦截 Return/Enter，不修改原 Esc 处理；测试通过真实事件和信号观察动作及对话框结果。网络与凭据仅在已有注入边界隔离，不调用真实账号服务。新增测试通过 black 26.5.1 / ruff 0.14.10 的定向检查；运行文件原有 QHBoxLayout 未使用导入 F401 在 HEAD 与当前各 1 项，未混入无关清理。全量离线 CI 由独立 verifier 统一调度，打包版、人工窗口/真实服务登录、PySide6 6.9.2 尚未验证。

**风险与回滚**：低频按钮不再以 Return/Enter 显式激活，使用 Space 或鼠标；这是为稳定主动作做出的有意选择。关闭 autoDefault 可能改变平台样式预留的默认按钮边框空间，离屏测试不证明打包版视觉。若交互不符预期，可独立回退本原子修改（当前页 default 管理、四个 autoDefault 设置及对应新增测试）；无数据迁移、配置或服务端变更。Oracle gate 前保留未提交 diff，不自行 merge/rebase/push。
