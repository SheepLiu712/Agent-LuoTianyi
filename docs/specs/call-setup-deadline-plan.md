# #410 单一通话建立截止时间设计（待非作者审核）

> 状态：core、U1配置控制台、U2独立诊断均经独立gate及lead许可分别提交 `f3e2cb8d`、`8ab238c4`、`f5846ff6`，未push。U3安全诊断字段验证中，未完整CI/真实供应商验收。基线 `ee718b21536e410ce5e4073b068f03b9bfcd68dc`；工作树分支 `bugfix/call-setup-deadline`。
> 需求依据：[维护者评论 6910783940](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/410#issuecomment-6910783940)。设计作者 issue-scout；未获实施gate与lead提交许可前不commit/push。本文为设计及证据记录，不代表整个工单已交付。

## 用户故事

1. 作为管理员，我希望在实时音频面板只设置一个通话建立总时限，并看到实际生效值，以便调大窗口后不再被隐藏的 10 秒内层上限截断。
2. 作为拨号用户，我希望模型稍晚就绪但仍在总窗口内时可以接通；鉴权或连接已明确失败时立即收到失败，而不是无意义等到窗口用完。
3. 作为运维人员，我希望建立超时保留发生阶段，并在取消、退出时可靠回收资源，不把“客户端已见失败”误认为旧任务已释放。
4. 作为 Fun-ASR 诊断脚本使用者，我希望直连和 `--adapter` 两条诊断路径有自己的等待上限，不借用生产拨号预算或依赖 Manager。

## 验收标准

以下为已确认需求的可执行拆解，不是测试已通过记录。

| 编号 | 状态与输入 | 输出及不变量 |
| --- | --- | --- |
| AC-1 | 新请求登记，总预算 10 秒；模型在登记后第 15 秒就绪 | 约第 10 秒终止为 `SETUP_TIMEOUT`，未进入 ACTIVE；记录耗尽阶段。 |
| AC-2 | 同一模型时序，总预算 30 秒；旧 connect/session 值仍为 10 秒或更小 | 模型第 15 秒就绪并接听，呼叫进入 ACTIVE；旧键与库默认不提前截断。 |
| AC-3 | 连接先消耗 8 秒，就绪继续等待；总预算 10 秒 | 就绪阶段只能再等约 2 秒，不重新得到 10 秒；响铃仍沿用同一登记截止时间。 |
| AC-4 | 总预算 30 秒，模型第 4 秒明确鉴权失败，或连接明确拒绝 | 立即结束为真实失败，不等到第 30 秒、不自动重连；安全日志保留阶段与错误分类，不记录 token/原文。 |
| AC-5 | 同 request 重入、准备期断线恢复 | deadline 不续期，不重开供应商会话；已过期不再发起连接。 |
| AC-6 | 连接/就绪/源聊天收尾期间用户挂断或服务关闭；外部协程可能迟到 | 沿现有取消与迟到处置 owner 关闭 socket/provider/context，资源未安全释放前不释放交互占用；不吞 CancelledError。 |
| AC-7 | 管理面板无显式总预算、或管理员填入 30 并点击“修改” | 分别显示有效缺省 10、保存后有效 30；回读一致。只能写本面板字段；其他三个面板未提交草稿不丢失、不提交。 |
| AC-8 | 控制台或配置提交 0、负数、布尔、NaN、Infinity 或非数值 | 校验失败、配置不写入、运行时不重启；合法正有限秒数允许小数。 |
| AC-9 | Fun-ASR 直连、`--adapter`，分别给脚本自有连接/就绪上限 | 两路径按脚本参数限时；不读取旧生产 connect/session 键作为预算，不产生呼叫账本，不需要 Manager。 |

## 模块与架构

### 当前证据与最小修改面

- [Manager 配置/登记](<../../server/src/stage/stage_manager.py#L57-L95>) 已有唯一的 `stage_manager.call_setup_timeout`，默认 10；[登记逻辑](<../../server/src/stage/stage_manager.py#L736-L785>) 将原 deadline 放进 claim/ownership。**不需要新建第二个预算配置，也不重写登记算法**。
- [CallStage 建立](<../../server/src/stage/call/call_stage.py#L472-L508>) 目前依次创建 context、供应商会话、结束源聊天、进入 RINGING；[_await_setup](<../../server/src/stage/call/call_stage.py#L2012-L2053>) 已按原截止时间计算余额并拥有取消/迟到清理。
- [Agent.open_omni_session](<../../server/src/agent/facade.py#L65-L77>) → [OmniSessionFactory.open](<../../server/src/domain/call/omni.py#L113-L114>) → [Qwen provider](<../../server/src/infrastructure/models/realtime_speech/omni.py#L48-L75>) 是预算尚未下传的接缝。
- [Qwen 启动](<../../server/src/infrastructure/models/realtime_speech/omni.py#L101-L140>) 仍使用独立 connect/session 值；[配置类](<../../server/src/infrastructure/models/realtime_speech/config.py#L18-L94>) 和 [控制台](<../../server/res/admin_ui/src/main.tsx#L1679-L1729>) 仍暴露旧键。
- [配置视图/局部合并](<../../server/src/infrastructure/config/model_editor.py#L7-L87>)、[管理 apply](<../../server/src/web/admin/admin_interface.py#L305-L338>) 需增加单一叶子字段的读取、校验与合并；不得覆盖整份 stage_manager。

```text
登记请求（Manager）                         诊断脚本（无 Manager）
  原 deadline = monotonic + 总时限             脚本参数 connect / ready 上限
       │                                            │
  CallStage ownership                              Fun-ASR factory/session
       │
  原 _await_setup / _watch_setup 继续总控
       ├─ context
       ├─ Agent.open_omni_session
       │     └─ OmniSessionFactory.open
       │            ├─ connect：此刻 remaining
       │            └─ session_ready：连接后重新 remaining
       ├─ source handoff（#411 独立策略）
       └─ RINGING：原 deadline，不续期
```

### 最小传递方案（推荐，待审）

**预算仍只有 `remaining_setup_time: Callable[[], float]`；D2 窄核补充已由 lead 选定同步 `on_session_created(session)`，在首个 await 前把唯一清理所有权交给既有 Stage，不增加通用 owner/clock 框架。**

- CallStage 以原 `ownership.setup_deadline` 和现有注入的 `_monotonic` 形成具名余额方法。方法计算 `deadline - monotonic()`；余额 `<=0` 抛 `asyncio.TimeoutError`（Python 3.10），不悄悄返回新窗口。
- `Agent.open_omni_session(context, call_id, *, remaining_setup_time, on_session_created)` 转交；`OmniSessionFactory.open(call_id, instructions, *, remaining_setup_time, on_session_created)` 声明同一 keyword；具体 Factory/session 只在初始化 await 期间使用，**成功后不保存 Stage 或回调**。现有 fake factories/测试装配同步更新，独立调用者显式持有本地 owner 并 finally close，不提供隐式无 owner 兜底或 `**kwargs` 吞参数。
- 该回调只表达剩余时间，不提供 Stage/Manager 查找、配置读取、状态修改或跨调用缓存能力；基础设施不导入 Stage。余额在构造库connect对象前求值；若外层先发现耗尽，原 `_await_setup` 关闭尚未await的Agent coroutine，Agent async函数未执行，因此未建provider/socket，不产生未await警告。不得把connect/resource分配提到该检查之前。
- Qwen 连接前调用一次余额，显式传 `connect(..., open_timeout=remaining)`；移除套在连接外的独立旧 `wait_for(connect, config.connect_timeout_seconds)`。一次 `await connect`，不用 `async for connect`，因此不启用库自动重连/退避。
- 连接完成后重新调用余额，以其包裹 `session.update` 发送及等待 `session.updated` 的整个就绪阶段（不能只限最后 `_ready.wait()` 而让 send 阶段另有无界等待）。使用 Python 3.10 的 `asyncio.wait_for`，而非 3.11 才有的 `asyncio.timeout_at`。
- CallStage 原 `_await_setup` 仍包裹整个 provider open，保持绝对总 deadline 的最终约束；库 connect timer 和 ready timer 只使用当时余额，不重新配置、更不续期。接通前响铃仍由原 watcher 控制。
- Phase 诊断保持在失败的所有者：provider 在 connect/ready 的失败或取消边界记录 `call_id / phase / outcome / 安全错误码`；若取消发生时已无余额，可记录 `setup_timeout`，若尚有余额记录 `cancelled`，不把所有 CancelledError 当超时。CallStage 仍拥有 `context/source_handoff/ringing` 耗尽阶段及最终 `SETUP_TIMEOUT`，两层用同一 call_id 关联；无需为观测再加 phase setter 回调或通用状态机。
- 调用者清点：生产仅CallStage→Agent→QwenFactory；直接测试入口还包括 [test_call_omni.py](<../../server/tests/integration/stage/test_call_omni.py>) 的factory.open、[test_call_prompt.py:49、100](<../../server/tests/integration/agent/test_call_prompt.py#L49-L100>) 的Sessions/Agent，以及 [call_session支持](<../../server/tests/support/call_session.py#L14-L25>) / [其open_session闭包](<../../server/tests/support/call_session.py#L76-L96>)、[网络E2E厂](<../../server/tests/support/call_network_success_server.py#L70-L85>)。共享配置还被 [realtime取消诊断](<../../server/scripts/diagnose_realtime_cancel_timing.py#L156>) 读取，移旧键校验须保留该独立诊断显式限时，不能只改Fun-ASR路径。

**备选（不推荐）**：传 `setup_deadline` 与另一个 clock 参数。它会迫使三个接缝同时理解时钟域，还可能测试/生产使用不同 clock；现有 Stage 已有权威 monotonic，单一余额回调更小。

**备选（不推荐）**：只把 `open_timeout=None` 并删除全部内层限时。外层能约束生产等待，但缺少维护者要求的连接/就绪明确余额语义，且 standalone factory 容易误用为无界；不采用。

### Python / websockets 官方依据与版本边界

本机只读核对：Python **3.10.21**，websockets **16.1.1**；[pyproject](<../../server/pyproject.toml#L10-L42>) 要求 Python `>=3.10,<3.11`、websockets `>=14`。Context7 查到的 stable 文档已覆盖较新 17.x，不据此引入 16.1.1 没有的新参数；本方案只用 `await connect`、`open_timeout`、`close_timeout`、`additional_headers`。

- [websockets asyncio client](https://websockets.readthedocs.io/en/stable/reference/asyncio/client.html)：`open_timeout` 默认 10，显式浮点值为开连接上限，None 关闭限时；单次 await 与自动重连 iterator 是不同入口。
- [websockets 16.0 官方文档](https://github.com/python-websockets/websockets/blob/16.0/docs/reference/asyncio/client.md)：`process_exception` 的重连分类只作用于 `async for ... in connect(...)`；本设计不使用该入口，因此鉴权/拒连失败直接传播。
- [Python asyncio wait_for](https://docs.python.org/3.10/library/asyncio-task.html#asyncio.wait_for)：超时会取消并等待被取消任务结束，因此墙钟总返回可晚于 timeout；Python 3.10 使用 `asyncio.TimeoutError`，不能套用 3.11 的异常/上下文管理器细节。
- [Python asyncio wait](https://docs.python.org/3.10/library/asyncio-task.html#asyncio.wait)：timeout 本身不取消 pending；现有 `_await_setup` 显式 cancel + owned dispose 不可删掉。

以上 API 事实已通过 Context7 官方来源核对；尚未运行实际 socket 取消实验，不宣称库在任意取消竞态都替本项目完成资源所有权。

## 配置、管理控制台与兼容迁移

### 唯一新界面字段

配置位置不变：`stage_manager.call_setup_timeout`，缺省 10，正有限数字且排除 bool。Manager 自有解析保持权威；配置校验与编辑读取共享这一口径，避免 UI 默认和运行时默认漂移。

控制台“实时音频模型配置”面板：

```text
实时音频模型配置
  接口：模型 / Key引用 / endpoint / workspace
  [启用通话] [启用实时音频模型]
  通话建立总时限（秒）  [ 10 ]
  说明：连接、会话就绪、源聊天切换及响铃共用；明确失败立即结束。
  关闭超时 / 清理超时 / 队列容量 / 帧上限（既有字段保留）
  [修改] [放弃草稿]
```

- 建议模型配置视图只新增 `call_setup_timeout: number` 这一叶子，不把整份 `stage_manager` 暴露给模型面板。
- `build_llm_config_view` 返回**有效值**；`apply_llm_config_draft` 仅当 payload 包含该叶子时写到现有 `next_config['stage_manager']['call_setup_timeout']`，保留 stage/termination 等兄弟节点。
- 实时面板 select 纳入 `call_transport` 与这个叶子，其他三面板不纳入；[当前局部草稿实现](<../../server/res/admin_ui/src/main.tsx#L1521-L1645>) 的提交串行、只撤当前草稿、保存后保留其他草稿均不重构。
- [ConfigStore](<../../server/src/infrastructure/config/store.py#L31-L47>) 的原子写/备份、整份校验和按需 restart 保持；新叶子非法时不能写盘。真实演示仅用隔离配置/实例，不操作用户当前配置或 Key。

### 旧 connect/session 键（推荐迁移策略）

1. 旧配置文件无需用户先改、无需启动时迁移写盘；旧键暂允许存在，但**生产 Qwen 建立不再使用它们作为时限，也不以旧键非法值阻断生产启动**。保留原始值不等于继续生效。
2. 控制台不再显示/编辑两个旧键；返回有效总预算，显示一次无秘密弃用说明，避免用户继续调一个无效字段。不将旧 connect/session 的 max 或 sum 映射成总预算，缺省总预算仍是既有 10，显式既有总预算仍保持。
3. 共享 realtime config 中的连接/就绪预算从“生产配置”迁到诊断参数所有权；可在诊断内部构造专用限时对象，不为保留旧 JSON 键而继续全局校验/消费。关闭/清理 timeout 不属于旧建立预算，保留其既有语义。
4. 正常管理保存会按用户明确提交的叶子更新配置；不偷偷删除旧键、其他面板字段或用户设置。旧键删除/长期拒绝的破坏性迁移不在本单元实施。

## 取消、迟到资源与 #411 边界

### D2 窄核所有权表（lead 已选定，实施约束）

| 时点/结果 | 唯一清理 owner | 处理 |
| --- | --- | --- |
| remaining<=0 或原初始化 coroutine 未开始即取消 | 尚无 session | 先检查余额/取消，再构造；原 `_await_setup` close 未await coroutine，不能分配网络资源。 |
| Factory 构造无网络 session、同步 callback 尚未成功返回 | Factory | callback 若在未登记前拒绝，Factory只清理这个未交出的句柄；Stage回调先校验再赋值，赋值后不抛，避免双持有。 |
| callback 正常返回 | Stage PREPARING 私有slot | callback仅登记一次；Factory成功/失败/取消均不close，不缓存Stage；明确失败立即传播，先锁原原因/终态再异步清理。 |
| 外层cancel/timeout、provider抑制取消后迟到成功 | Stage | `_await_setup`保留cancel/join，但provider不再传cleanup lambda；初始化退出后termination统一close已登记同句柄，return必须is该句柄，不得覆盖/复活。context原late cleanup保持。 |
| termination_requested后本初始化仍试图发布 | Stage | 前置remaining检查通常阻止构造；若合法发布仍在受管初始化内，登记必须无await且成功，然后下一余额/取消检查抛CancelledError。Factory不得后台脱离初始化发布；termination先join初始化再关slot。 |
| Stage关闭成功/失败 | Stage单个close task | 成功清slot；失败保留slot及同一失败close task，设置_resource_error，resources_released=false，Manager继续保留占用；重复cleanup只能等待同一task，不再次调用close。不靠Qwen幂等容忍任意双close。 |

明确鉴权/拒连在发生时立即抛出且Stage锁定SYSTEM_FAILURE；Factory不先await close，旧watcher不能因关闭跨deadline重分类。阶段诊断读取remaining若抛TimeoutError，只在独立日志小try中记0，不覆盖原CancelledError/cause。清理失败独立记录，不能掩盖原建立原因。只修本次provider建立路径，不重写全部旧异常。

[CallStage._dispose_late_setup](<../../server/src/stage/call/call_stage.py#L2036-L2050>) 对context仍维持原迟到处置；provider因已早交owner不再经第二cleanup入口。不得为了准时返回提前释放仍在关闭中的资源。
- 接收明确 provider error 的 `_ready` 事件会结束等待并 `_check_open` 抛错误，不把“_ready 被唤醒”误认为“成功就绪”。诊断原因只记录供应商 code/type、HTTP status 等安全字段，不保存带 Key 的 URL/header。
- #411 owner 已反馈拟复用 `StageTerminationResult`，ChatStage 分 tasks_stopped / maintenance / context_closed，只有已确认安全清理时 `resources_released=true`；Manager 阻断 cleanup_error 或未释放，保留维护失败日志。该方案仍待其独立 gate，**#410 不修改这个结果契约或其判断条件**。
- 本项不后台化维护、不调整其 90 秒期限、不改变建立顺序；源维护耗时仍从同一个建立总预算扣除，不保证每次维护失败都能在预算内继续接通。

## Fun-ASR 独立诊断路径

[diagnose_fun_asr.py](<../../server/scripts/diagnose_fun_asr.py>) 的U2改动仅脚本与入口测试，生产配置/adapter实现不改：

- 脚本明确提供 `--connect-timeout-seconds` 与 `--session-timeout-seconds`，缺省各 10，正有限数字；这是**诊断操作参数**而非管理员生产配置。
- 直连将第一项交库 `open_timeout`，第二项约束 run-task/等待 task-started；`--adapter` 使用完全相同的脚本参数显式构造 Fun-ASR 的诊断限时，再调用现有厂商 session。
- provider 的 endpoint/model/key 等连接材料仍从既有配置解析，不记录 Key；不从 Manager 获得 deadline，不创建呼叫账本，不自动重放采集写入。
- 验证不触发线上 ASR：参数解析/adapter 装配回归用公开脚本main入口及假外部 socket；有效红灯为旧非法配置在factory解析阻断（1failed/.65s），脚本覆盖后1passed/.08s；最终两路径连接/就绪限时、取消清理、CLI/main非法值及既有Fun-ASR定向回归见U2gate归档。真实供应商诊断保留为明确external/手动证据，不能用offline passed代表线上识别通过。

## 验证计划、预算与实施顺序

### 已确认测试接缝

lead 已确认：**Manager 公开接入 → 真实 Agent → provider factory**，仅外部 connector/socket 与时间受控。先一个行为测试，观察 30 秒预算不应被 10 秒旧键/库默认截断、10 秒应真实超时；不以新参数缺失的 TypeError 作为红证据。

- 使用已有 Manager `monotonic` 注入与真实 asyncio loop timer；测试局部推进 loop.time/定时器，不向生产新增“测试时钟服务”、不 mock Agent/Manager/_await_setup。
- 网络由 connector/socket 响应已知脚本控制：连接成功/第15秒 session.updated/第4秒 HTTP401或 protocol error。断言公开呼叫状态/终态及可查账本，不只断言调用次数或 timeout 参数。
- 如无法在现有测试支持下可靠控制 timer，先交明确失败点和最小试验，不偷偷改运行接口来适配测试。

### 非重复证据分工

| 证据 | 本 lane 所有者/最低范围 | 不能外推 |
| --- | --- | --- |
| 首个 10/30 秒红灯 | issue-scout：新增一个参数化集成行为测试，旧代码30秒场景应在10秒提前失败，10秒场景仍超时 | 非真实网络/性能；不等于完整 #410 验收 |
| 连接后余额与第4秒明确错误 | 实施后同一接缝各加必要行为；错误原始 code/phase 不丢 | 不模拟内核固定21秒上限 |
| 响铃/重连/取消/迟到释放 | 复用既有 handoff/Manager 测试；仅补新传递接缝缺失的取消覆盖 | #411 安全结果 gate 属另一 lane |
| 配置/局部提交 | 既有 admin audio config 与 model-panels 构建浏览器脚本，补总预算叶子保留兄弟/其他草稿 | 构建不等于运行时重启成功 |
| Fun-ASR 两路径 | 脚本入口/真实适配器 + 假外部 WS，无付费请求 | 不声称供应商线上识别已验收 |
| 最终 CI | ci-verifier 按 lead 调度，版本对齐后复刻现行工作流 | 本地结果不替代远端 CI |

建议原子顺序：设计+首个红灯 → 非作者 design gate + #411 契约确认 → 预算下传和 provider 最小实现 → 接缝绿灯/既有生命周期回归 → 控制台/旧键兼容/诊断独立参数 → 审核与完整本地闸门。**D2已明确放行provider核心进入绿灯；当前单元不包含UI/旧键兼容/Fun-ASR实现，不自动commit/push。**

### 风险与回滚

- 新参数跨 Agent/Factory 接缝，遗漏既有 fake/诊断调用会以 TypeError 暴露；所有调用者一次性清点，不能靠宽松 kwargs 掩盖遗漏。
- 共享配置迁移可能影响 Fun-ASR/旧 Aliyun 适配器：先将诊断预算显式化再移生产旧字段消费者；不把 standalone 诊断变成无界等待。
- 库 timeout 不是成功保证，操作系统拒绝/鉴权/断线仍立即失败；不为“撑满30秒”吞错或重连。
- API 回滚为本单元代码回退；不删除用户配置/密钥/数据库，不改变原始 `stage_manager.call_setup_timeout` 的默认；用户明确保存的新总预算仍可被旧 Manager 读取。旧键保留所以无需逆迁移。

## 当前执行记录

- 已核对分支/HEAD/依赖版本与官方 API；HEAD仍固定SHA。D2后仅4个授权生产文件改provider预算/owner接缝，Manager、UI、配置和脚本未改。
- 新增 [test_call_setup_deadline.py](<../../server/tests/integration/stage/test_call_setup_deadline.py>) 一个参数化行为测试：现有 Manager公开入口→真实Context/Agent/Qwen，局部推进loop.time（不替换sleep/wait_for），第10.25虚拟秒检查；30秒路径之后预定第15秒模型就绪并验证ACTIVE。只替换外部WS、空存储端口与时钟，不真实等待30秒。
- 干净红基线（job `pwsh-7b6420a064f44074`，已收集）：**1 failed, 1 passed, 1 warning in 0.61s**；10秒场景的公开终态与可查账本确为SETUP_TIMEOUT；30秒场景精确失败于“30秒总预算不能被遗留10秒会话上限提前终止”的业务断言。当前只能证明旧session ready限时提前截断；假connector立即连上，**尚不能证明真实库连接默认已被测试覆盖**。
- 首跑曾因测试finally错误调用不存在的Agent.stop产生夹具错误，已删该错误清理调用；该次2 failed不计入有效红证据。Manager/stage真实收尾保留，生产未改。随后仅调整import排序后复跑（job `pwsh-e5100541cf1e4bd7`）仍1 failed,1 passed in0.62s，同一业务断言；最终把socket.closed清理断言移进finally使失败路径也检查回收，该断言移动未重跑业务，不扩报原结果。Ruff/Black对最终新增测试通过，git diff --check通过。
- warning为当前环境pydub未发现ffmpeg；本测试不处理音频，未因它跳过。未启动业务服务、真实ASR、管理配置写入或完整CI；4秒鉴权、连接余额、实际控制台与诊断两路径仍列后续待测，不冒称已覆盖。
- 实施核心绿灯：首个10/30场景2 passed in0.22s（job `pwsh-ca345c330bc549ed`）；既有会话、角色prompt、handoff及公开Manager四文件73 passed in5.88s（job `pwsh-258405949ef44995`）。后补4项门控合并最终六场景6 passed in0.73s（job `pwsh-114822102f554208`）：第4秒auth立即真实终态且close阻塞跨deadline不改原因、close抛错资源不释放/Manager拒绝关闭、connect耗15秒后update send仍只用原30余量、取消抑制late socket关闭一次。均已收集；这些是离线受控WS，不是实际厂商/OS连接实验。
- 门控编写中两次auth失败分别因测试写死cause层数及未等close_started的测试竞态，均仅修测试，未作为产品红证据；最终用真实关闭门控收敛。全量Black对既有test_call_omni仍会指出3处本次未改的基线格式（测试不在仓库Black默认范围）；新增helper按Black格式，4生产文件Ruff/Black和diff-check通过，最终文件验证在冻结归档另列。
- D2核心实施gate attempt1/3 PASS并按lead许可提交 `f3e2cb8d27dd5b236138aa8bd805060b050a4d0e`，未push。U1配置/控制台已实施：新红2 failed/.47s→77 passed/3.47s，单leaf/default/非法不写不重启、旧非法键Qwen生产忽略而独立adapter严格。4生产Ruff/Black通过。
- U1独占时窗本tree显式Node22.23.5 npmci69packages7s+tsc/vite成功；真实新构建Chromium脚本exit0，验证default10、空不提交、30.5保存刷新、放弃仅本面板及#435其他草稿保留。JS变为index-BUblm2wq.js，size243936，SHA256 ed15f72493eaeb7bb2b1e0bfa025878267104453dd49713150ffc08030a1b815，HTML生成后仅规范混合换行至LF，最终size423、SHA256 282cec880bde7c0767ba3e84257296d457031a48fd7e733bc5b6ee2d2dbbc185同步发布清单；DOM语义和引用JS/CSS未变，未重复浏览器验收。
- 上述浏览器只用隔离模拟API与真实构建产物，不是实际生产重启验收。U2独立诊断已24passed/.39s及5scope独立commit；U3最小caplog有效red缺outcome1failed/1.06s→14passed/.34s，新增固定outcome及有限provider_code/严格HTTPstatus，不输出自由文本/URL/header/body。测试只认证新增phase日志，不泛称既有异常链全部脱敏；未改变原异常/CancelledError/owner预算。U3尚待gate/commit，整个#410仍待完整CI和交付，不关闭工单。
