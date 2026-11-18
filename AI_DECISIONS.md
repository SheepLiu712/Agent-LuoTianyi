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

## 2026-11-17 #411：将聊天停止安全事实与结束维护结果分离（设计 gate 已通过，实施 gate 待定）

**待定问题**：维护失败不应独自阻断通话，但现有 `finalization_error` 混合停止任务与维护失败，`resources_released` 又只依据关闭上下文，不能只删除 Manager 的拒绝条件。

**背景约束**：
- 固定工作树 `.slim/worktrees/issue-411`，分支 `bugfix/call-handoff-maintenance`，基线 `ee718b21536e410ce5e4073b068f03b9bfcd68dc`。初始仅授权写 `server/src/stage`、相关 `server/tests` 和本文；后续精确扩域见下文；未获实现 gate 前不提交，当前不推送或写 GitHub。
- 验收依据：[维护者锁定评论](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/411#issuecomment-6910255769)。任务已停止、上下文已关闭、资源释放安全确定后，纯维护失败继续切换；清理失败或安全未确认仍拒绝。
- 不调整 90 秒结束维护、通话建立预算、建立步骤或供应商审核语义；不把结束维护后台化；保留 #427 embedding 准备/跳过和并行生成、阈值维护后台队列。
- 非作者设计 gate 通过前只写测试/本文，不改生产代码。

**调研参考**：
- Python/CPython asyncio [任务文档](https://docs.python.org/3.10/library/asyncio-task.html)：`wait_for` 等待取消完成；`shield` 保留被拥有任务，不把等待者取消当作终止已完成；`gather(return_exceptions=True)` 等待所有任务，但异常仅成为结果，不能据正常返回推断清理成功。通过 Context7 复核，实际解释器为 Python 3.10.21。
- 本项目 `StageLifetime.start/terminate` 与 Manager 已持有初始化/终止任务，复用现有所有权，不建立另一个生命周期框架。

**候选方案**
1. **仅删除 Manager 的 finalization_error 条件**：改动最少，但停止阶段异常也被放行，现有 context.close 成功不足以证明安全，否决。
2. **复用现有结果、分三段记录事实**：在 ChatStage 内分离停止、维护、关闭。将停止/关闭错误归 `cleanup_error`，只将维护错误归 `finalization_error`；`resources_released` 成为完整安全释放事实。Manager 对纯维护失败放行。选择此方案。
3. **扩展 domain 结果枚举/每阶段字段**：可表达更多细节，但超出授权写域并涉及 CallStage、其他 ManagedStage；现有字段已能表达本工单最小需求，暂不采用。

**选择**：候选 2。Oracle D1 非作者设计 gate attempt 1/3 通过，lead 已放行实施；尚未实现 gate，不提交或推送。初始化只允许 `StageStartAborted` 直接 `__cause__` 为 `CancelledError` 的明确包装；`StageStartAborted → OSError → CancelledError` 不放行。

**三段安全事实与最小改动**：
1. **停止段**：初始 `tasks_stopped=False`；取消并等待初始化及受管前台、阈值后台、提醒任务，成功完成后才置 True。停止阶段异常归 `cleanup_error`，不运行结束维护。对本次 join 的非取消异常应在等待所有兄弟退出后判为不安全，不能因 `return_exceptions=True` 遗失；正常取消不是清理错误。现有初始化包装会以 `StageStartAborted` 包裹取消，需要核对 cause，不能白名单放行全部初始化失败。优先局限在 ChatStage，不改变 CallStage 的取消规则。
2. **维护段**：仅停止安全后进入，继续原 `InteractionEnding`→Agent→唯一 `CognitiveMaintenance` 和原 `wait_for`；维护失败/超时保留 `finalization_error`、失败日志和 error span。超时必须实际取消并等待维护退出，不当作成功、不推进未提交进度。
3. **关闭段**：仅停止安全时关闭 context，防止仍在运行的任务使用已关闭上下文；关闭失败归 `cleanup_error`。只有停止事实成立且 context 关闭成功（或无 context）且无清理错误，才 `resources_released=True`，ChatStage/StageLifetime 才为 TERMINATED。
4. **Manager**：`_finish_source_interaction` 只在 `cleanup_error` 或 `not resources_released` 时拒绝。`_finish_stage` 原失败日志保留，安全释放后可移除 source 注册；纯维护失败不是维护成功。`_finish_call_ownership` 原资源守卫不变。

**所有权与取消**：
- `ChatStage.terminate` 使用同一个 `_lifetime.termination`，重复调用返回同一结果，不重新运行停止/close，也不能从“后续任务退出”推测先前失败结果可升级为安全。
- 停止失败时保留 TERMINATING、Manager `_managed`/`_termination_results`，call transition 不转为 CALL。`_finish_call_ownership` 再次读取同一不安全结果并拒绝释放；后续聊天/直接通话/用户数据 reset 不应取得有效所有权。
- 现有 `StageManager.close` 对不安全结果/遗留 managed/释放异常抛 `StageShutdownFailed`；不是必须自愈重试，重复 close 也不能虚假成功。明确保留此失败模式。
- 不捕获并转成功 `CancelledError`，不改变 shield、owned termination、CallStage 的 setup timeout、挂断先发送终态与后续 scope release。
- 私有 `_stop_work(require_safe_cleanup=False)` 默认保留断线既有策略；仅 `_stop_termination_work` 传 True 启用本次取消/join 收尾异常安全门，避免把 #411 扩成断线策略修改。对比回归覆盖同一 CancelDelivery OSError 在断线保留旧 CHAT 可重连、在终止保留不安全 CALL_TRANSITION。

**选择理由**：复用窄结果接口和既有拥有任务，安全判断集中于真正知道受管任务/上下文的 ChatStage；Manager 不解析错误字符串或供应商类型。

**未选原因**：
- 候选 1：会把停止失败误分成可忽略的维护故障，存在双交互和后台任务遗留风险。
- 候选 3：为本次单一行为扩散 domain/CallStage 的接口改动，没有必要且不在本 lane 写域。

**验证方式与证据路径**：
- 外部确认来源为维护者锁定评论，不以旧测试或 mock 返回值确认正确预期。
- 公开接缝为 `WebSocketAdapter` 打开真实 ChatStage→`StageManager.prepare_call_transition/try_to_get_stage`→真实 CallStage→显式 `call.start()`；新用例不 fake `StageTerminationResult`。
- 修改前现有旧维护必败用例和正常关闭用例：`2 passed, 2 warnings in 0.98s`（2026-11-17），仅生命周期基线，不是新需求通过。
- 首次只导入 stage 触发已有 SqlCallSessionRepository 循环 import；按 conftest 顺序先加载 `support.agent_runtime_support` 后正常。未改依赖/用户配置。每次运行将 `src.__path__` 限为本 lane/server/src，打印 `inspect.getfile(ChatStage/StageManager/CallStage)` 并 assert 路径在本 lane，避免 editable 回退主树。
- 红灯：将旧“维护失败必然通话失败”用例改为 `test_termination_maintenance_failure_does_not_fail_safely_released_call`，显式等待 call.start，要求 RINGING、账本不为 FAILED/SYSTEM_FAILURE、维护错误仍存在：`1 failed, 2 warnings in 0.93s`，实际失败链 `Manager._finish_source_interaction → StageHandoffFailed → StageInitializationFailed`。再运行 foreground/threshold 等待退出与 CancelDelivery 清理端口 OSError 三例：`3 failed, 43 deselected, 2 warnings in 1.47s`；旧实现丢弃清理异常后仍 `resources_released=True`，与安全验收相反。
- 安全网：真实前台/阈值任务取消 finally 用 Event 卡住，退出前不可 RINGING/不可释放 transition；停止阶段抛异常与 context.close 失败必须拒绝，重复 terminate/close 保持失败 owner；用户取消、服务关闭、setup timeout 和 provider 故障不放宽。
- 维护证据：`test_handoff_maintenance_safety.py` 使用真实 Agent、InteractionEndingHandler、CognitiveMaintenanceActionHandler、CognitiveMaintenanceSkill、AgentMemory/MemoryWriter、InteractionContext、SQLite ConversationService；仅外部模型/音频端口受控。分别注入 RuntimeError 与现有 LLMContentInspectionError，断言维护失败日志/error spans、未提交进度仍为 None、真实 context 已关，call RINGING/账本无失败，并通过真实 CallAnswerRequestedHandler/AnswerCallHandler 达到 ACTIVE 和持久账本 ACTIVE。单独 RecordingAgent 测试不充当清理或进度安全证明。
- 定向回归最小集合：`test_call_handoff.py`、`test_chat_stage.py`、`test_manager_lifecycle.py`；补现有认知维护/embedding 跳过、并行生成用例。全量离线门禁由 ci-verifier 统一调度，未执行前不声称通过。
- 运行命令（工作目录为本 lane 的 server）：
  ```powershell
  & 'C:\Users\Administrator\.conda\envs\agent\python.exe' -c "import sys,pathlib,inspect; root=pathlib.Path.cwd(); sys.path.insert(0,str(root)); sys.path.insert(0,str(root/'tests')); import src; src.__path__=[str(root/'src')]; import support.agent_runtime_support; from src.stage.chat.chat_stage import ChatStage; from src.stage.stage_manager import StageManager; from src.stage.call.call_stage import CallStage; classes=(ChatStage,StageManager,CallStage); [(print(cls.__name__+'='+inspect.getfile(cls),flush=True)) for cls in classes]; assert all(pathlib.Path(inspect.getfile(cls)).is_relative_to(root/'src') for cls in classes); import pytest; raise SystemExit(pytest.main(['tests/integration/stage/test_call_handoff.py::test_termination_maintenance_failure_does_not_fail_safely_released_call','-q','--tb=short']))"
  ```

**真实 Agent 可观察性缺口与精确扩域（已授权修复，待实现 gate）**：`agent/processing/invocation.py:57–72` 在取消时等待 worker，但若 worker 的取消清理抛异常，只记录异常后重抛原 CancelledError；Stage 的 gather 无法从 `task.cancelled()` 识别此内部清理失败。当时本 lane 授权写域不含 Agent，故先暂停且未擅自扩改。真实 Agent + 真实 ChatStage/Manager/CallStage 的取消 finally OSError 探针 `test_real_agent_cancel_cleanup_failure_does_not_release_handoff` 已实跑：`1 failed, 2 warnings in 1.00s`，OSError 原因仍在日志，但 Stage 返回 `finalization_error=None, cleanup_error=None, resources_released=True`。lead/Oracle 已收到，Oracle 确认必须补窄可观察信号，当时暂停 runtime 继续改动/不提交，等待明确最小载体与精确授权；随后按下述授权完成局部实现。之前最终收窄版 160 passed/12.91s、四文件 ruff/black/diff-check 通过不含当时新增的红例，不代表最终候选验证；最终结果见下文。独立 Python 3.10 探针确认 `gather(return_exceptions=True)` 与之后 `task.result()` 均丢失 CancelledError 的 cause，不能靠异常临时属性/因果链或日志解析补安全判据。当时提出复用单次 CancellationToken 只读清理错误类型信号与独立清理结果载体两候选；lead/Oracle 选择前者并由 task-6 revision 3 精确授权 `domain/agent/handle_input.py` + `agent/processing/invocation.py`。只记录首个异常类型名，校验为标识符、不保存异常对象/自由文本或 traceback，不改取消 reason/首次原因/只读属性；正常取消、取消到达前已 done 的业务失败不标。Stage 停止前捕获本次 active request/foreground/threshold 执行对应的 token，所有任务 join 后检查，已被 finally 清掉的引用不影响检查；结束维护局部 request/execution token 在维护超时后也检查，清理失败不关 context、不释放 owner。

随后真实结束维护 execution 超时用例又取得 `1 failed, 125 passed in 2.40s`：`cognitive_maintenance/_parallel.py` 的 sibling drain 同样吞了外部模型取消 finally OSError，且遗留 `_GatheringFuture exception was never retrieved`。lead 在 task-6 revision 5 精确授权 `_parallel.py` 和 `skill.py`/`_call.py` 两个现有调用点传入同一 `invocation.cancellation`。保留原并行、shield、complete_owned、全部 siblings join；只对本次 active 且实际 cancel 成功的 child 的非取消收尾异常，在完整 join 后写已有 token，原 gather 通过 done callback 检索异常。此载体也覆盖一个分支先业务失败→取消兄弟→兄弟清理失败（无需外层取消）的近邻，普通业务失败仍不是清理错误。不改 shared complete_owned，不建立新框架/全局 registry。两条真实红均保留为长期测试，不换浅 mock 取绿。

**最终候选验证（2026-11-17，未提交/待实现 gate）**：
- 使用上文同一受控 import/inspect runner，最终 13 个 pytest 入口：`297 passed, 2 warnings in 17.39s`，exit 0。目标依次为 `integration/stage/test_call_handoff.py`、`test_chat_stage.py`、`test_manager_lifecycle.py`、`test_handoff_maintenance_safety.py`、`test_call_stage.py`、`test_stage_finalization.py`、`test_call_omni.py::test_provider_failure_ends_call_and_releases_session`、`unit/agent/test_cognitive_maintenance.py`、`integration/agent/test_call_threshold_maintenance.py`、`unit/utils/test_embedding_timeouts.py`、`unit/domain/test_handle_input_contract.py`、`unit/agent/test_cancellation_cleanup.py`、`unit/agent/test_interruptibility.py`；均以 `server/tests/` 为前缀。
- 真实 Agent 取消 finally 红例 + 全部 token 契约先局部 `109 passed, 2 warnings in 0.51s`。新 token 契约实现前为 `5 failed, 103 deselected in 0.89s`（字段/方法不存在）。
- 维护纯失败、LLMContentInspectionError 不假成功；真实 SQLite 进度不推进，error 日志/span 与终止总 span error 保留；RINGING 后真实接听处理器使持久账本 ACTIVE。停止清理异常、初始化清理异常、关闭失败、结束维护 handler/execution timeout 清理异常与生成分支失败导致 sibling 清理异常都拒绝；正常取消和业务先 done 的异常不误标。
- ruff 0.14.10 对 7 个改动生产文件 + 4 个改动/新增测试文件通过；black 26.5.1 对 7 个改动生产文件 + 新安全/Agent 测试/原 handoff 测试 10 文件检查通过；`git diff --check` exit 0。未重排未改动的 domain 契约测试全文格式。
- Python 3.10.21；`inspect.getfile` 打印并 assert ChatStage、StageManager、CallStage、invocation、CancellationToken 均来自本 issue-411/server/src。启动前仅 runner 内调整 sys.path/src.__path__，未安装 editable/改全局环境。
- 2 个 pytest 提示是预加载 support 后 anyio/pytest_asyncio 已导入，无法重写断言；另 pydub 提示未在当前 PATH 找到 ffmpeg。上述定向用例没有实际音频编解码，无真实供应商/设备验收。全量离线 CI 仍由 ci-verifier 统一调度，尚未运行，不等同已过 CI。
- 清理失败 owner 仍为 CALL_TRANSITION 或原 CHAT，重复 terminate 返回同一不安全结果，重复 close 拒绝；不迁移持久数据、不撤销 #427。不承诺慢拨号已经解决。

**风险与回滚**：停止结果的错误分类、取消任务 finally 失败、初始化被取消的 cause、Manager 的失败 scope release 都需独立 gate 核查。`resources_released=False` 将继续阻止新交互与关闭依赖，不能自作主张清理或放弃 owner。最终运行修改为已授权的 Stage 与单次清理事实传递链，后续可单独 revert 本单元，恢复旧准入策略；不迁移持久数据、不改模型配置，不撤销 #427。仅放行纯维护错误仍可能耗尽既有 10 秒通话预算，不承诺解决慢拨号。无真实供应商、生产配置、实体设备验证。
