# PR #440 决策记录

# AI 决策记录

## 2026-11-17 #376：独立窗口请求与有效结果应用分离，不依赖未合入工单

**待定问题**：让手动登录、注册、重置、换服与动态读写全部 HTTP 离开 GUI，同时避免把整个 Binder/NetworkClient 的可变身份与本地副作用放进 worker；还需在 #402/#371 未合入时保持一个 PR 只交付 #376。

**背景约束**：lead 已创建 `issue-376` / `bugfix/desktop-window-network`，基线 `ee718b21536e410ce5e4073b068f03b9bfcd68dc`。目前只授权本记录、模板规格及必要测试，设计 gate 前运行实现零改。#376 维护者评论明确要求真实非阻塞、同操作一次、失败手动重试；只禁按钮仍同步不合格。不得合入 #402/#371/#359，不改未读行为、全局环境或真实账号数据。旧17个登录回归仍是安全网，不能因body过期称零测试。

**调研参考**：

- [#376 正文](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/376) 与 [维护者补充验收](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/376#issuecomment-6663141756)，本轮复核 open / should be solved。按钮点击入口要在慢响应未完成时证明可响应与不重入，失败后可以主动重试。
- [Qt QDialog done/finished](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QDialog.html)：accept/reject/done结束局部exec并发信号；普通隐藏/删除不保证finished通知，故关闭、隐藏重开、直接delete的有效性必须明确，不用finished单一信号冒充生命周期覆盖。Context7已查询。
- [Qt QWidget enabled](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QWidget.html)：禁用限制输入，但不能替代操作入口busy守卫，也不解决同步HTTP饥饿。
- [Requests Session上下文](https://github.com/psf/requests/blob/main/docs/user/advanced.rst) 和 [Session实现](https://github.com/psf/requests/blob/main/src/requests/sessions.py)：独立Session退出上下文close连接池；沿用既有TLS adapter不等于复制共享Session。Context7已核查。
- [Requests timeout语义](https://requests.readthedocs.io/en/latest/user/advanced/#timeouts)：连接/读取不是硬墙钟deadline；读写不自动重试，尤其已经送出的POST无法以丢弃回调撤销。
- 已读真实链：LoginDialog→AgentBinder.on_login→NetworkClient.login→AuthApi.login→encrypt_pwd取新公钥/加密/POST；NetworkClient随后改身份、写凭据、start WS。WsTransport.start只启动后台线程，无UI等待；模型绑定由main.py在登录Accepted之后装配主窗，不能移进认证worker。
- 仓库动态编辑器已在同步发布期间禁按钮，但仍阻塞；CommentInput独立Return信号会绕过仅按钮禁用。动态窗口构造同步读+标读，选择回调还同步评论；它们必须由各自有效generation控制。
- #371已审研究可借“纯请求、独立Session、daemon/有界队列、GUI接收”的机制，不 import 其专用Unread helper。#402的11行default/autoDefault仅未来同文件局部合流，不在本PR提前修默认按钮。

**候选方案**
1. **本单窗口请求 runner + 纯网络请求/有效结果应用分离**：小Interface仅start/invalidate/close，固定槽由各窗口声明。worker拿冻结输入/身份/独立Session，GUI检查operation owner/identity后才提交本地认证副作用或渲染。动态用固定列表读、评论读和串行写三个槽，不建全局平台。
2. **把Binder/NetworkClient绑定方法直接丢线程**：改动表面少，但后台可能触及QObject、可变Session/身份，并在窗口关闭后保存凭据/start WS；只在UI丢结果无法撤销已经发生的本地副作用。
3. **合入#371后推广其徽标helper或整体换Qt Network**：前者让#376 PR携带多工单差异并把单一Unread模块泛化为平台；后者需复制取钥/加密/认证与certifi/TLS/代理兼容面。当前不为复用或强取消的新需求承担这些扩大。

**选择**：方案1，独立ee718b21分支实现#376；规格见 [desktop-window-network.md](docs/specs/desktop-window-network.md)。C3 design attempt1/3经非作者Oracle通过，lead随后只授权账号phase运行实现；动态phase尚未实施，设计通过不代表整单运行交付。

**选择理由**：把真正变化集中到现有网络模块与窗口seam，GUI/HTTP/本地身份副作用各有确定线程；已有多个本单窗口调用点能共享窄runner的busy/终态/生命周期逻辑，而无需注册表或全局executor。独立会话提取仅建立同一TLS装配，旧缓存行为不替换。原同步NetworkClient接口保留共用纯请求解析，以免创建第二套认证/动态协议。

**未选原因**
- 方案2：关闭迟登录仍可能偷偷登录；认证并不是一个无副作用函数，线程化整个调用链会固化错误seam，无法由迟到回调guard补救。
- 方案3：#371源branch未merged，直接合入会失去一PR一交付；其27行专用Unread helper不是认证/写操作通用接口。Qt Network可在未来真实要求强取消时重审，但本次保持旧信任来源/密码刷新更小；不把默认系统CA称为已保留certifi。

**关键取舍与边界**：

- 登录/注册/重置/换服共父登录窗一个实际在途，pending冻结会改变身份的相关表单/页签/入口，不禁标题栏关闭；子窗口关闭只失效接收，不提前释放实际在途槽。
- worker认证仅取新公钥、加密、POST；有效GUI apply才一次写身份/凭据并启动WS。调用方持未消费ticket与上下文revision，代际在字段实际替换时更新。不能用反射从Binder回调探出NetworkClient、不能把bound QObject送后台。
- 关闭可设置停止令牌以在POST前尽量拒绝未发写入，但HTTP已送达可能服务端成功；既不声称撤销，也不自动重放。网络异常后的用户主动重试不等于服务端幂等；无协议更改/幂等键承诺。
- 动态read用单槽+至多一个最新选择意图；post/comment/read-confirm共享固定串行写槽，用户写不排队重复。首次列表成功才标读；若写槽忙仅合并一个明确标读意图。写成功使相关旧read generation失效。
- 动态窗口当前缓存重开：隐藏后仍保留实际写槽直到终态，不弹窗/清草稿；重开不能绕过在途guard。comment固定目标/正文，成功清稿前检查仍是同一草稿/操作，失败保留；A迟评论不盖B。
- 基线ChatWidget.open_dynamics结尾仍调用#371负责的同步unread，#376独立PR不修改它；本单证明窗口自身所列请求非阻塞，不谎称主界面全部HTTP已异步。自动登录在main.py局部exec之前的旧同步启动契约也暂不包含，若扩入须重新锁定启动验收。

**验证方式**：已新增首个真实Qt红灯，不在设计阶段继续堆所有动态红测试。工作目录 `client`：

```powershell
& 'C:\Users\Administrator\.conda\envs\agent\python.exe' -c 'import os; os.environ["QT_QPA_PLATFORM"] = "offscreen"; import pytest; raise SystemExit(pytest.main(["tests/test_window_requests.py", "-q", "--tb=short", "-p", "no:cacheprovider"]))'
```

实际 `1 failed in 7.08s`：真实LoginDialog按钮→真实Binder/NetworkClient/AuthApi/encrypt_pwd，只有Session.send外部transport门控公钥请求。transport started后Qt timer检查心跳、重复mouse和明确提交按钮焦点Return；期望 `(True,True,False,1)`，实际 `(False,False,True,3)`，即请求返回后才运行探针、等待期间心跳无运行、按钮可用且重复链3次。1秒Event看门狗是测试终止保护，不是产品网络时限。真实POST未到达，因为fake取钥503，未碰用户账号。

指定Python3.10.21 / PySide6-Qt6.11.0 / pytest9.0.3，不安装/修改共享依赖；CI钉6.9.2，后由verifier调度。实施阶段保留上述业务判据，用少量真实点击+transport门控证明四账号动作、动态列表/选择和写操作；失败手动重试、owner关闭迟成功不得提交本地身份；认证/TLS沿现真实本地测试，不以内部busy属性替代验收。

**账号phase实施与证据**：

- 纯 `AccountRequest` 不持客户端/Qt/Binder，网络使用新独立Session；同一Session显式传入AuthApi和encrypt_pwd，取每次新公钥、加密、POST全链均在worker。缺省`session=None`保留旧直接encrypt_password调用及旧同步NetworkClient接口。登录/换服有效GUI apply才改本地身份/凭据/WS，revision在字段改变时立即递增。
- 父登录窗口只有一实际槽，20ms Qt接收terminal，worker不回调UI；ticket在有效呈现之前先消费一次，交付回调含模态QMessageBox期间仍保持busy防重入。子窗口关/删只设置其旧ticket的独立Event，不清实际槽；旧child延迟删除不能取消新操作。真正owner删除通过不持Qt的单元素token holder设置当前token，不累积任务或QObject引用。
- 首红转绿：同测试增生产同款具名prepare/apply/context注入，核心pending/心跳/禁按钮/一次GET断言不变，`1 passed in 7.85s`。job `pwsh-f1fe9d399c764c0e`已收集exit0。
- 四动作测试一次出现`1 failed,6 passed in17.97s`：错误要求换服成功已关闭的子窗按钮重新enable；改为观察成功关闭和GUI保存，并补换服失败后主动重试。该测试期待错误不计运行回归；不以延长时间掩盖。
- 原17测试完整行为断言保留；fixture新增纯成功request与GUI apply替身，原binder.on_login/on_register Mock只在有效GUI apply中用于保留一次处理观测，不在worker调用。两个成功用例只增加Qt等待，不删Esc/close/accepted/页签/子窗断言。真实NetworkClient与Session链另由新账号测试证明，不能把Mock别名当生产仍走旧同步Binder。
- 账号行为最终10例覆盖公钥在途、四动作POST/服务器GET在途重复mouse/明确按钮Return、失败手动重试且无自动重放；真实RSA解密验证实际密文使用新取公钥；取钥与POST同独立Session且HTTP线程非GUI；成功登录保存只在GUI、WS只启动一次；父关闭POST迟成功不改identity/save/WS；公钥阶段关闭不发后续POST；子关闭实际槽不释放、旧child删除不取消后续登录；身份变化拒迟登录；旧同步login/register/reset返回形状和成功副作用兼容。
- 相关命令在`client`：指定解释器执行pytest `tests/test_window_requests.py tests/test_login_dialog.py tests/test_password_key_rotation.py tests/test_tls_connections.py tests/test_credential.py -q --tb=short -p no:cacheprovider`。实际最终 `40 passed,4 warnings in22.72s`（新账号10、旧登录17、密钥轮换1、TLS9、凭据3）；4警告为既有websockets legacy弃用。PySide6/Qt仍6.11.0，Python3.10.21；来源打印均issue-376树。新独立会话真实HTTPS trusted/wrong-host/untrusted含环境CA和verifyFalse不降级，旧缓存HTTPS/WSS仍保留。
- black26.5.1定向8文件检查通过；ruff0.14.10新增/改动无既有导入债务的7文件通过；auth原未用requests和GUI/Binder/main原告警按HEAD对照，不混无关清理。全量CI、CI6.9.2、真实账号/打包视觉未验；当时动态runtime无改，账号phase不能关闭#376。账号phase经Oracle实施1/3 PASS及lead明确授权，已原子提交`42ffeb8659e567e781a12f9c2053bb876e99d2d7`。

**动态phase实施与证据**：

- lead按已审设计另CAS八路径放行。实际无需修改`window_operation.py`，直接使用三个固定实例；无registry/dispatcher/globalpool，账号runner与旧40行为保持。新增纯`DynamicRequest`冻结身份/URL/ID/正文/cursor，五类原同步动态方法与后台共用同fetch，不改`get_dynamic_unread_status`。
- 首屏装配后Qt首事件发读，加载态先显示；列表单槽，失败不推进cursor不清旧列表，成功去重/恢复选择/翻页滚动。评论读单槽只合并一个最新ID，feed/selection/identity/visible代际匹配才呈现。成功首屏才标读；写槽包含post/comment/read，markread反复触发只dirty一个，终态不busy-loop，不自动重发用户写。
- 隐藏只invalidate接收，三个timer继续回收实际终态；重开不能绕过在途POST。草稿按动态ID保持，成功清理只作用于同一目标/输入。编辑器直接删除后只在GUI用`shiboken6.isValid`判断，不引入额外callback sentinel；worker始终无Qt引用。
- 首有效红：真实`DynamicsDialog`构造→真实NC.list→Session.send门控首GET，Qt50ms心跳/刷新探针预期`(True,True,True,1)`，实际`(False,False,True,2)`，`1 failed in8.15s`，job`pwsh-b8ae441203d64094`已收集1。相同业务测试最小fix后`1 passed in6.32s`，不改判据。
- 六个动态场景+原账号40组合`46 passed,4 warnings in26.29s`，job`pwsh-bfd12e7b50614aee`已收集0；4条均既有websockets弃用。最后GUI编辑器删除有效性保护补一必要场景，动态7例定向`7 passed in5.83s`。不把这两次相加成单次47通过。
- 七场景覆盖慢构造单请求、A/B评论迟到/失败分页cursor保持再成功去重、comment按钮+Return单POST/失败草稿/markread双触发只一次/隐藏重开实际busy、首屏失败不标读及手动恢复、发布编辑器失败稿/手动retry、身份变化丢评论/删除、在途编辑器实际delete后无Qt callback错误。真实transport与UI控件观测，不用内部flag当验收。
- 已精准glob/grep确认本独立基线无旧动态测试文件，不删除其他root可能有的用例；账号原17保留。动态4py black26.5.1/ruff0.14.10定向通过、diffcheck0；scope允许runner但0diff，main_ui/auth/Binder/main/default均无本阶段diff。全#376的CI6.9.2与完整离线门禁由verifier下一轮统一一次，不用Qt6.11局部46/7冒充全量绿。

**C3-2 attempt1 必修与 attempt2 证据**：

- Oracle implementation attempt1/3 不通过提交，仅确认一项真实分页竞态：请求开始选A，等待期间用户选B，旧成功回调仍按请求开始snapshot把选择抢回A。原7例只测分页前后A，不能证明这一新交互。
- 依lead最窄授权增强原分页门控例（不新增机械矩阵）：page GET未完成时真实切B，再释放响应；候选上实际`assert 'A' == 'B'`，`1 failed in3.04s`。只在`_list_completed`成功且原identity/feed守卫通过后，清单变更前读取完成时current ID与scroll，增加3行，不改runner/协议/账号/外部未读。
- 修后仅动态文件定向`7 passed in4.49s`：同例仍核cursor推进、IDs A/B/C一次、分页失败保旧cursor、评论最新与HTTP非GUI。没有重跑46/40，也不把第一次gate写成PASS。
- 边界补充：基线主窗口open尾刷新以及mark-read成功的外部on_read_callback都可能同步查询未读，属于已排#371；本单只保证自己拥有的HTTP离开GUI，不声称整条父回调链无同步HTTP。firstshot在实际main同栈show后执行；构造从不show或delete-before-firstshot没有独立实测，不把当前delete-after-request证据冒充全生命周期覆盖。

**风险与回滚**：daemon只取消结果接收，不能强停已在途HTTP或保证退出finally；Session timeout非墙钟，server已成功但客户端未收到的写入有结果未知风险，必须明示不自动重试。凭据保存/WSstart是本地有效apply，不保证底层磁盘/DPAPI完全无耗时，禁止在其路径增加网络或wait。实现可按账号/动态两个相关原子单元推进，但最终单个#376 PR须覆盖全规格；出错回退窗口runner接入和纯请求/apply拆分，无配置/凭据格式/服务器迁移。未合入#402/#371未来冲突仅按钮装配、会话创建和identity同点对齐，不预先merge/rebase/cherry-pick；完整spec经设计gate后才允许runtime，最终实现另经Oracle才commit，当前不push/GitHub写。

# PR #439 决策记录

# AI 决策记录

## 2026-11-17 #439 通话历史与重置准入的测试同步

**待定问题**：f5d8全量原E2E在历史可见后立即reset，实际409 USER_INTERACTION_BUSY（15passed/1failed）。历史写入先于context关闭与Manager所有权释放，不能把history或call.ended当可重置前置。

**背景约束**：lead task16/Oracle设计1/3仅准测试宿主、原E2E与本文，不改生产guard/预算/回收。原fullgate失败保留；旧纯ee真实SQL保存后门实验8.828秒证明history可见不等idle，但不复原本次exactowner；CallStage及support对ee不同，不做sameblob全免责。生产对31ff→f5d8零差异。

**调研参考**：现Manager._own_termination返回包含真实operation与release的原owned task，完成结果可只读快照；reset实际先查用户交互再fence。沿既有/test/call_state测试端点，不新生产接口。

**候选方案**：1 原终止task donecallback仅存completed/resources/failed布尔，GET瞬读原repo身份/Managerbusy/fence/lease，原case有界等ready再唯一POST；2 bounded POSTretry BUSY直到200，会改变原恰一次语义并可能掩guard，否决。**选择**1；缺快照/异常/取消/身份不符均notready，wrapper在任何call绑定前安装、返回原task，不持旧Stage或长期task、不再次terminate/notdoneexception。

**实施**：只测试宿主扩现call_state reset_readiness；GET用原账本内部取用户身份，不回传secret，Managerclosed/fence缺失或resetting/owned未完/lease存在均拒ready。原E2E history后只GET观察真实idle，再唯一reset；原SQL删除、重登和隐私断言不改。受控验证只在本树原save成功后暂停，证明history可见readyfalse且reset0，放门自然释放后readytrue、唯一200/SQL清空/重登。所有控制finally先放门、有界收进程，独立父60秒含启动，一次失败不重试，不全16/1200/Linux。

**验证方式**：首轮新观测接缝失败job pwsh-e0abe3a1c34e4b51：旧call_state计算ready后仍读不存在stage._inputs，ASGI500/clientJSONDecodeError，reset0/serverexit0/父16.5秒；不是产品red/green，原材料保留。lead准精确query reset_readiness_only=True早返，旧默认state不顺手修；原新E2E/controller显式true。仅route函数预检pwsh-ccbf5260cfc74a9e exit0（无server）验证绕旧段/非法notready。run2真实原case+原save成功后门job pwsh-e8560c64e6b04551 exit0：父11.438秒<60、启动5.407、场景及清理7.657/serverexit0/killedfalse；history200且savedtrue/releasedfalse时readyfalse/用户busy与leaseownedtrue/reset0，放门自然释放到completed/resourcestrue、用户busyfalse/fence0/leasefalse，再唯一reset200；原SQL清空/重登/privacy断言全通过。仅底层外部模型保既有离线端口，不重复旧ee或全16/1200/Linux；精确命令/原回执/三hash保留外部报告，静态后冻结待独立实现gate，不提交推送。

**风险与回滚**：只读观测必须不改变生命周期，task完成资源失败不能missing当safe；新业务并发不由测试端点加锁保护，当前隔离case没有其他账号工作。有限GET等待不是产品SLA，不放松resetguard或重试写请求。回退本test-only单元不改产品；新全量/远端结果必须归新SHA。

## 2026-11-17 #439 preclaim 超时后的测试无界等待

**待定问题**：原账本阻塞测试只有 20ms 的通话建立预算；真实仓库预查询先耗尽预算时，create 不进入，started 永不置位。测试忽略 started.wait(1) 返回 False 后仍 await 无限 heartbeat，无法走到原 TimeoutError 断言。

**背景约束**：lead task14 与 Oracle 设计 gate attempt1/3 只准本测试文件和本文，不改生产 Manager/CallRecords/预算/全局 clock/执行器，不跳过测试。固定父提交31ff341f；旧原函数外部唯一受控红已实跑：实例原 find 返回 None 后约63ms，真实 Manager817 TimeoutError、create未进入/startedFalse、原测试609 awaitpulse与heartbeat594栈四判全真；父6.75秒、取栈后才canceljoin回收，原源码前后三hash同。只证条件性测试漏洞可达，不认原Linux30分钟取消 exact cause。2秒 faulthandler 已arm但实际未打印线程栈，async任务栈与原异常trace已取得，不补重复红。

**调研参考**：复用生产构造已有 monotonic 接缝与本测试文件313–314既有单实例覆盖先例；本文件 manager(clock=) 仅wall_clock，不能误作单调时钟。Python asyncio.wait不自动取消被观察任务，适合把测试看门狗与产品取消分开。

**候选方案**：1 分清 late/early：late仅本Manager单调时钟固定100，真实create已进入且仍阻塞时heartbeat有限3ticks，然后推进100.03并release；early真实单调时钟+原读后60ms控制延迟，要求真实TimeoutError/create0且不等待create事件。2 只assert started返回值+有限pulse，仍有20ms前置调度竞争，负载下可能未测晚补偿就失败。3 抬时限/删heartbeat/skip，弱化原off-loop与晚提交保证。**选择**1；不改业务时限，局部时钟只选择原deadline分支，不伪造仓库写入或结果。

**实施**：late原20ms保持；明确核started=True，在release未开且start未done时运行有限3tick，推进实例clock后释放，要求原super真实创建PREPARING、原abort更新FAILED/SETUP_TIMEOUT且lease释放。early用原repo读取None后Event.wait(.06)，真实clock超时、create_calls空、lease释放，无无限pulse。所有新等待用asyncio.wait失败看门狗，finally先release，再cancel并有界等待自有tasks、close Manager也有界；如未收完明确失败，不宣称已清理，外部父20秒硬限兜底而不无界finally。原repo是InMemory，不称真实SQL集成。

**验证方式**：不重跑旧63ms红、不全1200/不新Linux矩阵。唯一短集合job pwsh-0e36c11b50e34615：两个新/改节点及邻近direct ledger failure、shutdown owned、deadline捕获，共5passed/2warnings/.16s；父6.75秒<20、killed=false、已收子进程。测试实际导入本issue410源；原20ms配置保留，Manager/_call_records字节hash与受控红前相同。单测试文件Ruff/Black/diff-check通过，冻结外部报告保留exact5nodes/命令/两文件hash，AI仅后补此回执不重跑。仅两个文件待实现gate，不提前commit/push。

**风险与回滚**：测试局部clock与真实IO分离需明确，early保真实读延迟使原条件仍被覆盖；所有失败路径门先释放，未完成任务不能被无界gather掩盖。回退本test-only单元不改变任何产品逻辑。远端原失败记录保留，后续新SHA CI另验，不能将本地小集合绿当原运行根因已确认。

## 2026-11-17 #439 CI 开场装配就绪的测试同步修复

**待定问题**：远端run43934219460在aa42唯一失败为lookup-failure测试的create_stage开场response.create等待1秒，尚未进入lookup业务断言。不能用本地平台异常豁免，也不能默认flaky或rerun碰绿。

**背景约束**：纯ee一次真实SQLACTIVEcommit后返回Event门实验1.273557s，内存/SQL均ACTIVE仍未发opening，旧helper1秒Timeout，放门后response恰1、answer任务完成、finally资源释放任务0；只证明readiness不足，不是远端exact cause回放。helper/fake同baseline blob，生产初始化scope确有改动，samehelper不排回归。lead task8rev17与Oracle设计permit只准helper/new1参数化test/本记录，不改生产state/CAS/预算/owner、不抬超时/skip/noamend。

**调研参考**：项目真实_apply_answer在_realize_plan try前，ACTIVE内存先于await真实SQL提交返回，之后才provider.push opening。_drain_facts只等fact-tail，不能代表answer。Oracle与独立只读复核确认已有_realize_task在ACTIVE时指向接听realization并包含opening发送。

**候选方案**：1 helper具名wait_opening_ready在ACTIVE后shieldjoin当前answer realization再检查实际response.create/非terminal；2 fake socket新增发送Event与answer错误竞速；3 _drain_facts或ACTIVE输出后继续1秒poll。**选择**1，最小集中既有test seam，不加productionAPI。**未选原因**2增加fake契约和竞速面；3不覆盖完整answer且仍有假SLA。

**实施**：create_stage从start到opening ACK准备置于BaseException保护，失败自terminate，原CAS/push前段异常不被cleanup替换；cleanup另失败用日志保留，不能吞成正常。wait_opening_ready缺task明确断言、取消原样、终止态明确失败、成功必须实际socket.sent含response.create。只承诺接听前段原异常传播，Agent.realize后段内部SYSTEM_FAILURE不泛化成全部throws。

**验证方式**：新受控参数化test在target真实SQLcommit后门控迟到成功/原OSError失败；旧helper有效red job pwsh-a629f8435ef24e49为2failed/5.27s，均creating提前TimeoutError触业务断言；fix后job pwsh-551dce2b5e59440c为2passed/4.02s。原test_call_omni整文件（含远端失败节点及正常场景）job pwsh-d400b685304e40d8为24passed/12.65s，不重复core/U1/npm或远端rerun。最终静态/冻结归档另列，所有控制门finally放行，资源/SQL/实际response断言保留；1.1秒仅越过旧helper的错误等待，不是新增产品SLA。

**风险与回滚**：测试helper依赖既有_realize_task seam，集中具名方法可局部回退；原先helper失败在callertry前会泄漏Stage，故创建失败自己回收。回退本测试同步提交不改变任何生产行为；远端原失败记录保留，待后续新commit新CI，不拿本地绿替远端结果。

## 2026-11-17 #410 U3 有限安全字段的建立诊断

**待定问题**：core保留call/phase/type/remaining及原auth异常cause，尚无结构化outcome/安全供应商code/HTTPstatus，不能把core测试说成这些字段已经观测。

**背景约束**：core/U1/U2已三独立commit f3e2cb8d/8ab238c4/f5846ff6，未push。lead task8rev12只授权provideromni、既有deadline门控测试、design/本记录；不改预算/owner/Manager/config/diag/UI，不做全仓日志脱敏。

**调研参考**：Context7核websockets16.0 InvalidStatus为握手拒绝；本机16.1.1只读签名核InvalidStatus(response)、Response.status_code。旧Aliyun诊断token已有有限正则[A-Za-z0-9_.:-]{1,96}可作同仓一致规则，不导入其私有功能或新建通用错误框架。

**候选方案**：1 当前phase日志增加固定outcome和安全code/status；2 记录str(error)/整供应商payload；3 新错误/可观测框架跨Stage。**选择**1，outcome仅failed/timeout/cancelled；provider code只字符串完全匹配长度<=96，否则None；HTTPstatus只实际InvalidStatus response对象字典中的type(int)100..599，排bool；不dump message/body/header/URL。**未选原因**：2泄露凭据/原文；3范围与审查成本超需要。

**验证方式**：扩现t4auth门控caplog有效red job pwsh-bdb6d89a8a344179：1failed/5deselected1.06s，精确缺outcome；最小修复后auth2passed1.06s（原cause/清理owner仍成立）。后补401/非法status、自由文本换行/97长度/dict code、timeout与cancel原异常对象保留且日志remaining过期不覆盖，最终14passed/.34s；脚本/配置/core旧回归不重复。测试只筛新增_log_setup_failure记录，不伪称StageManager既有traceback全部脱敏。最终格式和hash归档单列。

**风险与回滚**：诊断提取不得调用自由文本或有副作用属性，vars读取已知异常/响应字典；取消无论remaining耗尽仍cancelled并原样raise。回退本单元观测字段不改变通话/取消/释放行为。只保留安全code而不保存error.message；旧异常原cause语义保持，恶意payload在历史异常链的全量脱敏不在本单元。

## 2026-11-17 #410 U2 Fun-ASR 脚本自有限时

**待定问题**：生产移除内层管理员限时后，诊断直连与--adapter仍需自己的连接/初始化等待，不能复用Manager或被旧非法配置阻断。

**背景约束**：core与U1已分别commit f3e2cb8d、8ab238c4，未push。lead task8rev10仅授权diagnose_fun_asr.py、公开main(args)测试、README/design/本记录；不改共享config/provider/realtime_cancel_timing，不混U3。

**调研参考**：沿已通过Context7核对的websockets显式open_timeout与asyncio.wait_for超时取消/清理语义，复用真实Fun-ASR独立factory/session；脚本CLI由argparse正有限转换，main再排bool等非法值。

**候选方案**：1 脚本参数内存覆盖旧键，两路径都用；2 从Manager借总deadline；3 改全部shared adapter/诊断框架。**选择**1，两个参数缺省10，直连ready等待覆盖run-task发送及task-started，--adapter按独立session限时；主入口不写配置。**未选原因**：2混生产与诊断所有权；3超工单最小范围且已有独立adapter端口足够。

**验证方式**：先main(adapter)有效red job pwsh-7ff56717e64a4184：旧非法connect键在factory解析失败，1failed/.65s；实现脚本内存覆盖并把start置于try/finally后单例1passed/.08s。进一步公开main两路径ready/connect超时、取消保留并关socket、CLI和main非法限时，全部只替外部WS、临时公开配置与合成WAV。使用asyncio.wait观察自身短限时是否完成，不能把测试watchdog取消冒作脚本超时。最终job pwsh-ec7d07233f1d4df7：24passed/.39s及脚本/测试Ruff、Black、diff-check通过；定向Fun-ASR原回归包含其中，不与22项前轮相加。未真实等待30秒/供应商计费请求。

**风险与回滚**：start失败后consumer尚未创建，finally须可None且仍关session；close后consumer取消join不遗漏。连接等待上限交显式库参数，非成功保证，取消/拒绝不重试。回退脚本/文档/测试即可，不触用户配置、密钥或生产预算链。

## 2026-11-17 #410 U1 总预算配置与控制台

**待定问题**：核心预算链已提交 `f3e2cb8d27dd5b236138aa8bd805060b050a4d0e`，控制台仍只显示旧内层值，且共享解析会用旧非法键阻止生产配置校验。需要一次可回滚的配置/UI单元，保留独立诊断严格限时。

**背景约束**：lead放行task8 U1 rev8，仅现有配置编辑/校验、Qwen生产解析、控制台及其真实构建产物、公开模板/README和必要测试。不改Manager、Stage owner、用户config/secret；不混Fun-ASR脚本或结构化日志单元，gate前不commit/push。

**调研参考**：[React官方input](https://react.dev/reference/react-dom/components/input) 经Context7核对受控number输入保留原始string、onChange同步更新，避免输入中途转NaN/JSON null；UI skill精准表单查询只采用number类型与明确错误提示，不换样式系统。既有#435面板局部select/草稿/串行apply作为稳定行为保留。

**候选方案**
1. **有效值视图+单叶子patch**：视图显示stage_manager.call_setup_timeout缺省10，提交只合这一键；validator按正有限数/bool排除；Qwen生产显式忽略legacy限时，独立adapter from_mapping默认严格。
2. **把整个stage_manager暴露并覆盖保存**：便于编辑但可能覆盖termination/offline兄弟设置，违背最小范围。
3. **独立新解析模块同时修改Manager**：可共享默认值，但新增跨层依赖/改既过gate核心，无必要。

**选择**：候选1。只抽model_editor本次leaf写入小helper避免既有apply复杂度10→11，不建跨层模块。UI保存raw string，提交验证非空/正有限后转number；旧connect/session编辑字段撤下，原值不启动改写/删除。管理apply原校验→写→按需重启链路复用。

**未选原因**：候选2会扩大写入面并破坏#435；候选3扩大邻域改动与回归成本。模板显式10但缺省行为不变；独立诊断仍严格旧参数，避免本单元把它变无界。

**验证方式**：首个view/apply公开接缝red job `pwsh-d8c30569f1ca4985` 为2 failed/7 deselected/.47s，均因有效预算字段缺失；最终job `pwsh-54673a2cace24a72` 为77 passed/3.47s，含默认/30/leaf兄弟保持、非法总时限apply不写不重启、5类旧Qwen非法键不阻完整validator而独立adapter拒绝；4生产Ruff/Black通过。首次回归旧session_timeout=-1管理校验预期失败，按维护者明确兼容要求更换为生产/诊断对照；独立adapter原严格测试保留。独占窗口内本tree锁文件SHA256 12109e9efe5a0c039c482db7cdb91d0e20632d0436cf019901a2318fdbacb7e4未变，显式Node22.23.5 npmci69packages7s与tsc/vite构建成功（job `pwsh-2673bb6d91ba4416`）；新构建产物真实Chromium `python -m scripts.check_admin_model_panels` exit0（job `pwsh-38525d4753d6490f`），空输入不发请求/总预算30.5保存刷新/局部放弃/其他面板草稿保留。未改用户配置、不把UI模拟API说成真实业务runtime重启。资源清单按新JS及HTML实际字节/哈希同步；初次资源校验通过与3项发布资源测试通过，但diff-check随后发现HTML混合CRLF，组合shell末status掩盖其非零，已明确排除该次diff绿声明。仅生成HTML规范为LF（无DOM/JS语义变化，423字节、SHA256 282cec880bde7c0767ba3e84257296d457031a48fd7e733bc5b6ee2d2dbbc185），重算清单后资源验证和逐项diff-check均通过，未重复浏览器。

**风险与回滚**：UI与有效默认漂移、整树覆盖、旧键解析模式误伤诊断。用单叶子与生产显式flag、公开Manager契约对照和局部草稿浏览器证据控制；回退本单元代码/资源/模板，不删除旧键、不迁移用户数据。部署资源清单须同步实际构建文件路径/size/hash，不能只改TSX。

## 2026-11-17 #410 单一建立 deadline 的最小传递候选

**待定问题**：Manager 已有唯一通话建立截止时间，但 Qwen 的 connect/session 独立限时与 websockets 缺省 10 秒仍可能提前终止管理员给定的较长总窗口。需要在不重写生命周期所有权、不混入 #411 的前提下传递剩余时间。

**背景约束**：需求已由 [维护者评论](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/410#issuecomment-6910783940) 锁定：仅 `stage_manager.call_setup_timeout` 可配置；登记时固定唯一 deadline，连接/ready/ringing 共用；明确错误立即失败；Fun-ASR 诊断脚本独立限时。基线 `ee718b21536e410ce5e4073b068f03b9bfcd68dc`，Python 3.10.21、websockets 16.1.1。D2通过后lead已放行provider预算核心与显式caller；不改Manager/用户配置/密钥，不提交/推送/GitHub。

**调研参考**：通过 Context7 核对 [websockets asyncio client](https://websockets.readthedocs.io/en/stable/reference/asyncio/client.html) 与 [16.0 官方文档](https://github.com/python-websockets/websockets/blob/16.0/docs/reference/asyncio/client.md)：单次 await、显式 `open_timeout`、None 可禁限时、iterator 才自动重连；[Python3.10 asyncio.wait_for](https://docs.python.org/3.10/library/asyncio-task.html#asyncio.wait_for) 超时取消并等待清理，总返回可超过 timeout；[asyncio.wait](https://docs.python.org/3.10/library/asyncio-task.html#asyncio.wait) 不自动取消 pending。借鉴既有 absolute deadline+阶段 remaining，不引入3.11才有的timeout上下文。

**候选方案**
1. **余额回调沿现有open接缝传递**：CallStage 由现有原 deadline 与 monotonic 计算 `remaining_setup_time()`，Agent/Factory 转交；provider 每阶段重算，仅初始化期间使用。不加配置/测试专属clock。
2. **原deadline + clock双参数**：三层均传 deadline 与 clock，类型更显式，但接缝需共同理解时钟域，参数更多且容易与已有注入不同步。
3. **删除全部内层限时，仅外层取消**：改动少，但不能表达明确的阶段余额，standalone 调用易变无界，诊断所有权容易遗漏。

**选择**：D2设计gate attempt1/3已通过，lead已放行候选1的provider核心实施，不commit/push；UI/旧键/诊断为后续单元。窄核补充明确选择同步 `on_session_created` 早交Stage owner，不采用失败异常携活handle候选。完整方案及单owner表见 [设计稿](<docs/specs/call-setup-deadline-plan.md>)。

**选择理由**：复用唯一权威 clock，三个接缝只学习一个小 Interface；provider 不查 Stage、不存当前会话状态，外层 `_await_setup / _dispose_late_setup` 仍拥有任务/迟到资源。显式 `open_timeout=remaining` 不受库缺省10秒影响；ready重新取余额而非续期。

**未选原因**
- 候选2：重复时钟约定与参数传递，不比现有 Stage 的权威余额提供更多实际能力。
- 候选3：虽能依赖外层约束，但独立 Factory/诊断的无界风险和阶段语义不够清楚。

**其他具体取舍**：旧connect/session JSON键暂兼容但生产不消费、不让旧非法值阻断，不启动时改写用户配置；UI仅新总预算叶子并保留#435面板局部草稿；Fun-ASR脚本分别持有connect/ready参数，不借用生产Manager。#411既有安全释放结果由另一lane负责，设计中只衔接不修改。

**验证方式**：lead已确认 Manager公开接入→真实Agent/providerfactory 接缝，仅connector/socket、空存储端口与时间受控。已运行 [首个参数化10/30行为测试](<server/tests/integration/stage/test_call_setup_deadline.py>)，job `pwsh-7b6420a064f44074` 已收集：1 failed, 1 passed, 1 warning in0.61s。10秒真实终态/账本SETUP_TIMEOUT对照通过；30秒在10.25虚拟秒因旧ready限时已经进入终止，精确业务断言失败，不是新参数TypeError。首跑清理夹具曾误调用Agent.stop，已修正，仅干净复跑计证据。Ruff/Black通过；pydub缺ffmpeg为环境warning，本测试不做音频。尚未覆盖库真实connect默认、4秒鉴权、控制台/诊断；后续各取最少必要证据。生产零改动，设计gate前不进入绿灯，完整CI由ci-verifier统一调度。

**风险与回滚**：接缝参数遗漏、共享配置迁移遗漏独立诊断、取消清理覆盖原错误是主要风险。回退本单元代码与测试，不删配置/密钥/数据库；保持Manager既有键与默认兼容、旧键不删除。不得为准时返回先释放仍被旧任务使用的资源，也不为凑满预算重试明确失败。

**D2单owner落实**：remaining先检查再创建；Factory首await前同步on_session_created交Stage PREPARING slot，callback拒绝必须在赋slot前完成校验，赋值后不抛；重复发布同handle为幂等，异handle拒绝。交后Factory成功/失败/cancel均不close；Stage原provider late-cleanup lambda移除但cancel/join保持，return必须is已持handle。Stage唯一close task成功清slot、失败保留slot/失败task并_resource_error；多次清理不再close，资源不安全时Manager仍拒绝释放。取消日志读remaining独立小try捕TimeoutError/CancelledError，不改原异常。普通auth即时传播Stage锁SYSTEM_FAILURE，不因慢close跨deadline改SETUP_TIMEOUT。未加窄失败异常handle、通用owner/clock或#411字段。

**实施阶段证据**：核心首红转2 passed/.22s；既有四文件73 passed/5.88s（会话/prompt/handoff/公开Manager）；六场景门控6 passed/.73s，含auth+慢关/关失败、connect15+blocked update send、取消抑制late关闭一次。测试初稿cause层数/close计数时机错误已收敛，不把夹具失败算产品红灯。4生产文件Ruff/Black、diff-check通过；未改的既有test_call_omni全文件仍有基线格式差异，新增helper按Black，不夹带格式清理。最终冻结检查与原输出归档单独提供，未运行真实供应商/全CI。UI、旧键验证兼容、诊断在下单元；当前不commit/push。

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

## 2026-11-17 #441 reset 测试只读就绪同步（task17顺序记录）

**待定问题**：历史写入可见时，通话终止任务可能仍持有交互占用；怎样只修测试等待条件，保留真实重置准入和唯一POST？

**背景约束与来源**：目标父为 `b8189f17cef14c22131cfdd5a0bff2b4ddc6e905`，仅host/E2E/本记录三路径，desktop-repair只改两代码、startup仅顺序记录AI，不预填未产生提交SHA。来源task16实现1/3 PASS后提交 `b307df6897800776cdb354ea36069c8a27000b8b`，source host b36035ab/E2E 2f493641/controller e27c620b已由实施者核验；观察接口相同，但目标保旧 `open(self,call_id,instructions)` Factory，明确排除来源新预算/owner参数，不覆盖整文件或合生产改动。

**候选方案与选择**：①GET只读观察原owned终止任务完成及真实Manager busy、fence owned/resetting、lease，ready后才发原唯一POST；完成回调仅存安全布尔，不强持Stage/Task，显式 `reset_readiness_only=true` 提前返回，未知/失败/缺完成快照均notready。②重复POST等200会把删除当探针并掩盖冲突，不选。③只认history、固定sleep或降低guard断言混淆持久化与资源关闭，不选。选择①；GET不替代POST的原子准入，后来新占用导致非200须原样失败，不重试碰绿。

**验证方式与目标实际结果**：来源首跑旧state `_inputs` 500为fixture错误，来源成功11.438秒不作目标成绩或原canonical 409精确根因。目标唯一运行job `pwsh-b44de775aed94b95` collect exit0：父12.375秒<60/killed=false，client8.219秒含startup6.110秒，server_exit=0，ROOT确为issue-412及既有V2。真实SQL CallHistory.save已成功但返回门未放时history200/readiness GET200，ready=false/reset0/busy及lease=true；缺完成快照的failed=true是保守默认，不称实际终止异常。放门后原任务自然完成，completed/resources=true、failed=false、busy=false、fenceowned0/resetting=false、lease=false/ready=true；唯一reset得200，四持久计数call_sessions/conversations/maintenance_batches/memories均0、profile空，原重登/凭据隐私断言通过。

两代码逐diff+103/-5，旧默认state分支不顺手修；host SHA256 `47c7c3f15d4131492f94237ecfd00a26eebe201d35e28229669a42c7d6a05d68`、E2E SHA256 `2f4936417ca64d07f364d7a9e3aa32af0bbe94c4b7335e1cb1a17b1460ce2dd0`，除Factory类外host AST同来源/E2E LF字节同来源。Ruff/Black/diff-check通过，生产/config/scripts/CI差异为空；pydub缺ffmpeg PATH提示保留。依据已读目标25行短报告、53行raw与冻结静态记录转录，startup未重跑或操作索引。

**风险与回滚**：观察回调不改原owned任务返回/失败语义；父看门、失败先放门及有限wait/reap只覆盖本受控宿主，不是通用无泄漏审计。唯一POST、实际guard、SQL删除与隐私保证不削弱。回滚该自然测试单元及记录不改产品重置政策、不删用户数据；三路径共同冻结后统一gate/单原子提交，不单AI提交，不push/自动all/ready/closegoal。局部成功不等远端绿、真资源恢复或完整A4/A6/V5，旧失败历史继续保留。

## 2026-11-17 #441 preclaim 测试同步与有限清理（task15顺序记录）

**待定问题**：旧建立前置请求测试把“已进入create”当成超时前必达条件；若请求在find返回后已耗尽预算，create不会发生，旧heartbeat可能无限等待。怎样保留真实early/late边界而不修改生产预算？

**背景约束与来源**：lead仅准handoff测试与本记录两个路径，desktop-repair只改测试，startup-spec仅顺序写AI；当前父为Secrets提交 `256af59fd6520417a02aedbaf322babe1f51cbb4`，本单元尚未提交，不预填新SHA。复用已审 `f5d8deab6012002839247686471c101b18160110` 的单文件测试同步契约，原目标test blob87f98ca4、StageManager c8965145、CallRecords d48c5140与来源父31ff相同，两个support接口也相同；不merge/cherry-pick生产改动。

**候选方案**：①分开early/late并有界清理：late仅本Manager实例时钟固定100，在真实create进入且release未开时检查3次heartbeat，再推进100.03并放门；early保真实时钟，原find真None后Event延迟.06，要求Timeout/create0/lease空。两者均保原.02预算，finally先release/cancel再有限等待及close。②延长等待或放大预算：改变被测边界，仍可能混淆未进入create和已进入create。③删heartbeat或补假FAILED：失去事件循环可用性或真实补偿证据。选择①，因为按真实阶段验证且不改变产品；不选②③的掩盖与伪造风险。

**验证方式与实际证据**：来源受控find(None)后延迟.063秒，真实Manager先Timeout、create/started未进入，旧heartbeat无界等待；相关原始blob相同支持复用该条件性漏洞负证，**不是本树重新悬挂，也不是原Linux30分钟取消的exact cause复原**。desktop-repair本树唯一focused运行job `pwsh-4466006d83c24eae`：**5passed,2warnings in0.16s**，父7.812秒<20、killed=false/reaped=true，SOURCES硬断测试/StageManager均来自issue-412及既有V2。覆盖late、early、direct_ledger_failure、shutdown_waits_blocking_direct_repo、setup_deadline_captured；真实内存仓库super建立PREPARING后由Manager补偿FAILED/SETUP_TIMEOUT，**不称SQL**。

测试仅逐diff变更cleanuphelper/late/early，+90/-13，未整文件覆盖或改变其他case；最终test SHA256 `6fe6be23634dfdbaecf19566017fcf8621f40529e3db438b721ee48794ba420c`、blob e5de9e24与来源相等。定向Ruff/Black/diff-check通过；2个support预加载重写警告及pydub缺ffmpeg路径提示如实保留，本例不编解码。以上来自已读外部task15短冻结报告，startup未重跑5节点、17/95或全门禁；生产两个SHA未变。

**风险与回滚**：局部时钟不能扩展为全局时钟或产品超时放宽，early真实时钟与有限finally保证仍须保留；清理后pending应明确失败，不能软通过。仅证明已受控条件的测试同步漏洞修复，不倒写旧远端失败/取消或宣完整验收。test与本记录冻结后统一实施gate、同一自然新提交，单独回滚不改变建立预算/准入/仓库生产逻辑，不删除数据；最终合成HEAD原七作业与Draft更新由lead另行调度，当前无push/自动all/ready/closegoal。

## 2026-11-17 #441 opening 测试就绪契约复用（task13顺序补记）

**待定问题**：本分支未包含独立#410的测试helper修复，真实远端lookup失败场景在opening创建时固定1秒等待超时；怎样补对本树测试契约而不混入通话预算生产功能？

**背景约束**：task13只允许测试helper和新增readiness测试两个文件，不并写AI；该单元经Oracle implementation1/3与lead授权提交 `3805e0cb18e60454adf2579fe7b48c1ccc57e4c7`（parent5ee）。本条由startup-spec在task12提交3924并明确释放AI后，按lead要求依据外部47行task13报告顺序记录，不重跑其测试。

**调研参考**：复用已审 `31ff341f81d6a9b38828e2cdc3cde4657112e1e7` 的两文件测试契约，未merge/cherry-pick其生产改动。旧helper与ee同blob7a9259…；当前factory/Agent/四元组签名不改。最终helper blob `51a23805a1e4e43f6d7cbd4939eab04992ce13d8`、新测试blob `69a31421b02e84ca9def450710078dc3b3aee1f8` 与来源对象相等。

**候选方案**
1. **具名opening就绪接缝及失败清理**：捕获当次真实_realize_task并shield等待，检查ACTIVE/非终止/socket确有response.create；创建失败真实terminate并保留原异常。
2. **抬固定1秒或删除发送检查**：只能掩盖调度差异，不能保证实际opening已发。
3. **跨分支合生产改动或假成功factory**：扩大工单范围，并绕掉本树真实接口验证。

**选择/理由**：候选1，在本树旧接口上复用已审深度最小的测试同步契约。受控SQL ACTIVE提交返回门同时验证等待与失败分支，不用sleep当就绪条件。

**未选原因**：候选2无可靠阶段证据；候选3越过test-only范围，无法独立归因与回滚。

**验证方式与实际证据**：task13在本树原helper上新增2场景，真实红为 `2 failed,1warning in3.48s`（job pwsh-3c4968f8bcc84295，两个TimeoutError）；修后同新2+旧call_omni24一次 `26passed,1warning in6.30s`（job pwsh-dadbc87f8f334e92），外壳10.047/11.875秒均在20/40秒上限内。成功opening恰1次；失败保原OSError同对象、socket关闭/tasks空；finally放门/清理。定向静态通过，旧helper原I001未扩大格式化；pydub路径告警保留，不冒媒体依赖齐备。本条只转录已落原证据，不是新增运行PASS或原远端精确根因重建。

**风险与回滚**：只证明测试同步/清理契约，不改变生产预算；回滚该自然提交不删除数据。不据26通过宣整个PR/远端已绿，后续Secrets/preclaim收齐后由verifier在最终HEAD统一门禁。

## 2026-11-17 #441 Secrets 夹具补齐真实校验器能力

**待定问题**：3A状态接口共用必需密钥策略后，旧测试shell没有validator，真实远端更新Secrets失败；应改生产还是补齐测试夹具？

**背景约束**：真实AdminShell dataclass声明validator，initialize实际构造RuntimeConfigValidator并共享给Supervisor；旧测试与ee同blob但partial SimpleNamespace只提供SecretStore/read_raw/is_running。task7rev10仅原http_secret_security测试与本AI两路径；等task12提交 `3924ca6df0ef2117c5f2258d9f03e8ee66f93774` 并明确释放后才实施，不并写AI。不改production/超时/通话helper/UI/CI，不扩鉴权或实际重启平台。

**调研参考**：已读AdminShell、SecretStore、ConfigStore和RuntimeConfigValidator.required_secret_keys的现有契约；无需新框架或外部研究。更新Secrets返回secrets_status，因此需要同一真实校验规则：JWT始终required，顶层citywalk=false时AMAP非required。

**候选方案**
1. **修旧夹具为真实Store/Validator**：真实临时ConfigStore与SecretStore，validator引用同一SecretStore，citywalk false/true两代表，保原changed_keys/restart_required并核条件状态。
2. **生产status直接调用策略staticmethod**：可减少shell实例依赖，但真实AdminShell本来已有validator，为兼容失真fake改生产无必要。
3. **getattr/hardcode或lambda假validator兜底**：容易复制策略并掩盖真实协议缺失，不能验证实际配置/密钥状态。

**选择/理由**：候选1。测试以monkeypatch先登记JWT_SECRET/AMAP_KEY/RUNTIME_SECRET_TEST三个合成环境值，SecretStore之后即使覆盖也能恢复原环境；AMAP测试值保留在store，false场景直接断言required=False而非缺key。Supervisor仅is_running提示端口，不能称真实owner重启；密钥均临时合成不输出/不归档值。

**未选原因**：候选2扩大生产范围且无真实owner缺陷；候选3会为测试绿灯降低真实状态保证。

**验证方式与实际证据**：原节点先在本树V2运行，job `pwsh-4b80f9e31d584e3d` 原 `1failed,1warning in3.25s`，准确update_secrets→secrets_status L254 `AttributeError: SimpleNamespace has no attribute validator`，不是导入/前置错误。补真实夹具及两代表后，原文件+已有citywalk免AMAP不免JWT/Secrets.required两邻近节点，job `pwsh-56dafb7d9f6f4438` 为 **13passed,1warning in1.83s**，Ruff/Black该测试全通过/无需格式变动。警告为既有zhconv/pkg_resources弃用，不称零告警。未重95/17/0.15敏感计时或全CI。

```text
python -B -X utf8 -m pytest tests/integration/system/test_http_secret_security.py tests/integration/system/test_admin_runtime.py::test_citywalk_disabled_does_not_require_amap_but_jwt_stays_required tests/integration/system/test_admin_runtime.py::test_secrets_required_status_matches_citywalk_condition -q --tb=short -p no:cacheprovider
```

**风险与回滚**：本单元只修测试依赖契约与环境隔离；原远端失败历史不抹，不据13通过称整个PR已验。回滚后续自然test-only提交即可，不改用户配置/SecretStore或生产行为。两路径冻结交独立gate，未获明确许可不commit/push/GH/ready/closegoal；多个自然修复及preclaim收齐后，最终固定HEAD只由verifier统一执行原七作业，不每个小commit重复全量。

## 2026-11-17 #441 embedding 超时测试的阶段契约

**待定问题**：原633远端单元测试在真实连接EOF0后断言connected=false；该事件实际仅在完整HTTP header到达后置位，混淆了TCP接受和响应停滞。测试/实现与ee基线同blob并不豁免失败，外部真实双分支只证合法早取消同症状可达，不是远端exact cause。

**背景约束**：lead task12及Oracle设计许可只改本测试文件与本记录，实施树issue-412/5ee；保同步embed_query真实wall-clock请求0.15秒、总2秒、清理1秒、单次尝试。严格响应stall必须仍有真实header和真实socket关闭证据，不生产改动、不抬等待、不加依赖或通用时钟框架，AI由本单元独占。

**调研参考**：[HTTPX0.28.1 trace扩展](https://github.com/encode/httpx/blob/0.28.1/docs/advanced/extensions.md)支持异步连接/发送/响应阶段观察；只用事件名，不记录info/headers/body/密钥。[Python3.10事件循环](https://docs.python.org/3.10/library/asyncio-eventloop.html#asyncio.loop.call_later)允许计时回调提前一个时钟分辨率，[wait_for](https://docs.python.org/3.10/library/asyncio-task.html#asyncio.wait_for)超时取消且等待实际清理。项目已有局部loop.time受控验证；这里只覆盖新建客户端loop实例，pytest/server loop和全局monotonic不变。

**候选方案与选择**：选择两个互补场景：原同步真实时钟入口按accepted/header/EOF/closed分类，且只认TimeoutError、attempts1；另在专用新线程/loop从请求前原点冻结time，真实header及receive_response_headers阶段后推进未到期点，再跨原0.15期限，验证原wait_for取消和真实EOF。单独放宽header断言会失去响应stall覆盖；只抬超时或去掉断言仍没有阶段保证，均不选。无需新公共helper或生产API。

**验证方式**：先在原测试注入send_headers.started事件门，job pwsh-90eda9dfe8424940有效red为1failed/7deselected/0.88秒，精确header事件false与EOF0。阶段分类两分支2passed/0.47秒。严格clock初版及0.149负对照都通过，后者暴露安全网不足，不能计为有效边界证据：本机loop分辨率0.015625秒，0.149与0.14距0.15均不足一个分辨率。按官方容忍取前点0.15-2*resolution（本机0.11875），原timer观察为0.15/2.0；不跨期负对照job pwsh-01acc6d3af094a8d为1failed/8deselected/1.70秒，精确stopped仍false。恢复跨点0.16，原异常发生时虚时必须0.16并在finally恢复真实time前记录；最终本文件job pwsh-143e9e8af51d4668为9passed/0.62秒，Ruff通过。此后仅按Black整理新增部分，不重测或夹旧响应字典格式清理；静态/冻结细节另列实施归档。未重17/95或全CI，旧633失败和新5ee集成失败仍保留。

**同attempt1收尾修正**：Oracle发现真实看门超时后finally无界gather会抵消watchdog，原匿名gate也不能由owner解除。新增唯一坏路径吞计时取消直到可释放网络门，外部父5秒取得gateentered后hang红（job pwsh-0b4e1f0b0d3b4e8e，tree-kill0/reapedtrue，含启动总11.57秒，非产品失败）。最窄改为只在worker仍未结束的异常看门路径线程安全放门/取消实际client POST task、先关自有server/writers，再真实有限等待worker；invoke的finally标记与Task已done共同证明同步调用及其asyncio.run已退出，不取消to_thread包装冒充join。正常产品Timeout分支不主动close，仍须自行EOF。修后job pwsh-12406541a72344e0：坏节点1passed/0.56秒，本文件10passed/1.09秒，父分别7.2113/6.250039秒均有界且reaped；仅此网络门回归可解除，不宣称可强杀任意恶意Python无限线程。随后只有新增格式静态/指纹更新，不再业务测试。

**风险与回滚**：局部loop时钟只服务该严格测试，原点不在header后重置；pytest/server真实watchdog不虚时，finally恢复实例方法、关闭async client/server/writer、收齐handler与线程。前界须远于平台clock_resolution，不能声称毫秒级精度。真实worker若在有限等待内仍未退出必须明确失败，不能宣清理成功；任意不可协作线程不在此测试保证。回退本测试单元不改变产品行为；若计时器或trace依赖版本改变，测试应明确失败，不用扩大产品预算或soft-pass掩盖。

本文件记录 #412 规格的推荐、否决理由与非作者裁定。完整规格已通过 D3 attempt 2/3，可作为分阶段实施依据；不表示人类此前逐项批准派生设计，也不是 A1–A6 或运行代码验收通过。具体提交/实施权限仍由 lead 逐阶段授予。

- 工单：[Issue #412](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/412)，2026-11-17 读取最新 body（`updated_at=2026-11-16T15:37:16Z`），comments 为空。
- 调查基线：`ee718b21536e410ce5e4073b068f03b9bfcd68dc`；分支 `feat/component-startup-switches`。
- 交付规格：[组件级启动开关](<docs/specs/component-startup-switches.md>)。依 [开发守则](<docs/开发守则.md#L5-L9>) 已完成非作者门禁；规格阶段没有运行代码/测试/现用配置/密钥改动或业务运行、依赖安装。lead 已单独授权本次两文档原子提交，不推送、不操作 GitHub 写入。
- 2026-11-17 D3 attempt 2/3 已确认 N1/M1-S 和 N2 闭合，G1–G6 无新增必修，许可完整规格用于分阶段实施。审查冻结输入：418 行 spec SHA-256 `9a60e13c4f23447f5bb093347476354f38e36222976f918c9805c66350cffae8`；260 行 AI_DECISIONS SHA-256 `39d63748ffafd4c911a10ac25738c7e6aef50b07f74c9d6a9a399b17a47770db`。本次只机械登记报告摘要，不改已审契约；下文“待 attempt 2”等保留为历史记录，由本裁定覆盖，不代表仍需用户逐项确认。A1–A6、运行代码、真实资源与控制台均尚未验证，下一 phase 仍等 lead 明确 scope。

## 2026-11-17 在现有装配接缝选择真实或禁用 Adapter

**待定问题**：怎样让 TTS、向量资源明确不启动，又不把 `None` 和异常兜底判断散布到 Stage/所有调用方？

**背景约束**：不改配置时全量行为不变；只逐项开关，不加 preset/新环境变量。现有 [AgentRuntime](<server/src/agent_runtime/agent_runtime.py#L123-L139>)、[SharedSkills](<server/src/agent/skills/facade.py>) 已有具名装配与清理 owner；向量依赖非空，SAY 的空 TTS 是失败。

**调研参考**：2026-11-17 经 Context7 `/websites/fastapi_tiangolo` 读取 [官方 Lifespan](https://fastapi.tiangolo.com/advanced/events/) 及 [生命周期测试](https://fastapi.tiangolo.com/advanced/testing-events/)。官方示例将共享模型在接请求前加载、结束后释放，并解释模块导入时加载会拖慢独立测试；测试须进入/退出生命周期。只借鉴受控资源所有权、非 import 时昂贵初始化和完整清理；本项目已经显式拥有业务 runtime，不照搬/迁移为 FastAPI lifespan。页面为滚动文档，查询日期不是版本锁，不能推导本项目已安装的具体版本。

**候选方案**
1. **装配选择 + 禁用 Adapter**：在现有 owner 构造前选择，无后端资源；以少量只读 `enabled` 能力事实影响必要业务路径。兼容原方法，集中保障启动/关闭/回滚。
2. **依赖置 None + 到处判断**：少建类型，但使所有 caller 和依赖门禁学习禁用/关闭语义，易漏分支。
3. **首次调用 lazy 初始化或捕获失败降级**：启动看似更轻，首次对话仍可能加载资源或联网，也难区分主动关闭和真实故障。

**选择**：推荐候选 1，缺省 true；disabled Adapter 非空，业务只在语音输出和记忆投影的窄接缝作能力判断。

**选择理由**：沿既有架构取得 Locality；真实与禁用两个 Adapter 让变化明确，可用构造陷阱验证“不拥有资源”，关闭和失败回滚仍由原 owner 承担。不需要重构全局服务注册框架。

**未选原因**
- 候选 2：当前 AgentMemory/AgentRuntime 明确要求非空向量，改为 None 会扩大 Interface，并容易漏掉 prepared SAY、用户重置和初始化失败回滚。
- 候选 3：不满足 A2/A3“无需资源且禁用时不使用”的可观察契约；把任意 provider/数据库故障当禁用会降低 enabled 下的安全网。

**验证方式**：缺省/true 对比保持原装配；false 时 TTS/Chroma/embedding 构造与 HTTP 如被触发即失败；关闭/部分初始化回滚无残留。完整生命周期及真实 HTTP/WS/SQL 证明由实现阶段负责，本文未执行。

**风险与回滚**：能力事实若被解释成全局静音/全部记忆关闭会扩大语义；规格分别限定 SAY、向量投影。通过操作者在隔离配置恢复 true 并重启回退，不改其现用配置。

## 2026-11-17 默认兼容的配置与 AMAP 条件校验

**待定问题**：新键放在哪里，禁用后哪些资源可以缺失，如何避免假称当前缺 AMAP 已非阻断？

**背景约束**：[validator](<server/src/infrastructure/config/validation.py#L41-L129>) 当前仍把 JWT_SECRET 与 AMAP_KEY 都列为 core 必需；[管理 Secrets](<server/src/web/admin/admin_interface.py#L244-L261>) 也有独立 required 标记。关闭 TTS 不关闭 singing、模型引用、SQL/媒体；不为本机写密钥。

**调研参考**：上述 FastAPI 官方生命周期只支持“有需要才创建资源”的技术原则，未规定本项目的配置键/密钥政策。键的 owner 和严格配置错误采用 [SkillsConfig](<server/src/infrastructure/config/skills.py>) 与 [WorldRuntime](<server/src/world/world_runtime.py#L286-L288>) 的本项目接缝；具体产品选择由本草案提出，不冒称外部标准或用户原话。

**候选方案**
1. **所有者节点逐项 bool**：`agent_runtime.skills.speaking.enabled`、`agent_runtime.vector_store.enabled`；缺省 true，非布尔拒绝。`citywalk.enabled=false` 才解除 AMAP 核心必需，其他条件保留。
2. **全局 lightweight/development 模式**：一个键隐含关闭多种能力，或新增环境变量覆盖。
3. **按凭据是否存在自动选模式**：缺资源自动忽略或用虚构 AMAP/key 占位绕过 validator。

**选择**：推荐候选 1；对明确禁用的专属资源条件跳过校验/初始化；AMAP 条件及 Secrets required 显示由同一有效规则决定。

**选择理由**：逐项可解释，缺省兼容；顶层 citywalk false 是确定信号，不需要推断全部 per-character 覆盖。JWT 必需和核心安全检查不削弱，A5 不应为了不使用的城市漫步要求真实地图 key。

**未选原因**
- 候选 2：直接违反不 preset/新 env；隐含组合会让 A1、回滚和 README 不透明。
- 候选 3：掩盖真实错误、不满足显式选择，伪造密钥有安全/错误诊断风险。基线当前 AMAP 阻断必须如实说明，而不是靠旧 world warning 推导可启动。

**验证方式**：对两项新键及九项任务键做 omitted/true/false/非法值测试；无 AMAP + citywalk false 可通过此项，无 AMAP + omitted/true 仍按原 core 门禁；验证管理 required 显示一致，无密钥值写入/日志泄露。

**风险与回滚**：恢复 citywalk 时缺 key 将重新阻断，README/控制台必须可诊断。回滚需恢复原配置与资源再重启；不删除存储的 key，不借本变更降低全量发布资产清单。

## 2026-11-17 普通 SAY 禁用音频必须走合法文字终态

**待定问题**：TTS 关闭后怎样满足“无音频、文字可达、明确结束”，又不漏 prepared 音频或把 Call 假称可用？

**背景约束**：[SayHandler](<server/src/agent/handlers/action/say.py#L27-L112>) 在 TTS 之前走 prepared 分支；空语音是失败。[Say 值类型](<server/src/domain/agent/action_plan.py#L70-L91>) 已允许纯文字；[WS 转换](<server/src/adapter/websocket/chat/_protocol_translate.py#L118-L133>) 已有成功终态，无需扩协议。Sing 为工单明确排除的独立能力。

**调研参考**：未找到可直接借鉴且可替代本项目输出语义的外部先例；优先采用已存在的 TextFinal/Expression/MessageEnd Interface 及工单 A2。FastAPI 的资源生命周期不决定消息成功/失败语义。

**候选方案**
1. **在普通 SAY 音频分流前选择禁用成功路径**：保留正文/表情；不读预制或 TTS；输出唯一 COMPLETED 终态；Call 能力报告不可用。
2. **禁用 SpeakingSkill 返回空流**：不改 Handler，沿原输出路径消费。
3. **只禁用合成、继续 prepared 音频；或顺带全局静音含 Sing**：较少触及某一分支或更彻底静音。

**选择**：推荐候选 1；prepared 无正文瞬时反应不造气泡，仍发终态。普通 SAY 的 `audio` 始终空串；Sing 继续原行为。

**选择理由**：符合 A2 可见结果与现有协议，避免将主动禁用计算成 AUDIO_EMPTY。`supports_call_audio=false`、`call_tts_character_ids=()` 可复用现有准入和原因优先级，不发明“纯文字 Call”。

**未选原因**
- 候选 2：现有 SpeakingSkill 会 EmptySpeechError，Call 空流也为失败；会向客户端发 `TTS_EMPTY`，不是合法完成且易挂住消息消费者。
- 候选 3：继续 prepared 违反普通 SAY 无音频；全局静音则扩大到明确排除的 singing 曲库/演唱能力。两者均混淆“禁用语音合成”的本轮明确边界。

**验证方式**：真实 WS 两条连续正文、prepared 欢迎、ephemeral 无正文反应；检查全部音频字段为空且每消息唯一成功终态。补 Call capability 原原因优先级及绕过准入的拒绝；enabled 的超时/取消/空音频失败不变。

**风险与回滚**：不能用成功终态吞 sink/连接真实失败；触摸仍不显示聊天气泡；用 TTS true + 资源恢复并重启回退，不改变客户端协议。

## 2026-11-17 向量关闭保留 SQL 正本，不伪造投影成功

**待定问题**：A3“显式记忆写入不报错”应保留什么，怎样兼容维护/旧写入口而不造 upsert ID？

**背景约束**：[MemoryWriteSkill](<server/src/agent/skills/memory_write.py#L126-L175>) 将正本、upsert 确认和关联分开；[维护 writer](<server/src/agent/skills/adapters/memory/writer.py#L251-L319>) 先 embedding 后正本；[旧 intentional 提交](<server/src/agent/skills/adapters/memory/intentional_commit.py#L75-L158>) 有补偿删除与“已有记录必须有 embedding”的旧假设。未获确认的派生数据语义须明确写候选。

**调研参考**：本项目 [AgentMemory](<server/src/agent/skills/adapters/memory/facade.py#L94-L137>) 已将向量称为召回索引，命中后回 SQL 正本；[ChromaVectorStore](<server/src/infrastructure/persistence/database/vector_store.py#L164-L258>) 表明真实 upsert 确认必须来自后端。官方生命周期支持绕过昂贵实现，但没有外部资料可以替用户决定“关闭等于丢弃”还是“保留 SQL”。因此以下是本地设计推荐，不标为用户已批准或官方规定。

**候选方案**
1. **SQL-only + 空长期召回**：显式/事件/维护都可靠保存正本，跳过向量准备/upsert/link，返回真实 SQL ID；不自动回填。
2. **全部 no-op**：显式请求报告无错，但内容不保存或只保存一段临时确认。
3. **NullVectorStore 假成功 ID**：返回输入 ID/随机 ID 让旧链路继续链接，或自动启用本地 embedding 替代。

**选择**：推荐候选 1；维护结果区分 `CANONICAL_ONLY` 与真实供应商故障 `SKIPPED_EMBEDDING`。原身份/冻结候选/幂等/冲突/画像/摘要/进度职责保留。

**选择理由**：SQL 已是正本；保留用户内容不需要重资源，不捏造检索能力。写入口集中依据 enabled 事实绕过投影，旧路径对 SQL-only 的重复判断/补偿需一致，不能假成功后破坏关联。

**未选原因**
- 候选 2：用户“记住”的持久意图被无声丢弃；“不报错”并不授权假装已保存。需要额外明确产品决定才能选。
- 候选 3：破坏“关联指向真实向量”的不变量；零向量/默认本地模型仍可能加载/联网，与无需向量资源冲突。不能用假 ID 或自动回填掩盖 disabled。

**验证方式**：对真实 SQL 检查正本存在、真实 memory_ids、关联数量不增加；同源重试不重复、内容冲突不吞；维护无 embedding 且画像/摘要/进度可提交；enabled provider/SQL 故障维持原语义。重新启用不会自动回填。

**风险与回滚**：SQL-only 不可长期向量召回，语义相似去重退化；README 与确认材料准确说明。关闭不删数据，恢复 true 后原索引照旧可查，但关闭期间正本不承诺被检索。不要为了回退删除 SQL-only 正本。

## 2026-11-17 world 全关选择组合根三门控，保留不含它的边界

**待定问题**：A5 要全部 world 定时任务关闭，而工单又排除“world 任务代码改动”；是否存在不改任务内部的合法接缝？

**背景约束**：已核查 [WorldRuntime](<server/src/world/world_runtime.py#L66-L118>)、[WorldTask](<server/src/world/types/world_task.py>) 和 [WorldClock](<server/src/world/world_clock.py#L50-L93>)。六类有门控，song_knowledge/proactive_topic_check/expired_event_cleanup 无条件创建；空 tasks 当前被拒绝。不存在 `world.enabled`。

**调研参考**：本项目已有 `_task_enabled` 与六类构造前门控是最适配的成熟局部先例；FastAPI 官方共享资源生命周期支持 owner 控制存在性。没有外部项目资料能够判定本仓排除项的文字范围。已核对 `interval_seconds=0` 会报错，大周期仍注册，crawler.activated 不阻止 [远端列表获取](<server/src/world/get_new_songs/daily_new_song_fetcher.py#L149-L166>)，故不能借配置频率造禁用。

**候选方案**
1. **A：只改 WorldRuntime 装配门控**：三类按已有约定判断 enabled（缺省 true）；允许已初始化的合法空 tasks；不改任何任务内部/基类、周期和立即运行语义。
2. **B：完全不改 world 源码**：交两重组件、AMAP、管理和六类已有开关文档；准确保留三类常驻任务，A5 未满足。
3. **频率/非法 type 绕过，或新全局 world.enabled**：尝试不执行或统一关闭。

**选择**：推荐 A，并在规格保留 B 作为不含该变更的准确边界；**后续裁定：D3 attempt 1 已接受 A 属组合根允许范围，不需另等人类批准，不授权改任务内部。** 原记录中的范围不确定性已由非作者解释收敛，整体 spec 仍因 N1/N2 待复审。

**选择理由**：A 复用最小 Seam，以组合根决定是否构造，不改任务算法/触发逻辑，能够同时满足逐项选择、默认兼容和 A5。“world 任务代码”不必然等于“禁止组合根门控”，但需审核者明确解释，不能作者自行扩大已批准范围。

**未选原因**
- B：合法且可独立描述，但 A5 明确未满足，不能按 #412 全部完成验收；仅在维护者拒绝 A 时交这一边界，不悄悄删标准。
- 候选 3：频率和非法 type 不是 disable，会仍初始化/注册，伪造 `world.enabled` 又与逐项控制冲突且不在现状存在。

**验证方式**：单项 false 不构造/初始化/注册，true/省略保持原数据；全九项 false 注册和执行计数为零且空集合不拒启动；不改任务类/内部的差异审查。先取得非作者对范围的明确结论。

**风险与回滚**：D3 attempt 1 已裁定 A 不构成任务内部范围例外；不得把这一接受扩大到 citywalk scheduler/ingestor 工作流修改。节假日一次性 SQL 初始化、Stage/观测/心跳不属 world 定时任务，保留且不冒称全进程后台/联网关闭。恢复具体开关重启，旧任务按既有周期恢复，不保证补跑。

## 2026-11-17 禁用向量期间旧索引重置不得假成功

**待定问题**：向量关闭时用户清除数据，若已有旧 Chroma 文件而低层直接返回 0，重新启用后会不会恢复旧数据？

**背景约束**：[UserResetService](<server/src/application/user/user_reset.py#L69-L103>) 要严格删除向量；[旧向量兜底](<server/src/agent/skills/adapters/memory/facade.py#L211-L225>) 可能不依赖仍存在的 SQL 正本。禁止自动删除旧库/共享目录，不为清除偷启 Chroma。

**调研参考**：未找到可直接借鉴且无需新增持久状态的成熟先例。以现有 reset 的显式部分失败报告和“不得声称删除未删除的数据”的数据真实性为依据；这是风险约束和推荐候选，不是当前已实现的保护。

**候选方案**
1. **无旧资料可空成功，存在/未知则明确失败**：只读检查配置的向量路径；不存在/空目录返回 0，非空或不可判断抛诊断错误，沿现有 vectors 失败报告，指导先启用再重置。
2. **disabled 一律返回 0**：最小 no-op，SQL 其他步骤继续。
3. **持久删除意图/授权墓碑/下次启用再清理**：支持关闭时受理，但新增存储协议、启动清理和恢复机制；或直接删整个目录。

**选择**：推荐候选 1，交非作者审查其保守可用性边界。

**选择理由**：不加载禁用资源，避免隐私删除假成功，也不引入未请求的迁移系统。只对需清旧资料的重置报告未完成，不影响 A3 启动和显式记忆写入。reset 现有流程会有其他步骤部分成功，需如实披露，不伪造事务保证。

**未选原因**
- 候选 2：可能向用户宣称全部清除而留下可召回旧向量，尤其 legacy 路径有复活风险。
- 候选 3：协议与范围成本明显超出两个启动开关；直接删共享目录又可能破坏他人记录。未获明确批准不能作为“顺手修复”。

**验证方式**：分别用无索引、空目录、已有记录目录和不可读/未知路径；验证不会打开 Chroma，新空实例 reset 正常，旧资料 vectors 步骤明确失败且不会误报总成功。enabled 原严格删除回归保留。

**风险与回滚**：非空目录即使不含该用户记录也会保守拒绝“向量已清除”；接受该限制或另审持久删除意图由维护者决定。操作者在资源准备好后启用并重新执行 reset，不由本轮代理删除目录或密钥。

## 2026-11-17 管理台复用局部草稿与现有校验重启，不新增热切换

**待定问题**：A4 怎么让两项开关在控制台可操作，又不覆盖其他面板草稿或误报重启成功？

**背景约束**：[现有配置 DTO](<server/src/infrastructure/config/model_editor.py>)、[apply 路由](<server/src/web/admin/admin_interface.py#L296-L338>)、[局部面板](<server/res/admin_ui/src/main.tsx#L1521-L1649>) 已完成校验→原子保存/备份→Supervisor 重启。

**调研参考**：本项目现有管理工作流为首选；官方 FastAPI 生命周期不授权绕过它。界面针对性检索 `ui-ux-pro-max` 的 `ux` 域 `settings form save validation`：匹配 All 平台 Forms/Submit Feedback、Accessibility/Form Labels、Forms/Inline Validation；仅采用标签明确和提交加载/成功/错误反馈，不引入新视觉体系、图标依赖或页面重构。

**候选方案**
1. **原 DTO 增 component_startup 投影**：新增两复选框面板，部分 patch 映射两个配置叶子，校验/保存/重启仍走原链。
2. **新增 components 热切换端点**：分别启动/停止后台资源，不重建业务 runtime。
3. **任意 raw JSON 全量编辑保存**：界面可快做，但会携带/覆盖其他草稿及资源参数。

**选择**：推荐候选 1，`component_startup` 只是管理 DTO，不增加持久全局配置节点；两个键逐项 patch。

**选择理由**：最少网络与生命周期知识，保留未保存草稿；不破坏旧调用者省略新字段的行为。响应区分 written、restart requested 与真正 runtime running。

**未选原因**
- 候选 2：违背指定重启链，增加在途请求/资源引用切换并发问题，超出 A4。
- 候选 3：混合其他模型修改及原始 `$VAR`/密钥风险，不能保证“只改开关”。

**验证方式**：管理 API 的局部叶子映射、非布尔 422、不写入/不重启、停止状态不启动；实际浏览器分别改两项、刷新读回、其他面板草稿保留、缺资源重启显示真实失败，不拿 restarted=true 当可用证据。

**风险与回滚**：当前 restarted 表示曾运行并发起重启，不代表新 runtime 成功；UI 必须看 state。失败保留原错误/所有权，操作者恢复正确配置或备份再重启，不覆盖现用配置。

## 2026-11-17 以真实链路和同机原始值验收，不把估算当资源收益

**待定问题**：怎样提供成本可控、又足以证明 A1–A6 的证据？

**背景约束**：工单要求单元/集成、实际控制台和全量/最小资源比较；本轮仅 spec。已有 TTS 600s 为等待上限、Chroma 150–300 MB 为静态估计，不是本轮实测。

**调研参考**：FastAPI 官方生命周期测试要求观察实际启动/关闭；本仓 [开发守则](<docs/开发守则.md#L49-L67>) 要求从测试之外确认预期，不能拿 mock 返回值自证。采用规格 V0–V5 分 owner 证据预算；不重新发明基准工具链。

**候选方案**
1. **分层证据**：离线构造陷阱/真实 SQL/WS 契约，隔离实际闭环，非作者控制台/README；同机同条件全量/最小各至少三轮原始测量。
2. **只跑 mock 单测与 runtime.running**：便宜，但没有启动资源、客户端收包或 UI 证据。
3. **用 issue 中 GB/MB 估计填收益，或先做全量 CI 当全部验收**：看似数字完整，却无法证明本次功能行为。

**选择**：推荐候选 1；不同 claim 单一 owner、最小非重复测试；外部门禁由 lead/verifier 统一调度。无真实资源则明确全量比较未验证，不假测。

**选择理由**：直接覆盖用户可观察结果及禁用边界，保留底层与集成的区别；测量固定启动 t0/业务 ready、主进程 RSS 30s 窗口、递归子进程、缓存分组、清理记录。

**未选原因**
- 候选 2：替身有可能未经过正式工厂/validator，不能证明 A5 和无隐藏重资源，也不能证明 UI 可操作。
- 候选 3：静态估计不是实测，全量 CI 不能代替控制台/真实资源验证；重复并发全量还会污染资源比较。

**验证方式**：本轮仅 V0 文档结构/链接/差异与示例校验，A1–A6 保持未执行。实现后按同一环境、同一角色/模型/数据基线对照全部原始测量值，不遗漏失败轮次。远端 CI、真实供应商/设备的未测边界逐项披露。

**风险与回滚**：没有全量资源或环境无法一致就不宣称比较完成；不下载模型/安装 pip 来造证据，不改现用 secrets。检查失败先修复文档或实现，不通过降低原预期获得绿灯。

## 2026-11-17 D3 N1：混合 citywalk 选择明确的装配级执行跳过

**待定问题**：只关向量而保持 citywalk 请求开启时，既有直接向量写消费者如何准确降级，且不违反“不改 world 任务内部”？

**背景约束**：D3 attempt 1 仅要求补齐该组合，不要求新增“无向量 citywalk 仍完整成功”能力。已接受的 G1 只覆盖组合根；低层拒绝写入、无假 ID/count 仍保持。用户逐项选择不能被偷偷改成 citywalk=false，也不应把可选任务依赖关闭传播成整个聊天服务启动失败。

**调研参考**：本轮不扩展外部研究，只核对真实调用：[Task 构建服务](<server/src/world/citywalk/task.py#L233-L248>)、[service 先落报告后 ingest](<server/src/world/citywalk/runtime_scheduler.py#L19-L36>)、[ingestor add 后返回 len(docs)](<server/src/world/citywalk/memory_ingestor.py#L93-L118>)。它们没有可注入的投影 Interface。已有 [Task service=None 早返回](<server/src/world/citywalk/task.py#L105-L108>) 可由 [WorldRuntime 依赖派发](<server/src/world/world_runtime.py#L111-L117>) 选择，不必改任务内部方法；实际可实施性仍须 attempt 2 核对。

**候选方案**
1. **M1-S：组合根明确执行跳过**：vector=false 时 WorldRuntime 在依赖派发后/注册前给城市任务选择既有 citywalk_service=None 状态；保留 requested enabled、定时注册与周期，validator warning 解释“依赖关闭导致整项执行跳过”。任务触发返回原 unavailable skipped result，不进入 service.run_once，不生成报告/SQL travel/观察事实。
2. **只披露低层拒绝造成部分副作用**：不增加装配选择，允许 report 已落盘后因 add 拒绝失败，记录未提交 SQL/观察；整个聊天仍正常。这是报告推荐的最窄可接受下限，但对操作者的部分产物更易造成误解。
3. **保留完整 report/SQL，仅跳过投影**：改 scheduler/ingestor 的 capability/注入接缝，使返回 path 后继续 SQL/观察；或把低层 add 变 no-op/返回假 ID。
4. **拒绝该混合配置/自动设置 citywalk=false**：配置易诊断或容易实现，但前者阻断整个服务、后者改变用户显式逐项选择。

**选择**：推荐候选 1 送 D3 attempt 2；不是已经获准的新完整规格，也不是实现许可。保持 AMAP 按 citywalk 请求 true 的已审条件必需；warning 名为 citywalk.vector_projection 且 status=warning，不触发自动 world disablement。

**选择理由**：只在既有组合根选择不可用依赖，沿 Task 已有语义得到诚实 skipped，不造成功产物，不改任务算法/触发规则；在执行任何报告副作用前明确阻止，保留配置意图和聊天可用。重启重新启用向量可恢复原服务，不需新全局开关或重构。

**未选原因**
- 候选 2：可如实披露且不超 scope，但留下“有报告无 SQL/观察”的中间结果；依赖可用性接缝足以在执行前跳过时，不优先采用半途失败。
- 候选 3：完整保留能力需要 world 内部工作流改动，超出已接受排除；低层 no-op 又会让 ingestor 误报 len(docs)，与无假计数不变量冲突。不得借 G1 接受扩大范围。
- 候选 4：阻断启动不利于 A3，自动关配置违背逐项选择；推荐明确 requested=true / execution skipped，不把两者混为 disabled=false。

**验证方式**：真实 WorldRuntime mixed 配置下，warning 可见且配置仍 true、任务仍注册；触发原 Task 返回 ok=true/skipped=true/message=citywalk service is unavailable/data={}；service.run_once、ingestor、vector add 均不执行，无报告/SQL travel/观察事实；聊天照常且无向量资源。true/true 复核原 citywalk 链路；不用替换 Task.run_once 的自定返回值自证。

**风险与回滚**：该混合组合牺牲整个城市漫步执行而非仅索引，是必须在 README/validation 明示的能力限制，等待非作者接受。若装配接缝不能安全完成，不转为内部改动；退回已披露的候选 2 另行审定。恢复向量并重启回原状态，不补跑/清数据。

## 2026-11-17 D3 N2：固定生成器与自由模型采用不同正文判据

**待定问题**：A5 精确“核心链路412”是否错误要求真实模型逐字服从？

**背景约束**：工单要的是注册→登录→WS 文字→历史闭环，而非约束任意供应商模型的措辞。离线仍必须走真实配置、装配、网络转换、SQL 与关闭，只替换生成器，不替换整个投递链。实际模型联调和实际资源证据不能被取消。

**调研参考**：D3 attempt 1 N2 及工单 A5；不需要新研究、提示词重构或把字面文案变成人类必答问题。

**候选方案**
1. **分层断言**：离线固定生成器确切输出核心链路412，WS/历史逐字对应；真实模型保留同示例输入，要求非空实际正文、成功终态、无音频、后续继续、历史正确保存实际输入/回复及无 world 定时执行。
2. **所有场景硬断言精确文本**：把提示词服从当开关验收，必要时硬编码或强改 prompt。
3. **只保留固定生成器**：避免不确定性，但放弃真实联调证据。

**选择**：候选 1，已同步 A5、README 操作例与 V3；等待 attempt 2 对本版修订确认。

**选择理由**：离线确定性可归因，真实模型按本功能可观察结果验收；历史与 WS 实际正文对应比固定自由措辞更能证明链路正确。

**未选原因**
- 候选 2：把模型自由生成差异错误归为 #412 失败，硬编码/改 prompt 又污染范围。
- 候选 3：违反既定真实证据分层，不能因离线全绿宣称全部真实验证完成。

**验证方式**：离线精确文本与实际模型实际正文分开记录，均校验 terminal/history/后续消息/零 world timer；本轮只做文档静态核对，未执行这两路验收。

**风险与回滚**：真实模型失败、无正文、失败终态或历史丢失依旧是需诊断的真实结果，不以自由生成放宽这些标准。无需变更运行代码/配置来修正文本判据。

## 2026-11-17 Phase412-1：在既有语音 Skill 内显式禁用，普通 SAY 正常完成

**待定问题**：按已审完整规格实施第一自然阶段，怎样证明 false 真正不创建 TTS 资源，而不是只返回空流或绕过生产选择接缝？

**背景约束**：规格提交 `b50ab5309b3c0a5ec99d7d5fbc856c85d30bdb29`，D3 attempt 2 已通过；lead 将 task-7 CAS 至 revision 3，仅授权配置/TTS/合法文字、相应测试与模板。向量、world、AMAP 条件重构、DTO/UI/README 及完整 A1–A6 闭环属后续阶段；Oracle 实现 gate 前不提交本阶段。不改现用配置、密钥或依赖环境。

**调研参考**：沿规格已核实的 FastAPI 官方资源生命周期原则与本项目 SpeakingSkill/SpeechBackend/SharedSkills/SayHandler Interface，不再扩展技术研究。预期来源为 [已审规格 A2/输出契约](<docs/specs/component-startup-switches.md#L209-L226>)，而不是从测试替身返回值推断。

**候选方案**
1. **既有 Skill 显式禁用状态**：严格解析默认 true 的 bool；false 时不创建 SpeechBackend/AsyncTTS，公开只读 enabled、Call false、幂等 stop/abort，直接 speak 抛 SpeakingDisabledError；普通非 CALL SAY 在 prepared/TTS 分流前输出正文/表情和唯一成功终态。
2. **新建平行 DisabledSpeaking 类并改所有装配调用者**：可行，但当前 Skill 已拥有资源与生命周期，额外层对本阶段没有更多行为收益。
3. **None/空流/吞错误降级**：少改构造，但会走 EmptySpeechError/失败终态，或丢 prepared 限制，不能证明不持有资源。

**选择**：候选 1。SharedSkills 的现有 `SpeakingSkill(config.get("speaking"))` 已是完整选择接缝，保持该文件零差异；不为显示“有装配变更”而添加无用工厂。SAY 读取 enabled 时为既有测试/预制调用的无能力属性替身保留默认 true，仅显式 false 进入新分支；真实 Skill 始终提供严格 bool。CALL 在已有许可校验后返回 DEPENDENCY_UNAVAILABLE，不走文字成功回退；Sing 未修改。

**选择理由**：最小实现集中拥有资源的 owner，无新全局框架。启用分支的 TTS、预制音频、取消、故障、输出回执规则均不改；禁用 speak 在计量/供应商工作前明确拒绝。validator 只对 false 跳过 TTS 专属资源，缺省/true 仍按原必需；模板只增加 true 新叶。

**未选原因**
- 候选 2：会扩大 facade/类型/测试面，两个行为分支在同一资源 owner 内即可清楚表达；本阶段无需新层。
- 候选 3：空流是音频故障，不满足合法纯文字成功；prepared 还有独立读取分支，不能只关合成；吞 sink 失败又会虚报交付。

**验证方式与本轮实际证据**：使用已安装 Python `3.10.21`，pytest 默认不跑外部/真实模型。

- 首条红灯：新增 `test_disabled_speaking_creates_no_backend_and_closes_idempotently`，真实构造 false 仍调用 SpeechBackend，触发禁止资源构造陷阱，`1 failed in 0.66s`；最小改动后 `1 passed in 0.10s`。
- 直接 speak 红灯为 `_tts=None` 后 AttributeError，`1 failed in 0.66s`；明确禁用异常后两条语音资源/直接拒绝用例 `2 passed in 0.08s`。最终还覆盖默认注入 engine 保持启用、false 不使用注入 engine、非法值矩阵。
- SkillsConfig 公开解析对六类非 bool 原先均未抛出，`6 failed in 0.63s`；严格校验后，含真实 SharedSkills/AgentMemory/MemoryStore 装配共 `7 passed in 0.07s`。装配测试只给模型注册端口和现有向量依赖，不替换技能类或 speaking 选择；它证明共享技能子系统选择，不冒称完整 ServerRuntime 启动。
- 普通 SAY 经真实 Agent 与公开 Adapter `open/next_output/complete_output`，初始得到 AUDIO_GENERATION_FAILED，`1 failed in 1.53s`；prepared/瞬时反应原先仍触读取陷阱、未交付终态，`2 failed in 5.28s`。修复后该三场景 `3 passed in 0.57s`，后续补上纯文字无 sound_content、Call（含 prepared）拒绝、sink 失败不伪发成功、消息身份/序号/唯一终态。
- validator false 无 TTS 配置原为 `core_ok=false`，`1 failed in 2.89s`；条件化后纳入定向绿灯。补 false 留有失效路径也不检查、非法 bool 仍阻断、true/省略仍要求资源。
- 中间一次新增 ChatEndpoint 忘记 `connection_generation`，导致 `3 failed,180 passed in 7.75s`；这是新增测试端口缺字段，不是产品红灯/平台差异。补齐真实 Adapter 所需端口后相同 12 文件回归 `183 passed in 5.84s`；再补无音源 SAY 用例后 `184 passed in 5.53s`。最终冻结回归结果在交 lead 的阶段报告中列出，不能把这些中间数字当全量验收。
- 最终候选执行上述 12 文件：`185 passed, 2 warnings in 5.76s`（job `pwsh-935d3a94355e4e73`，exit 0）。小范围 Ruff `0.14.10` / Black `26.5.1` 对五份改动生产源码通过；对两新增测试及 Call 追加测试也通过。旧测试文件原有格式未顺手全格式化。所有新增文件仍按最终状态检查差异空白/路径白名单。

当前重复回归命令（cwd 为 `server/`，`python` 指已安装的 agent 环境）：

```text
python -B -m pytest tests/unit/agent/test_speaking.py tests/unit/agent/test_speaking_module_ownership.py tests/unit/agent/test_call_say_permit.py tests/unit/agent/test_call_say_output_metadata.py tests/unit/agent/test_tts_cancellation_boundary.py tests/unit/test_call_transport_capability.py tests/unit/web/test_call_capability.py tests/integration/runtime/test_component_speaking_startup.py tests/integration/websocket/test_disabled_speaking.py tests/integration/websocket/test_websocket_adapter.py tests/integration/system/test_admin_runtime.py tests/integration/agent/test_skill_configuration.py -q -p no:cacheprovider
```

**风险与回滚**：最初 PATH 找不到 ffmpeg，测试有 pydub warning；ci-verifier 实际确认 agent 环境 `Library/bin` 的 ffmpeg/ffprobe `8.1.2`，仅测试子进程临时前置该目录，后续无 ffmpeg warning，未安装或修改全局 PATH。剩余 Starlette BlockingPortal 与 zhconv/pkg_resources 弃用警告如实保留。未运行全量 CI、真实 TTS 权重、完整账号/HTTP/WS/SQL 闭环、浏览器、真实模型或资源对比；Phase412-1 局部绿灯不等于 A1–A6 通过。要恢复语音需操作者准备原资源、设 true 并重启；不用删除用户数据。当前阶段实现未提交，等待 lead/Oracle gate。

## 2026-11-17 Phase412-2：禁用向量保留真实 SQL 正本，不伪造投影

**待定问题**：按照已审 §3.5，在向量资源完全不启动时，怎样保持显式写入、维护、授权召回与旧入口的真实持久化/失败语义？

**背景约束**：Phase412-1 已在 Oracle implementation attempt 1/3 PASS 后由 lead 授权原子提交 `42ce9e9843bf62b1af022d53c4d950c61be6b6c8`，工作树干净且未推送。lead 将 task-7 CAS 至 revision 4 授权本阶段 exact19路径；只做向量/SQL-only，不能修改 MemoryStore/schema、world/M1-S、AMAP、DTO/UI/README 或自动回填。Phase2 gate 前不提交推送；阶段绿灯不是 A1–A6 全交付。

**调研参考**：沿用 [已审 §3.5](<docs/specs/component-startup-switches.md#L228-L295>) 与既有正本/向量 Interface；call-repair 提供独立只读五项安全输入，指出 legacy 补偿、无条件 True、maintenance_id 跨角色碰撞与 reset 隐私边界。本轮不重新研究/扩架构，不把辅助提示当实际测试或 gate。

**候选方案**
1. **非空 DisabledVectorStore + 正本成功后跳投影**：真实工厂在 Chroma/embedding/线程池/目录之前选择禁用实现；低层读空、误写/嵌入明确拒绝，正本/维护写入口依明确能力事实绕过投影与 link；保留原受信身份/冻结/SQL幂等和错误传播。
2. **Null 实现返回输入 ID 或空向量，再照旧链接/补偿**：caller 少改，但不存在的索引会被写入关联，或 legacy 无 ID 补偿反而删除正本。
3. **统一移除向量、重写事务/旧记忆体系或自动补索引**：能统一接口，却扩大到 schema/存储 owner、数据迁移与新平台，超出本阶段及工单。

**选择**：候选1。复用 `init_vector_store`/工厂与 AgentRuntime 原装配；AgentRuntime、CognitiveMaintenanceSkill 保持零差异。Base VectorStore 的只读 enabled 默认 true，禁用实现 false；缺省/true 仍原 Chroma，不把真实故障转 disabled。MemoryWriteResult 仅新增默认 true 的 `retrieval_enabled` 事实供确认材料，不造通用状态平台。

**选择理由**：原 SQL 是正本，向量为可选召回投影；if_absent 的真实身份/内容冲突检查已足够，不改 MemoryStore。维护 CANONICAL_ONLY 是正本已可靠保存而没有投影，不混同 SKIPPED_EMBEDDING；原维护 owner 在所有写成功后才提交画像/摘要/进度，真实 SQL 错误/取消/冲突继续向上。

**未选原因**
- 候选2：假 ID、假计数会破坏正本→真实向量不变量；返回空值会令旧补偿链当损坏并删除合法 SQL-only 正本。直接查询也不能先触 embedding 再故障降级。
- 候选3：不需要新增事务/迁移/删除队列就能达成已审契约；新平台扩大回滚/授权风险，也违反无自动回填与当前19路径限制。

**受限旧入口 commit=False 裁定**：lead 已明确要求“本次不提交则不得声称已保存”，不改变 enabled 原行为。disabled 的 `commit_user_memory` 若没有已持久同身份正本，返回 `("",False)` 且不写正本/update/link；已存在则严格核 owner/user/type/visibility/source/content 后返回真实旧 ID+False，冲突拒绝。disabled 两个 bool 入口同样不写且返回 False；False 是“本次未保存”，不是正常保存成功。三个入口的 commit=True 都走真实严格 if_absent，跨入口用户事实使用原稳定 ID、同日事件使用 owner/user/date/规范文本确定 ID，不伪造向量标识。风险是旧 caller 不能再把 disabled+commit=False 当已持久化承诺；主 `commit_fact` 始终真提交，不受这条旧接口限制影响。

**已实施的最小契约**：

- 真实工厂 strict bool，false 不建目录、Chroma、embedding 或专用池；低层 search/get_by_id 空，add/upsert/update/prepare/embed 明确 VectorStoreDisabledError，close 幂等。strict delete 对不存在/已确认空路径才0，非空/文件/符号链接/不可判断均 VectorDeletionUnavailable，不开旧Chroma、不删数据。reset沿既有部分成功/HTTP500/fence释放，不新增错误协议。
- 显式/事件写保持稳定来源身份、冻结候选复用、真实 SQL ID与 CREATED/DUPLICATE/NO_CANDIDATE；disabled跳upsert/link而非假返回。用户确认只在实际正本成功后，材料明确“已保存正文；长期检索关闭，恢复时不自动建索引”，不强制模型逐字措辞。
- 维护 disabled 非空候选全部 SQL 成功后 CANONICAL_ONLY/日志 index=disabled；无 embedding/link，memory_skipped_count=0。维护批次ID算法不改；同 maintenance_id/index 的敌对跨角色或跨用户碰撞由既有 if_absent 拒绝，不吞成重复或覆盖。真实部分 SQL失败/取消/冲突不推进画像/摘要/进度，允许原 owned-operation 已完成的部分正本留待同批重试。
- MemoryRetrievalSkill 先校 USER身份/角色/MemoryQuery，再屏蔽 USER/CHARACTER含 YesterdayCityWalk；公共歌曲 SQL/目录不变。AgentMemory一般话题召回也提前空，避免直接调用先 embed。重新创建真实启用Chroma不自动将 SQL-only 记录补入；既有索引和数据不删除。

**红→绿与实际证据**（agent Python `3.10.21`，Ruff `0.14.10`、Black `26.5.1`，cwd `server/`）：

| 垂直片 | 原始红灯 | 修复后已执行证据 |
| --- | --- | --- |
| 公开 init_vector_store 资源构造 | `pwsh-691dcbf5265940b1`：false 仍走真实 Chroma 构造并触 ThreadPoolExecutor 陷阱，`1 failed in 1.42s` | 同条 `pwsh-12d9ac6784ea4521`：`1 passed in 0.07s`；strictbool/误写拒绝/strictdelete矩阵随后 `12 passed in 0.10s`。未替换工厂/ChromaVectorStore自证。 |
| 显式 SQL-only | `pwsh-86f642289ff04e0b`：正本后仍 upsert，VectorStoreDisabledError，`1 failed in 1.51s` | 三个C/U组合/异内容冲突/无关联/SQL失败与维护首批及旧enabled记忆回归 `16 passed in 3.84s`。 |
| 维护候选 | `pwsh-8fe00488508649b3`：仍 prepare_embeddings，`1 failed in 0.92s` | CANONICAL_ONLY、同批重试、敌对跨C/U冲突、真实维护成功/第二SQL失败/取消/冲突不越进度均进入最终集合；enabled embedding outage保持原skip。 |
| 授权召回 | `pwsh-83c292bb63b040f9`：仍先 embed_query，`1 failed in 2.88s` | 私有/角色/Yesterday空、身份错误仍拒绝、公共歌曲真实SQL，`2 passed in 0.54s`及最终集合。 |
| legacy intentional/bool | `pwsh-deb843fa8d044def`：add触禁用拒绝，`1 failed in 0.95s`；`pwsh-6f99db71487848f9`：bool两入口 `2 failed,1 passed in 1.60s` | 窄 disabled 正本分支+原enabled投影补偿基线 `8 passed in 0.78s`；commitFalse无写/已存仍在/冲突与SQL异常后续加入。 |
| 确认材料 | `pwsh-d5d89fa8a1524ab3`：没有“已保存正文/长期检索关闭”材料，`1 failed in 0.72s` | 真实Handler编排+相关记忆用例 `24 passed in 3.85s`。 |
| validator strictbool | `pwsh-97c63735866b45a1`：六非法值 core_ok仍true，`6 failed in 3.24s` | strictbool/disabled状态报告与AgentRuntime真实工厂装配加入最终集合。 |

**非产品失败如实排除**：新 AgentRuntime 测试首次提供 media_resolver=None 后调用 ensure_dependencies，导致夹具缺依赖（`1 failed,6 passed in 19.48s`）；补非空媒体端口后误断言 Agent 公开 character_id（实际无此属性），`1 failed,1 passed in 1.82s`。均仅修测试，不能算产品红灯/平台差异。旧enabled真实Chroma回归使用临时库并替换 embedding HTTP方法，不表示使用真实供应商；未删/跳该基线。

**最终阶段验证**：`pwsh-b50507fbcb0e4f21` 执行下列精确相关集合，`163 passed, 3 warnings in 14.28s`，exit0。其中warning为 zhconv/pkg_resources 与两处 Chroma embedding get_config弃用；未称零告警。十份生产改动 Ruff/Black通过，三新增测试 Ruff/Black通过；受影响旧测试只追加，不全格式化。源码最终版本与新增文件全部进入外部冻结manifest；本阶段不重跑Phase1的185或全量CI。

```text
python -B -m pytest tests/unit/infrastructure/test_disabled_vector_store.py tests/integration/persistence/test_disabled_vector_memory.py tests/integration/runtime/test_component_vector_startup.py tests/unit/agent/test_intentional_memory.py tests/unit/agent/test_maintenance_memory_writer.py tests/integration/persistence/test_memory_write_skill.py tests/integration/persistence/test_intentional_memory_storage.py tests/integration/persistence/test_memory_retrieval_skill.py tests/integration/persistence/test_maintenance_memory_projection.py tests/integration/agent/test_topic_reply_pipeline.py tests/integration/system/test_admin_runtime.py tests/unit/agent/test_cognitive_maintenance.py::test_embedding_outage_skips_memory_but_commits_profile_summary_and_progress tests/unit/agent/test_cognitive_maintenance.py::test_cas_conflict_does_not_compact_or_overwrite_progress tests/unit/agent/test_cognitive_maintenance.py::test_cancellation_before_progress_does_not_advance_marker tests/integration/agent/test_call_threshold_maintenance.py::test_call_embedding_outage_keeps_threshold_summary_profile_and_ending_progress -q -p no:cacheprovider
```

**风险与回滚**：无自动回填，SQL-only 记录重新启用也不保证可长期召回；旧非空/未知索引reset会明确部分失败，不代表事务回滚。恢复向量需操作者准备原资源并设true重启，不删SQL/目录。Phase3 M1-S城市漫步依赖降级尚未实施，本阶段不得宣称 vector=false/citywalk=true 已安全完成；AMAP core必需、world、UI与真实闭环/真实模型/真实full-min资源对比仍待后续，不预判资产缺失，也不以静态估值或fakebenchmark交付。本阶段未提交推送，等lead/Oracle实现gate。

## 2026-11-17 Phase3A：world 组合根门控与条件依赖同步

**待定问题**：怎样在不改任务内部算法/周期的范围内，让全部 world 定时任务真正不构造/不注册，并诚实处理 citywalk 请求开启但向量关闭的混合组合？

**背景约束**：Phase2 在163定向+Oracle implementation1/3 PASS后由lead许可原子提交 `6c3f5e7d7c7419535c375fe556dad566b57b017e`，未推送；task-7 revision5批准本单元exact8路径。3B DTO、3C UI/README、3D实际隔离闭环、真实模型/资源比较另行分阶段，不能在此顺带实现。用户现用config/密钥不改，不新preset/env；非作者D3 attempt2已接受G1/M1-S，不重开产品取舍。

**调研参考**：沿既有 WorldRuntime 构造→initialize→注册与 CitywalkTask 的公开可空 citywalk_service/早返回接缝；validator 与 Secrets管理原接口。设计依据是[已审world/M1-S契约](<docs/specs/component-startup-switches.md#L181-L208>)与[混合组合](<docs/specs/component-startup-switches.md#L281-L295>)。独立phase3只读准备报告只作定位，不是运行证据；本轮不新增研究。

**候选方案**
1. **既有组合根补三门控、合法空集合与依赖选择**：三项默认true；任务基础初始化后/注册前，向量false使已请求citywalk的optional service=None，保留原请求开关/定时名称/周期，触发真实skipped。AMAP条件与Secrets共用同一规则，显式disabled凭据不检查。
2. **改任务内部/调整周期或非法type冒充关闭**：能少改某些构造，但不满足无任务/零执行或超出内部流程排除。
3. **自动关citywalk或混合组合阻断整个服务**：表面避免写向量，却改变逐项请求或让可选依赖导致聊天起不来。

**选择**：候选1。World目录生产差异仅WorldRuntime；不编辑Task/RuntimeService/Ingestor/WorldClock。三门控外只移除“已完成初始化但tasks空仍拒绝”的检查。保留一次性ensure_holidays，零world定时动作不冒称全进程零后台。

**选择理由**：已有owner与Seam足够，不需重构注册系统。M1-S在任何任务执行前完成，既有Task.run_once自然返回 `ok=true,skipped=true,message=citywalk service is unavailable,data={}`；无report/SQL travel/观察/向量成功计数。重新构造向量true实例恢复原service，不补跑/删数据。

**未选原因**
- 候选2：延迟不是disable，0频率非法，改任务内部则违排除；不能用猴补丁生产Task或假vector消除错误。
- 候选3：raw requested=true不代表依赖一定ready，但不可悄悄持久化false；warning必须非disabled并保留apply_world_disablements现有规则，不因向量关闭丧失整个聊天可用。

**条件校验**：九任务顶层enabled严格bool，代表非法值与角色覆盖校验不truthiness；缺省true。`required_secret_keys(config)`由validator对外提供，JWT始终必需，仅顶层citywalk=false解除AMAP，角色true不能反开顶层false；mixed citywalk=true/vector=false仍AMAP必需。Secrets.status使用同一规则，不读/写真实值。显式关闭B站/自动学歌不检查其credential路径；mixed增加world citywalk.vector_projection warning，不走自动关。模板补齐缺少的七个true叶，已有auto_song_learner/qq_refresh true保留，其他配置不改。

**实际红→绿**（agent Python3.10.21，Ruff0.14.10/Black26.5.1）：

| 断言与来源 | 红灯 | 绿灯/覆盖 |
| --- | --- | --- |
| 已审A5改变旧三无条件任务错误预期 | `pwsh-66cddd390c3342ae`：disabled仍注册三项，`1 failed,1 warning in1.51s` | 三构造门控后同条 `pwsh-b99faf22db2240a6`：`1 passed,1 warning in0.77s`。不是为了绿灯降旧保证，而是已审契约改变条件行为。 |
| 真实九项构造trap+原Clock全空 | `pwsh-eb336ec89ebd49fb`：所有Task未构造但tasks=[]被ensure拒绝，`1 failed,1 warning in1.08s` | 合法空集合后 `pwsh-43d432fad47d45ea`：`1 passed,1 warning in0.51s`；一次holiday工作仍启动/清理，原Clock注册表与运行任务都0。 |
| 真实M1-S初始化与执行入口 | `pwsh-a252ebc6c87f4210`：原城市服务仍存在，`1 failed,1 warning in1.31s` | 根依赖选择后两个真实world场景 `pwsh-20029638bc924423`：`2 passed,1 warning in0.82s`；Task.initialize/run_once未替换，SQLite event无写、无观察，服务执行设trap不触发，恢复true service可重建/周期不变。 |
| AMAP条件 | `pwsh-cec97631e8954522`：citywalk=false缺key仍core阻断，`1 failed,1 warning in2.36s` | shared条件后JWT保留、顶层false压角色true，mixedtrue仍AMAP必需。 |
| Secrets.required一致性 | `pwsh-f6aa6d9f3f5a46e9`：AMAP仍required，`1 failed,1 passed,1 warning in2.63s` | 管理页投影使用validator同一条件，不维护第二份hardcode列表。 |
| world strictbool代表 | `pwsh-03607ee1107e4cf6`：九任务字符串false未拒，`9 failed,45 deselected,1 warning in2.54s` | 同一验证helper九任务代表非法值覆盖（不继续机械9x6矩阵），默认/角色顶层优先与enabled周期原回归保留。 |

**候选主体及窄修验证**：下列5文件先完成 `106 passed,1 warning in3.25s`，job `pwsh-fe165188d6e14b29` exit0；三生产源Ruff/Black PASS。随后lead指出本新增world容器路径须安全报告：required_secret_keys已用安全_get，但_validate_world_switches遇world=[]仍.get抛AttributeError。根/section两个代表用例 `pwsh-61a13d603b3943ee` 得 `1 failed,1 passed,1 warning in3.07s`；仅给new switches根容器core.world error、optionals非法根直接跳过，原8scope不扩。修后代表/邻近AMAP/Secrets/mixedwarning/禁用credential/真实world共 `8 passed,1 warning in2.14s`（`pwsh-c24bd1e220424972`），validation Ruff/Black通过；不重跑106/163。旧candidate 0c9bce…仅修前，不算当前已通过，按新manifest冻结再交同attempt1增量审核。新world证据文件Ruff/Black及原world测试Ruff也通过（先前综合job `pwsh-5951e1b1a05f4c74`），唯一警告为既有zhconv/pkg_resources弃用。没有业务夹具红失败误记为产品修复，格式初查行宽/Black问题已在授权文件内修正。

```text
python -B -m pytest tests/unit/world/test_world_runtime.py tests/unit/world/test_world_clock.py tests/integration/world/test_disabled_world_startup.py tests/integration/system/test_admin_runtime.py tests/unit/world/test_world_task_citywalk.py -q -p no:cacheprovider
```

**风险与回滚**：world关闭会停止清理/提醒/学习等，明确不保证补跑；M1-S是整项citywalk跳过而非只少索引。AMAP重新请求true时需准备key，JWT不放宽。恢复具体开关/依赖并重启；不删除用户数据/资源/凭据。当前仅组合根与条件校验闭合，未证明完整注册登录/网络WS/历史/媒体/管理UI或资源性能。真实资源前置已确认资产存在与路径/密钥缺口，但只stat不能冒称可推理/full-min收益；不fakebenchmark、不擅自付费调用/迁移现用路径。3A未提交，等Oracle与lead明确许可。

## 2026-11-17 Phase3B：管理DTO逐叶映射与原保存重启契约

**待定问题**：如何在不重构管理工作流的前提下，让两个组件开关可读取/保存，并准确拒绝非法输入、不覆盖角色/模型/密钥占位、不破坏旧owner安全停止？

**背景约束**：3A已在同attempt1增量PASS后由lead授权原子提交 `80739a5b86a1e1d3f3b8096b5017ff58ebb6b969`，未推送；task7rev6仅五路径：model_editor/admin_interface/两个新测试/本AI。UI/README/build由desktop-ui独占另scope，完整真实A4/A5与资源测量在后续；不并发改AI、不改Supervisor内部或world/模板。

**调研参考**：沿[已审管理DTO契约](<docs/specs/component-startup-switches.md#L297-L315>)和现有 `apply_llm_config_draft→validator→ConfigStore.write_raw→RuntimeSupervisor.restart`，不新增研究/热切换端点。

**候选方案**
1. **新增DTO投影+专用组件输入校验**：GET始终给两个有效bool（缺省true）；POST对象/叶可省略；严格bool/未知叶由ComponentStartupDraftError携完整DTO路径，route只把这个新增错误映射422；逐叶merge到原raw owner节点。
2. **保存整个UI草稿到raw或统一catch所有ValueError**：便于处理，却可能丢characters/embedding/model/$VAR，或改变旧模型错误语义。
3. **独立组件热应用/新Supervisor**：额外端点和并发资源切换，超出既定重启规则。

**选择**：候选1。新component parser为窄helper，主apply函数调用它但不增加额外分支（避免C901从10到11）；仅新错误映射422，旧call_transport/model分支行为不变。component_startup不是新持久配置节点。GET使用现有路径读取，正常保存后反映false/true，默认缺省兼容。

**选择理由**：最小改动就能复用备份/原子写、校验和原Supervisor安全owner门禁。没有新restart逻辑；`restarted=true`仍只表示曾运行并请求重启，response.runtime.state/running反映实际失败/成功，UI阶段据此展示。

**未选原因**
- 候选2：覆盖整raw会把本面板外内容混入，或改写占位/配置；泛捕旧ValueError使非本契约报错改变，难定位与回滚。
- 候选3：不满足复用现有保存/重启要求，增加在途资源引用竞争及维护面。

**实际红→绿证据**（agent Python3.10.21/Ruff0.14.10/Black26.5.1）：

- 默认投影首红 `pwsh-8d6c2ab3edf440bb`：KeyError component_startup，`1 failed in0.61s`；最小projection后同条 `pwsh-a0458d7a7ce34612`：`1 passed in0.03s`。
- 单叶patch映raw红 `pwsh-b74bd328377a4097`：speaking.enabled没写，`1 failed in0.61s`；新helper映射后新/旧字段真实配置比较通过，输入副本不变、另叶/characters/embedding/$VAR全保留、无持久DTO节点。
- 真实AdminAuth setup/login/Bearer管理route非法输入红 `pwsh-a6481893b7cf482c`：stringfalse、int0、未知叶、对象null均200，`4 failed,2warnings in3.14s`；专用新增错误422后新两文件绿灯。
- 中间fixture每例真实登录消耗同进程5次/300s限流，`pwsh-8c67ea829ef04dab` 得 `7passed,3errors,2warnings in9.26s`。这是测试隔离错误，不是组件产品红灯；沿已有 `_reset_rate_limit_state` 在测试fixture重置，不改生产限流/不跳鉴权/不等sleep。
- 完整新DTO/管理集成 `pwsh-3ec5040fe56a44fc`：`12passed,2warnings in4.62s`。实际使用临时ConfigStore、SecretStore、validator、FastAPI路由与AdminAuth；检查未鉴权401、非法422无写无restart、validation失败不写不停、停止保存只validate不自启、运行调用原重启、备份字节等原raw。
- 两条使用**真实RuntimeSupervisor**的重启集成保留其stop/start方法，只替换外部昂贵ServerRuntime.initialize和旧owner资源；成功事件为old.shutdown→new.initialize，旧shutdown抛清理未完成时不构造新runtime、保留旧owner、response显示failed/running=false。不是用自定义restart结果自证安全，也不冒称完整ServerRuntime或实际浏览器A4。
- 最终相关旧管理字段回归 `pwsh-5169ea34903c4064`：5文件 `95passed,2warnings in4.60s`；旧音频模型/config/module_bindings/skills配置保障保留。Ruff对两生产/两新增测试通过，Black对应四文件通过；唯一先前静态C901已用窄新helper修正，不重写旧core。

```text
python -B -m pytest tests/unit/infrastructure/test_component_startup_config.py tests/integration/system/test_component_startup_admin.py tests/unit/infrastructure/test_admin_audio_config.py tests/integration/agent/test_skill_configuration.py tests/integration/system/test_admin_runtime.py -q -p no:cacheprovider
```

**风险与回滚**：控制台前端尚待3C，本阶段真实route+受控资源端口不能当实际浏览器A4；实际业务初始化失败与旧资源清理失败继续由原Supervisor报告，不因HTTP200/written/restarted误称运行成功。未进行真实LLM/TTS/full-min性能/完整A5，不修改现用config/secret、不付费调用。五路径候选冻结后交Oracle gate，未提交推送；UI脚本导入backend需待本阶段明确commit ready后运行。

## 2026-11-17 Phase3C：组件启动独立面板与使用说明（顺序转录）

**待定问题**：两个开关如何加入原四面板而不串草稿、不把请求重启误说成就绪？

**背景约束**：3B已由lead许可提交 `f8f6f9263f26c9752db9691340e0b00252d191a6`；desktop-ui仅拥有UI/README/资源锁scope，不并写AI。本条由startup-spec按lead明确要求从外部UI报告第2节顺序摘录；UI经Oracle implementation1/3 PASS和lead许可精确七记录提交 `80b783ad24942828fc6787cdbc870e8967a2849e`，不夹本阶段宿主。

**调研参考**：desktop-ui查询React官方受控checkbox/不可变对象更新，沿本仓原panelDraft/select工作流与原生标签，不新控件库。

**候选方案**
1. **独立第五面板/逐叶提交**：两个严格bool checkbox，只提交相对savedConfig有变的叶；成功仅清本面板，其他草稿保留；实际runtime.state/running决定就绪文案。
2. **整面板/raw替换**：省事，但覆盖其他配置/未保存草稿并放大输入面。
3. **restarted即成功/重设计布局**：反馈简单但虚报starting/failed；换布局/控件库额外风险且无需求。

**选择**：候选1。默认true，当前面板无变化不HTTP写；failed/blocked明确检查last_error，running且true才称运行中；旧四模型面板顺序/机制不变。README说明两新键与九world默认/严格bool、M1-S整项跳过、SQL-only无回填、SAY/Sing/Call区别、隔离路径与JWT/AMAP条件、管理员邀请/RSA登录/两轮聊天后真实`/history`刷新（不是initial-history缓存）。

**选择理由/未选原因**：原工作流足够且保草稿边界；候选2会把面板外内容带入，候选3把请求当完成或无需求扩大改动。

**验证方式与实际证据**：原真实旧bundle对五面板契约红（4≠5，job `pwsh-55161cc9afab4a33`）；固定3B ready后同树Node22.23.5/npm10.9.9执行npm ci与tsc/Vite7.3.6构建，最终stub Chromium脚本exit0/pageerror0，验证隔离草稿、单叶payload、刷新、实际状态文案。该stub拦截API，仅证前端交互，不是实际A4重启。安装报告6漏洞（1moderate/5high），未auditfix。真实整份release资源check PASS；JS `index-smbr_9OT.js` 245260B SHA256 `13625ee3a225a22dbc7de46b52173a81c9abc0a8b29679110c8f2260e04daf72`；HTML423B/CR0 SHA `7fa2c373bb070829688a71049d4d937d686a6024f90e0fc7deec2effa1f7ed7e`；CSS原内容不变。README唯一Oracle机械修正/history后候选47f192…通过，同attempt1无需重build。

**风险与回滚**：原styles/布局不变不是全设备视觉验收；实际管理API与重资源恢复另验，不能借stub勾A4。可回滚UI自然提交，不删除数据；本条只有顺序决策转录，3C已提交且UI文件不属下述3D四路径。

## 2026-11-17 Phase3D：真实隔离生产链与实际控制台证据

**待定问题**：怎样证明关闭重资源后仍能走真实生命周期/鉴权/WS/历史，而不以fakeRuntime或付费供应商填补缺证？

**背景约束**：task7rev7明确四路径（新host/E2E/真console脚本/AI），父版本为3C `80b783ad24942828fc6787cdbc870e8967a2849e`。90秒有界单探针，五DIR先于server_main导入；不改生产/现用config或secret，不下载权重、不调用真实供应商，不fake RSS。只有底层模型API factory可确定化，UI脚本用新bundle/真实API不拦截。

**调研参考**：复用已有production-loopback host的run_server/ServerLifecycle接缝及真实RSA/WS/voice协议，不复制旧call宿主数百诊断路由。事前标准库AST签名/内存JSON设计核对PASS，没有项目导入或业务启动。

**候选方案**
1. **真实生产链+最底层确定性接口**：保留LLMService/PromptManager/Modules/on_delta、Runtime、SQL/RSA/Stage/Adapter/媒体，四资源构造点计数后失败，关闭时全0。
2. **旧fake Runtime/TTS/vector装配**：容易启动，却用替身抹去本需求的资源分支/持久化/owner问题。
3. **真实供应商/full-min现场benchmark**：更强证据，但当前key配置false/远程成本未授权，不能越权或用静态估值冒充。

**选择/理由**：候选1，仅验证明确允许的离线真实生产契约。host标准库顶层先隔离CONFIG/DATA/RUNTIME/RESOURCE/ASSET，生成实例随机JWT不输出、合法persona/tone/prompt、songs空表/关键词、空唱库/prepared元信息；不复制用户数据。沿真实run_server→Lifecycle→AdminShell/validator/Supervisor→ServerRuntime→shutdown。只有LLM/VLM/audio create_interface替外部生成端，TTS/Chroma/embedding/vector执行器是触发即失败的trap而非成功替身。

**未选原因**：候选2无法证明实际装配；候选3未获远端授权/资源口径未齐，不以离线fake基准或MB/百分比填空。触碰反应配置清空仅隔离fixture普通聊天接缝，不代表生产功能删减或所有能力均验。

**验证方式与分层实际结果**：
- 首真实HTTP管理员setup/login/invite生成→RSA注册登录→网络WS两轮唯一成功终态/audio空→真实文字history→全关world0/资源trap0/真实模块注册，job `pwsh-dfbeaea5abfa4db0`：`1passed in10.71s`，原run_server finally退出0。非真实模型回答。
- 媒体fixture错误分别保留：job `pwsh-d970e0bdf9cb4ae4` 23.96s误等ack而协议server_ack；`pwsh-bd4812506aac41ed` 10.44s把finalize接纳ACK当落盘完成后立即断WS，下载404。均只修测试，不产品红；后等真实语音理解/回复终态，job `pwsh-aa2c9516daa44633`：`1passed in11.72s`，原AAC字节下载200/无token与坏token401/另一真实RSA账号404，文字history对应两轮，正常关闭/exit0。
- 真实console最初RESOURCE隔离未提供bundle使生产ui_register fallback、Setup token超时；其次setup/login页面切换未等导致登录失败；均按原log与退出0记录为fixture问题。lead明确允许复制锁列HTML/JS/CSS三个约260KB代码产物，前后核size/SHA，不复制用户assets/权重；同步真实setup200→登录heading→login200后，job `pwsh-70e789dea7384efe` exit0：`ACTUAL_CONSOLE_API=PASS`，pageerror0。实际停止业务后vectortrue保存/刷新不自启→false还原；TTStrue缺配置validator拒写/原文件不变/草稿保留/放弃刷新。没有page.route，保存结果只含bool，不归档临时config/token。
- **字节边界**：11.72媒体在bundlecopy变化前（当时代码bundle硬链接版、媒体不读取UI）；真实consolegreen基于copyfile版；后仅三个新文件Black/import排序、host固定copy/model重写与E2E环境小helper的原语提取、print字符串拆分，无等待预算/执行顺序/生产行为变化。按lead允许分层复用旧场景，不声称当前全文重跑；新三文件Ruff/Black最终PASS（job `pwsh-8272b78f732345af`）。

**证据限制与风险/回滚**：实际console只停止态保存/刷新与TTS拒写，**不等同运行中apply实际restart/真资源恢复的完整A4**；正常exit0/Lifecycleclosed不等全句柄泄漏审计；媒体原字节权限+处理终态不等已独立核音频history条目（文字history已核）。知识库合法空表不等公开歌曲查询全验。独立server-handoff只读证据桥认可保真链并提出以上三披露，不是另一次运行PASS。真实freeLLM、完整模型/full-min同口径3次30秒RSS收益未验证；资产存在的stat不是可推理或性能证据，工单证据仍未齐。3D局部可提交请求review而非验收闭合；未自行GH/push/goalcomplete，最终固定HEAD全CI另由verifier执行。四路径当前候选冻结待Oracle/lead，不删除数据，回滚证据代码不影响生产配置。

## 2026-11-17 A4补验：实际运行态保存、更换owner及同库继续聊天

**待定问题**：Draft #441中真实控制台只证明停止态保存/拒写，怎样在不启用重资源、不改生产的范围内证明运行中保存真的安全重启，而不相信restarted布尔？

**背景约束**：已提交633aa32/Draft441保持原历史；task7rev9新增仅旧host/旧actualconsole/本AI三路径，独立gate/新commit，不amend。两组件及九world始终false，仅外部模型API接口确定化，真实Supervisor/Runtime/SQL/RSA/Stage不替。一个实例/一次运行态保存，总≤90s，不复跑旧停态或整个17/95集合；供应商/真资源恢复/A6/V5仍非本单元。

**调研参考**：沿已存在真实run_server及Supervisor.restart的stop→start顺序；Playwright Python v1.63官方文档查询确认expect_response配合真实点击读取响应，沿旧浏览器鉴权和已有E2E网络helper，不加依赖/endpoint平台。

**候选方案**
1. **只观察原Runtime生命周期并从真模型面板触发重启**：测试host用弱引用给实例代号，包装原initialize/shutdown并逐次await原方法，记录begin/complete；模型字段发生真实变化，重启后同库账号重新WS和HTTP历史验证。
2. **只看restarted/running或同false点保存**：无需观测，但前者不能排除未换owner，后者UI no-op根本不发HTTP，证据不成立。
3. **启用真TTS/vector或替一个成功owner**：前者需要未授权资源/供应商，后者绕掉实际重启，两者都不满足当前证据目标。

**选择/理由**：候选1。RuntimeObserver只持weakref.ref和无凭据序号/事件，不强持旧owner，不更改原Supervisor。脚本`--running-restart`模式从真实模型面板将非空模型标识改为offline-restart-verified，两组件false不动；真实API校验/写入/备份/原restart，随后同账号重新连WS并GET history。旧停态模式保留复用，不混入本次一次保存。

**未选原因**：候选2是请求状态误证或no-op；候选3或越权或成功替身自证。字段变化不证明真实供应商用了新模型；只用于启动原重启工作流。

**验证方式与实际结果**：先建立assert_running_restart，标准库AST单独抽出断言，对“响应ok/written/restarted/running都true但owner相同”输入真实失败`restarted response retained the old runtime owner`。这是**断言敏感性红灯，不是产品功能原先失败**。还要求旧/新ID均非None、不同，新增事件恰为old shutdown.begin→complete→new initialize.begin→complete，两能力false、四资源计数0。

首有界运行`pwsh-6f6ff5634e1c4a50`生产初始化成功后，脚本helper导入被已安装tests命名空间遮挡，ModuleNotFoundError: tests.e2e，发生在管理员setup/模型保存之前；finally正常退出0/closedtrue，无业务重启执行，不算产品红。lead准仅按确定文件路径importlib加载既有E2E helper，纯导入preflight `pwsh-52070b31241c4b07` PASS（文件位置/三callable/无项目业务启动、无全局path改动）。

修后唯一场景`pwsh-033880145eb8404a` exit0：`ACTUAL_CONSOLE_API=PASS; running-restart/same-account-ws-history; not full TTS/provider reenabling`。实际runtime-1→runtime-2；旧shutdown完整结束先于新initialize；TTS/Chroma/embedding/vector-executor计数全0；重启前后同一账号分别得到核心链路412/第二条回复、真实history包含二者，pageerror0；原关闭链退出0/closedtrue、父子总<90s断言完成。两源码最终Ruff/Black PASS（`pwsh-dbf8eda47fbc4306`），没有额外矩阵/全量CI，未改生产/UI/README/E2E文件。

```text
python -B scripts/check_component_startup_console.py --running-restart --output <外部无凭据结果JSON>
```

**风险与回滚/准确结论**：本单元消除了“实际运行态保存工作流、新owner和重启后聊天未验证”这一局部缺证，**不是TTS/embedding true资源恢复，更不是A4全部步骤/A6非作者README/V5真实RSS或供应商验收**。Observer事件仅成功await原方法后标complete，若原方法抛错不会补成功事件；弱引用观察不是逐句柄泄漏审计。回滚后续证据自然提交即可，不回滚已发布633或删除数据。候选冻结后交独立Oracle gate，未经明确新许可不commit/push/GH/ready/closegoal；原633全量及远端CI结果不能倒写为新补丁完整通过。
