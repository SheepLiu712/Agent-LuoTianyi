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
