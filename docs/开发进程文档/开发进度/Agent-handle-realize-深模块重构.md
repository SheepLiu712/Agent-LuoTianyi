# Agent `handle_stimulus / realize_action_plan` 深模块重构进度

- 大目标：以两个有限 Agent interface 统一角色对刺激的认知决策与动作实现，逐步迁移聊天、玩偶和 world 调用链，并最终删除旧 AgentRuntime 业务代理和任意 Mapping 协议。
- PRD：[`Agent-handle-realize-深模块重构.md`](../需求说明（PRD）/Agent-handle-realize-深模块重构.md)
- 总体设计背景：[`Agent-handle-realize-深模块重构.md`](../设计文档/Agent-handle-realize-深模块重构.md)
- interface spec 索引：[`Server 模块接口文档`](../../项目说明/项目架构与接口（spec）/接口文档/README.md)
- 对应工单：[GitHub #60—#89](https://github.com/SheepLiu712/Agent-LuoTianyi/issues?q=is%3Aissue%20number%3A60..89)
- 总体状态：进行中

## 已完成事实

### 2026-09-06 门面公共入口与请求分流整理

- 交付内容：两个公共方法紧随 `__init__`；handle 入口直接登记请求，已有请求在 `_handle_existing_request` 处理后提前返回，新请求进入 `_process_request`。新处理和计划恢复共用处理权、交付及结算生命周期，原 `_handle_registered` 已删除；保留工作区已有的参数类型注解。
- SPEC 检查：facade、request-ledger、plan-emitter 的现有契约已满足，公开接口与行为不变；纯内部重构不新增 SPEC 或 RED commit，使用既有行为回归验证。
- commit：本记录所在 `codex/agent-facade-flow` 分支的 refactor 提交。
- 验证及结果：server 下运行 `D:/Anaconda/envs/lty/python.exe -X utf8 -m pytest tests/agent tests/agent_runtime -q --tb=short`，重构前 338 passed（65.62s），重构后 338 passed（46.21s）；Ruff 与 diff 检查通过。AST 确认类方法顺序为初始化、handle、realize，realize 及其他未调整方法保持原样；未修改测试。
- 未验证范围：未运行完整 Server、外部服务或生产环境验收。

### 2026-09-06 原输出恢复与可信结算补齐 GREEN

- 交付行为：可信完成或不安全失败行动的safe pending只投递原值，不重跑Handler；安全失败仍先重入Handler。恢复经过全计划准入与执行所有权，错误报告保留原效果及输出事实，失败不转换成业务完成。确认临时存储失败在最终可信结算补齐，本次仍停止新工作；首次payload保存失败保持未知，已有完整payload的尝试标记失败保留安全恢复值。
- interface spec：[输出投递契约](../../项目说明/项目架构与接口（spec）/接口文档/agent/output-delivery.md)、execution-ledger、facade、handler-routing已定稿为实现事实，项目架构及中文docstring同步。
- commit与SPEC：SPEC `a1c44e5e`、RED `1e44947c`均已作者自审；本记录所在 `codex/agent-output-recovery` 提交为GREEN，87项RED未改。`4d60a521`、`aff3bc6d`由独立测试作者修订最终资源清理预算，保留所有在途等待断言；Execution和PlanEmitter实际复现短预算抖动，Request Ledger为同形审计修订。
- 验证及结果：四个输出文件87 passed；server使用 `D:/Anaconda/envs/lty/python.exe -X utf8` 执行相关agent、agent_runtime、domain、world、system回归883 passed、2 skipped。Ruff、compileall、7份Agent SPEC UTF-8/围栏/链接和diff检查通过。包括真实临时SQLite故障、独立Python进程原音频恢复、UNKNOWN封闭、恢复等待者及重复取消清理。
- 未验证范围：两个world真实网络探测跳过；没有真实业务Handler、客户端播放、外部接收器或生产数据库验收；不表示#65业务Say已实现。


### 2026-09-06 确认输出后取消的可信结果 GREEN

- 交付行为：输出确认后协作取消不再覆盖处理器可信ActionResult；已完成项保留完成及效果，整体取消并只允许后续未开始行动继续；可信失败保留实际失败原因。UNKNOWN、未确认输出、持久故障和内容冲突仍阻断后续工作。
- SPEC与commit：既有execution-ledger与handler-routing取消结算契约已满足；PR #119独立审查新增RED `c2897f54`（2项）、`57074619`（1项），均已作者自审。本记录所在提交为最小GREEN，三项RED未改。
- 验证及结果：三个输出文件37 passed；server相关agent、agent_runtime、domain、world、system回归833 passed、2 skipped；Ruff、compileall、diff检查通过。首轮旧关闭用例20ms超时，原样定向复跑及完整复验通过。
- 未验证范围：两个world真实网络探测跳过；没有真实业务Handler、生产库或外部接收器验收。


### 2026-09-06 输出生产者与持久序列 GREEN

- 交付行为：处理器使用四种私有内容草稿，Agent绑定输出身份、从零跨行动连续编号并持久完整payload，串行等待有效回执；安全失败重入复用原槽，内容冲突及未知接收阻止后续输出与行动，已确认输出不重发。版本二序列元数据验证完整性，版本一旧库按真实输出历史保守兼容；输出错误记录不含内容和源码的安全日志。
- interface spec：[输出身份与持久序列](../../项目说明/项目架构与接口（spec）/接口文档/agent/output-delivery.md)，同步execution-ledger、facade、handler-routing及项目架构为实现事实；公开接口与私有输出协议具中文docstring。
- commit与SPEC：SPEC `11ccc9bf` / `d4d9ecc5`，RED `9bb7e059`；候选整理发现吞取消后重发UNKNOWN，追加RED `57d26032`并自审，实际失败于两次sequence=0。本记录所在 `codex/agent-output-delivery` 提交为GREEN。
- 验证及结果：server中使用 `D:/Anaconda/envs/lty/python.exe -X utf8`，相关agent、agent_runtime、domain、world、system测试 **829 passed、2 skipped**，其中34项输出用例。Ruff、compileall、Agent SPEC UTF-8/围栏/相对链接及diff检查通过；旧SQL夹具未修改。
- 未验证范围：两个world真实网络探测跳过；没有真实业务Handler、外部接收器、客户端播放或生产库验收；本地验证不表示完整#65或业务Say已经实现。

### 2026-09-06 PlanEmitter 日志源码隔离 GREEN

- 交付行为：投递失败日志从 traceback 提取文件、行号和函数名，保留角色、request、interaction、plan、ordinal、稳定错误码与异常类型；日志不传递原 traceback，不格式化源码、局部变量或原异常链。处理器捕获投递异常仍留下诊断记录，公开失败报告与消费事实保持正确。
- interface spec：[PlanEmitter](../../项目说明/项目架构与接口（spec）/接口文档/agent/plan-emitter.md) 已按实现定稿；没有新增公开接口或改变投递恢复行为。
- commit：SPEC `c6c4a8cc`、RED `5a4fc167`；GREEN 为 `codex/agent-plan-log-errors` 分支上本记录所在提交，原 RED 断言保持不变。
- 验证及结果：实现前日志用例实跑 1 failed，失败原因是输出含异常源码字面量；实现后 PlanEmitter 聚焦 45 passed。server 下 `D:/Anaconda/envs/lty/python.exe -X utf8 -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system -q --tb=short` 为 **796 passed、2 skipped**。相关 Ruff、compileall、git diff --check 与修改文档的 UTF-8、围栏、相对链接检查通过。
- 未验证范围：使用真实 utils logger、临时 SQLite 和受控协作者；两个 world 网络探测仍跳过。没有运行真实业务 Handler、外部队列、生产数据库或客户端验收。

### 2026-09-06 Execution Ledger 取消等待者事实 GREEN

- 交付行为：拥有者任务取消并完成清理后，给并发等待者发布最新完成前缀、效果与已确认输出，避免使用加入前快照；清理中返回可信结果但结算失败时保留当前效果，以 FAILED / DEPENDENCY_UNAVAILABLE 表达未完成持久化，不冒充 ALREADY_COMPLETED。相关存储错误日志使用稳定依赖错误码。
- SPEC 与 commit：Execution Ledger 既有取消、累计事实和结算失败契约已满足。初步 GREEN `94c295a3` 作者自审复现问题，RED `f0fdf077` 两项均失败；本记录所在提交为修复 GREEN，原 RED 断言未变。
- 验证及结果：40 项执行测试全部通过；完整相关命令 `D:/Anaconda/envs/lty/python.exe -X utf8 -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system -q --tb=short` 为 **795 passed、2 skipped**。相关 Ruff、compileall、diff 检查通过。
- 未验证范围：沿用执行账本切片的真实临时 SQLite 与受控协作者边界，没有新增真实外部能力、生产数据库或客户端验收；两个 world 网络探测仍跳过。

### 2026-09-06 Execution Ledger 逐行动持久恢复 GREEN

- 交付行为：公开 realize 校验完整计划身份并用角色/execution 复合主键仲裁；持久标记行动开始、可信结果及独立累计的未知/已确认输出。重投跳过已完成前缀，仅继续可信无效果且无已确认或未知输出的未完成行动；完成前缀带有输出和效果仍可继续后续安全行动。并发同执行加入同一拥有者，任务取消清理正常返回的可信结果在传播取消前持久结算。
- interface spec：[Execution Ledger](../../项目说明/项目架构与接口（spec）/接口文档/agent/execution-ledger.md)、facade、handler-routing 和架构索引已定稿为实现事实；公开 realize 文档说明持久身份、安全继续和取消语义。内部协议保留 AgentOutputSink，生产路由为空。
- commit：SPEC `25458406`、修订 `15f7b06c`，RED `c7694619`；GREEN 为 codex/agent-execution-ledger 分支上本记录所在提交。38 项新增测试未改动；日志按 RED 要求去除含字面量的源码行，保留异常类型和栈位置。
- 验证及结果：server 下 `D:/Anaconda/envs/lty/python.exe -X utf8 -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system -q --tb=short` 为 **793 passed、2 skipped**。相关 Ruff、Agent compileall、git diff --check、Agent SPEC UTF-8/围栏/本地链接检查通过。真实临时 SQLite 覆盖新 Python 进程完成和硬退出恢复、跨 Runtime 争用、数据库故障与损坏行拒绝。
- 未验证范围：两个 world 真实网络探测跳过；没有真实业务 Handler、外部能力、生产数据库或客户端验收。此记录只说明执行账本与逐行动安全继续，不表示 #65 全部完成或已进行独立 PR 审核。


### 2026-09-06 PlanEmitter 白名单错误分类 GREEN

- 交付行为：在数据库错误包装之前校验完整计划的显式类型白名单，自定义 Action 或嵌套 Tone 子类返回 INTERNAL_ERROR、无外部投递，不误报数据库不可用。接口文档精确区分累计未知接收事实与最后一次明确拒绝。
- commit 与 SPEC：现有 PlanEmitter 契约已满足；初步 GREEN `dce6f839` 自审发现错误分类，RED `dbd19ecd` 两项公开 handle 测试均失败于错误码，修复为本记录所在 GREEN 提交。
- 验证及结果：完整相关 pytest 为 **755 passed、2 skipped**，原42项新RED及两项补充RED全部通过；相关 Ruff、compileall、diff 检查以及四份 Agent 接口文档 UTF-8、围栏和本地链接校验通过。作者自审核对恢复权、取消清理、真实确认与旧测试迁移，没有剩余阻断发现。
- 未验证范围：沿用上一 PlanEmitter 完成记录的本地临时 SQLite 与受控协作者边界；未进行独立 PR 审核或真实外部依赖验收。

### 2026-09-06 PlanEmitter 持久投递与恢复 GREEN

- 交付行为：Handler 提交内部 ActionPlanDraft，由 PlanEmitter 分配稳定身份和连续 ordinal；完整计划落库后交付，记录有效回执、未知结果与明确拒绝。相同请求重投读取终态或原子领取已存计划恢复权，不重跑认知；同实例并发共享结果，恢复取消等待受控 sink 清理后释放恢复权。ack 写入失败时，最终结算能原子补齐真实确认，避免再次投递已知接收的计划。
- interface spec：plan-emitter、request-ledger、facade、handler-routing 已按实现定稿；项目架构记录 planning 与 outbox 的实际归属。内部协议及公开入口具有中文 docstring，两个业务方法和领域字段不变，生产路由仍为空。
- commit：SPEC `2194c0a9`、修订 `d7db3897`；RED `5ec6537a`、修订 `8a0f166e`；GREEN 为本记录所在提交。
- 验证及结果：完整相关 pytest 命令 `D:/Anaconda/envs/lty/python.exe -X utf8 -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system -q --tb=short` 在 server 下为 **753 passed、2 skipped**。42 项新增用例全部通过，原 Handler 测试按 Draft/真实回执身份迁移并保留行为断言。相关 Ruff、compileall、git diff --check 通过；临时 SQLite 覆盖旧库兼容、双实例和新 Python 进程恢复、持久接收器重复识别、存储错误与恢复取消。
- 未验证范围：两个 world 网络探测跳过；未验证真实业务 Handler、外部队列、生产数据库或客户端。持久 Fake 只证明可识别重复的接收器，不表示任意新连接恰好一次。此记录不表示 #64 的 ContextStore 等其他工作完成。

### 2026-09-06 Request Ledger 结算日志时点修复 GREEN

- 交付行为：移除处理器层尚未持久化时的完成日志，统一在公开 handle 确定最终报告后记录一次结算；终态提交失败只记录返回的依赖失败，不先宣称 completed。
- commit 与 SPEC：账本契约已满足；初步 GREEN `e8a6b49a` 自审发现问题，日志 RED `3129691c` 复现 3 条结算日志（其中 1 条提前 completed），GREEN `e14fb703` 修复，未改变领域或装配接口。
- 验证及结果：完整命令 `D:/Anaconda/envs/lty/python.exe -X utf8 -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system -q --tb=short` 为 **711 passed、2 skipped**；相关 Ruff、compileall 与 `git diff --check` 通过。原 44 项 Request Ledger RED 仍未修改。
- 未验证范围：沿用下述 Request Ledger 首片的验证边界，没有新增生产数据库、跨进程首次并发登记或外部服务验收。

### 2026-09-06 handle Request Ledger 持久幂等 GREEN

- 交付行为：AgentRuntime 向角色门面注入现有数据库会话工厂；Request Ledger 用角色/请求复合主键登记处理权，以版本化确定 fingerprint 检查输入，提交完整 JSON 终态后返回。相同请求恢复报告、不同内容拒绝；同实例重复等待原处理，不同实例未结算占用保守拒绝。等待者取消不取消拥有者，拥有者取消保留占用；关闭等待所有已登记调用。存储错误记录稳定身份和隐藏正文的栈信息，结算失败保留已接收计划 ID。
- interface spec：[handle 请求账本](../../项目说明/项目架构与接口（spec）/接口文档/agent/request-ledger.md)、门面和运行时接口均已定稿为当前事实；项目架构补充显式数据库注入与账本归属。公开构造和业务方法具有中文 docstring。
- commit：SPEC `cfa5858e`，RED `8f9e25c4`；GREEN `e8a6b49a`。原 44 项 RED 测试未修改，额外 11 项真实数据库损坏注入属于首次通过的补回归。
- 验证及结果：在 `server` 使用 `D:/Anaconda/envs/lty/python.exe -X utf8 -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system -q --tb=short`，**710 passed、2 skipped**。聚焦原请求用例 44 passed、补充恢复用例 11 passed；相关 Ruff、compileall、`git diff --check` 通过。
- 未验证范围：两个 world 真实网络探测跳过；没有跨进程同时首次登记争抢测试、真实业务处理器、外部能力或生产链验收。已验证临时 SQLite 的双实例争用及独立 Python 进程终态恢复。同步 SQL 调用期间的锁等待受注入引擎配置约束。此交付仅为 Request Ledger；没有实现 PlanEmitter outbox、ContextStore 或 Execution Ledger，不表示 #64 已全部解决。

### 2026-09-06 Agent 已注册路由、交付结算与在途关闭 GREEN

- 交付行为：AgentRuntime 为每角色装配两个独立空路由器；内部注册严格拒绝重复和非法键，门面通过两个业务接口调用已注册处理器。处理器获得单次受限 sink，计划/输出身份与回执校验、已确认事实、部分失败、行动顺序、协作取消及并发交互隔离均已实现。AgentRuntime 停止接受后等待在途处理器及清理，超时保留依赖供重试。
- 关闭修复：门面拥有处理器任务，调用方 Task.cancel 只向处理器转发一次，重复取消继续等待异步或同步清理，避免线程仍使用资源时提前关闭。没有修改共享 asyncio helper。
- interface spec：agent/facade.md、agent/handler-routing.md、agent_runtime/README.md 已按实现定稿；公开接口和路由协议提供中文 docstring。日志保存关联身份、稳定错误码、异常类型及栈位置，省略原异常正文和局部变量。
- commit：SPEC `4c031a4c`，RED `d870214c`，初步 GREEN `d21a2aeb`；重复调用方取消 RED `f5765cee` / GREEN `4f822f6d`；处理器实际开始前取消 RED `38322bd9`，最终 GREEN 为本记录所在提交。
- 验证及结果：原 69 项新增 RED 及原 38 项入口/兼容测试通过；补充的重复取消 RED 在初步 GREEN 上以关闭错误返回成功失败，修复后原断言保持不变并通过。另补 handle/realize 两项调度期间取消测试，先以错误消费/完成行动失败；处理器实际启动前检查令牌后通过。`D:/Anaconda/envs/lty/python.exe -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system -q --tb=short` 为 655 passed、2 skipped。相关产品代码与测试 Ruff、compileall、git diff --check 通过。`server/src` 的 get_agent 搜索仅剩方法定义，三处旧链路保持 get_character_runtime(...).conscious。
- 审核与验证范围：作者自审完成，尚未进行独立 PR 审核；本地测试使用受控内部处理器与接收器。两项真实网络探测跳过，未验证真实模型、capability、客户端、设备或生产服务器。本版生产处理器注册为空。

### 2026-09-06 Agent 空注册门面入口与旧查找迁移 GREEN

- 交付行为：`src.agent.Agent` 提供两个异步业务方法及中文 docstring，校验角色、交互、修订、参数和预取消，空注册返回 UNSUPPORTED；AgentRuntime 初始化组装每角色门面、严格查找并在关闭时停止接受。TopicReplier、SystemRuntime.agent、get_default_agent 三处旧调用改从 get_character_runtime 取得旧意识对象。
- interface spec：agent/facade.md 与 agent_runtime/README.md；SPEC `d5303223`，RED `0601a6d2`，GREEN 为本记录所在提交。
- 验证及结果：原 38 项 RED 测试保持不变，GREEN 38 passed；与 domain/world 合并 582 passed、2 skipped。5 项旧初始化回滚测试通过。门面、AgentRuntime 及新增测试 Ruff、git diff --check 通过，作者自审完成。
- 未验证范围：#63 已注册处理器路由、处理中取消、部分结算和在途关闭尚未实现；未验证真实模型、设备或生产链。额外解除暂缓运行的系统关闭测试因 CapabilityManager 测试替身缺少 _stop_lock 失败，该既有测试问题未修复。不将本轮入口 GREEN 记作 #63 完成。


### 2026-09-06 WorldClock 调度注册基线与关闭重试 GREEN

- 交付行为：通过公开 WorldClock/WorldRuntime 入口冻结九类任务注册、角色展开、配置与启用条件、本地每日时间、立即执行、同名替换、失败隔离和关闭行为；将适用的旧 world 任务测试迁至 `server/tests/world` 并恢复默认执行。WorldClock 重试关闭时只等待已请求取消的任务，不重复取消同步线程的清理等待。
- interface spec：[`world/README.md`](../../项目说明/项目架构与接口（spec）/接口文档/world/README.md)，SPEC commit `ca546227`；没有新增公开接口。
- commit 或 PR：RED `a14018e2`，旧测试整理 `07aa2a50`，GREEN 为 `codex/world-clock-baseline` 分支本记录所在提交。
- 验证及结果：原 RED 稳定复现第二次关闭错误返回成功；保持失败测试不变，`D:/Anaconda/envs/lty/python.exe -m pytest tests/world tests/domain -q` 为 544 passed、2 skipped。world 为 115 passed，domain 为 429 passed。WorldClock 和 world 测试及默认执行配置 Ruff 通过；迁移前后测试函数清单一致，未遗漏或复制测试。其他新增调度测试及恢复的旧测试属于既有行为回归，无伪造 RED。
- 未验证范围：两项真实 VCPedia/B 站探测仍跳过；未验证完整服务器、客户端或生产环境。已有任务业务测试不代表九类任务的完整业务契约已经审核；作者自审不替代独立 code review。

### 2026-09-05 Agent 深模块需求与总体设计基线

- 交付内容：确定 Agent 只保留 `handle_stimulus` 与 `realize_action_plan` 两个业务 interface，明确 Agent、stage、Adapter、world、subconscious、capabilities 和 AgentRuntime 的职责与迁移边界，并发布实现工单 #60—#89。
- 文档：上述 PRD、总体设计背景和根目录 [`CONTEXT.md`](../../../CONTEXT.md)。
- commit 或 PR：`refactor/agent` 历史提交 `8e00241d` 至 `816db81a`。
- 验证及结果：完成设计文档、领域词汇和工单之间的静态核对；该记录不表示产品实现或端到端链路已经完成。
- 未验证范围：真实聊天、玩偶、world、LLM、TTS、GPU、设备和生产环境行为。

### 2026-09-05 迁移期 `TextMessage` 最小公开入口

- 交付内容：`src.domain.agent` 已提供迁移期 `TextMessage`、`StimulusKind.TEXT_MESSAGE` 和 `StimulusSource.USER`，旧 Stimulus 与该入口暂时共用 `PersistPolicy`。
- interface spec：[`domain/README.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/README.md) 中标明的当前实现。
- commit 或 PR：PR #90，当前重放提交 `ede19abb`。
- 验证及结果：合入时的公开构造契约测试为 Green；该结果只证明迁移期入口，不证明本轮目标契约。
- 未验证范围：抽象 `Stimulus`、完整字段校验、稳定错误、移除目标包的 `PersistPolicy` 以及生产调用链迁移。

### 2026-09-05 `Stimulus / TextMessage` 领域契约实现

- 交付内容：实现不可直接构造的抽象 `Stimulus`、不可变 `TextMessage`、四种 `StimulusSource`、固定 `TEXT_MESSAGE` 判别值和稳定构造错误；目标包不再导出 `PersistPolicy`，迁移期旧 Stimulus 继续从旧路径使用自己的持久化协议。
- interface spec：[`domain/stimulus.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/stimulus.md)。
- commit 或 PR：分支 `codex/agent-01-stimulus-text-message-contract`；Red commit `31281005`。
- 验证及结果：Red 阶段聚焦测试为 39 failed、1 passed；最小实现后 `python -m pytest tests/domain/test_stimulus_text_message_contract.py -q` 与 `python -m pytest tests/domain -q` 均为 40 passed。启用临时测试收集策略前，默认 Server 回归为 477 passed、2 skipped、6 failed；失败位于 diary、preferences、proactive topic、runtime shutdown 和依赖真实数据的 Bilibili 测试，均不在本切片修改路径内。按项目负责人决定，之后只执行本切片新增契约测试；重新运行 `python -m pytest tests -q` 为 40 passed、445 skipped，跳过项不构成回归通过证据。
- 未验证范围：生产调用链迁移、真实聊天、玩偶、world、LLM、TTS、GPU、设备和生产环境行为；默认 Server 回归中的 6 个本切片外失败尚未在本切片处理。

### 2026-09-06 当前总 SPEC 的 Stimulus 领域契约实现

- 交付内容：实现当前总 SPEC 登记的全部 `StimulusKind`、15 个不可变可构造 Stimulus、7 个统一拒绝构造的占位类型，以及受控引用、动态消息、触摸频率、world/activity 事实和歌曲知识候选等领域值类型；所有构造入口保持仅限关键字、无任意 `payload`、无 `PersistPolicy`，也不校验字段间的生产场景组合。
- interface spec：[`domain/stimulus.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/stimulus.md)。
- commit 或 PR：分支 `codex/agent-01-stimulus-text-message-contract`；Red commit `f85c9e03`；Green commit `de71ae97`；审核补测与文件拆分为本记录所在收尾提交及其前一提交。
- 验证及结果：Red 阶段聚焦测试为 41 passed、92 failed，失败集中在尚未实现的登记类型、枚举、值对象和校验；Green 后聚焦测试为 133 passed。审核补充的 3 个受控引用名义隔离测试在既有实现上首次即通过，无 Red 证据；职责拆分后聚焦测试为 136 passed。`python -m ruff check src/domain/agent src/domain/stimulus.py tests/domain/test_stimulus_text_message_contract.py tests/domain/test_stimulus_registered_types_contract.py` 与 `python -m compileall -q src/domain/agent` 通过；按项目负责人要求运行 `python -m pytest tests -q` 为 136 passed、445 skipped，跳过项不构成回归通过证据。
- 未验证范围：15 个可构造类型尚未接入生产 Adapter、stage、world 或 Agent handle；受控引用读取 port、`HandleStimulusRequest.interaction.pending_stimuli`、真实数据库/媒体、聊天、通话、玩偶、LLM、TTS、GPU、设备和生产环境均不在本行为切片内。

### 2026-09-06 handle 输入 SPEC 第一版

- 交付内容：完成供评审的 handle 输入文档，定义 `HandleStimulusRequest`、Chat/Toy/World 快照、必要值类型及可变 `CancellationToken`；记录交互身份与修订号的区别、删除的状态字段、两类取消原因及首次取消语义，并同步接口索引、总体设计背景、PRD 说明和领域词汇。
- interface spec：[`domain/handle-input.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/handle-input.md)，状态为第一版、待评审且尚未实现。
- commit 或 PR：分支 `codex/agent-02-handle-input-contract`，本记录所在 SPEC 提交。
- 验证及结果：文档静态核对完成；新增 SPEC 的 UTF-8、代码围栏、九项用户结论相关词项及新增相对链接检查通过；`git diff --check` 通过。文档交付的运行时 Red/Green 不适用。
- 未验证范围：本记录只证明 SPEC 文档交付；没有新增产品代码或测试，没有实现 handle 输入类型、取消处理、Agent/stage 链路，也没有完成他人评审或远程 PR 合并。

### 2026-09-06 handle 输入 SPEC 的上下文归属修订

- 交付内容：删除输入中的 `conversation_ref`、`visible_world_ref` 和通用 `SnapshotRef`；明确 Agent 内部按角色与 interaction 管理历史对话、摘要及 Recall 工作上下文，清理临时上下文不删除长期正本，取消单次 handle 不等于结束 interaction。输入快照直接按值传递，不建立快照持久化或 ID 解析机制；world 内容通过已有强类型 Stimulus 传入。同步总体架构、设计背景、PRD、接口文档、领域词汇和验收场景。
- interface spec：[`domain/handle-input.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/handle-input.md)，修订版待评审、尚未实现。
- commit 或 PR：分支 `codex/agent-02-handle-input-contract`，本记录所在 SPEC 提交。
- 验证及结果：删除字段及导出、保留身份/修订/取消契约、文档 UTF-8、代码围栏、变更相对链接与 `git diff --check` 静态检查通过；运行时 Red/Green 不适用。
- 未验证范围：没有新增产品代码或运行时测试；Agent 工作上下文与清理、world 处理、后台反思证据生命周期均未实现或验证，本记录不代表运行时交付。

### 2026-09-06 删除独立演唱状态输出草案

- 交付内容：从 handle 输入的输出能力枚举、PRD 输出列表和总体设计中删除 `SONG_STATE`，移除 `SongPlaybackState` 草案引用；演唱使用音频及可选文字、表情输出。
- interface spec：[`domain/handle-input.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/handle-input.md)。
- commit 或 PR：分支 `codex/agent-02-handle-input-contract`，本记录所在 SPEC 提交。
- 验证及结果：三个相关契约文档的定义及引用残留检查、`git diff --check` 通过；文档修改的运行时 Red/Green 不适用。
- 未验证范围：未修改产品代码或测试，未验证运行时演唱链路。

### 2026-09-06 handle 输入领域契约 GREEN

- 交付行为：从 `src.domain.agent` 提供三种不可变交互快照、`HandleStimulusRequest`、`CancellationToken` 及已登记枚举和稳定构造错误。实现显式关键字构造、字段/集合/时间校验、pending 去重和 trigger 一致性；取消令牌保留首次原因、重复取消幂等，并通过同一对象向请求观察者发布状态。没有新增上下文快照引用、持久化或已删除的状态类型。
- interface spec：[`domain/handle-input.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/handle-input.md)；本次未扩大公开契约，只更新实现状态。
- commit 或 PR：SPEC 基线截至 `1b9d167a`；RED commit `9389c7ea`；GREEN 为分支 `codex/agent-02-handle-input-contract` 上本记录所在提交。
- 验证及结果：使用 `D:/Anaconda/envs/lty/python.exe`，工作目录 `server`。实现前重新运行 `-m pytest tests/domain/test_handle_input_contract.py -q --tb=no -rN` 为 97 failed、1 passed；实现后该文件为 98 passed，`-m pytest tests/domain -q` 为 234 passed、0 skipped，原有 136 项领域测试均通过。`-m ruff check src/domain/agent tests/domain/test_handle_input_contract.py`、`-m compileall -q src/domain/agent` 和 `git diff --check` 通过。
- 未验证范围：未运行完整 Server/客户端测试、真实设备或外部服务；未实现 Agent handle、plan sink、HandlingReport、stage 重连/结算、迟到模型结果丢弃或 Agent 工作上下文生命周期。本次 GREEN 仅证明输入领域对象及令牌契约，不代表生产链路已迁移或远程 PR 已合并。

### 2026-09-06 handle 接口文档事实化整理

- 交付内容：接口文档仅记录当前公开类型、字段、构造约束、取消状态和错误行为；移除历史删除清单、非目标、未来 Agent/stage 行为要求及尚不可调用的示例。补充可执行的请求构造示例；本轮临时测试证据已移至仓库外归档。
- interface spec：[`domain/handle-input.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/handle-input.md)，同步 domain 索引及 agent/stage 接口页。
- commit 或 PR：分支 `codex/agent-02-handle-input-contract`，本记录所在文档整理提交。
- 验证及结果：接口文档措辞、UTF-8、相对链接、实际构造示例和 `git diff --check` 检查通过；产品代码与测试未改动，文档整理的运行时 Red/Green 不适用。
- 未验证范围：本记录不表示已完成他人代码审查或新增运行时验收。

### 2026-09-06 HandlingReport 类型契约 GREEN

- 交付行为：`src.domain.agent` 提供不可变 `HandlingReport`、`HandlingRequestStatus`、`HandlingErrorCode`、`InvalidHandlingReportError` 和 `HandlingReportErrorCode`。实现全部字段显式关键字构造、身份元组校验、considered 的互斥完整划分及相对顺序、状态与错误码关联、重评时间约束；保留计划身份及显式 retryable 值。请求状态与内容消费结果分别表达。
- interface spec：[`domain/handling-report.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/handling-report.md)，已同步实现状态和可执行构造示例。
- commit 或 PR：SPEC `00ef610b`；RED `812bb249`；GREEN 为分支 `codex/agent-03-handling-report-contract` 上本记录所在提交。
- 验证及结果：使用 `D:/Anaconda/envs/lty/python.exe`，工作目录 `server`。RED 为 94 failed，全部源于公开能力尚未实现；本次保持测试不变，`-m pytest tests/domain/test_handling_report_contract.py -q` 为 94 passed，`-m pytest tests/domain -q` 为 328 passed、0 skipped，包含原有 234 项领域用例。`-m ruff check src/domain/agent tests/domain/test_handling_report_contract.py tests/conftest.py`、`-m compileall -q src/domain/agent` 和 `git diff --check` 通过。
- 未验证范围：未运行完整 Server/客户端测试、真实设备、外部服务或生产环境；本次只验证报告领域对象，未接入 Agent handle、计划 sink、stage 结算或运行时重试链路。

### 2026-09-06 HandlingReport 接口文档事实化整理

- 交付内容：报告接口页聚焦公开名称、字段含义、构造约束、稳定错误和实际测试入口；移除重复验收清单，明确构造器只校验报告内部关系。domain 索引补齐报告导出；相关 domain、agent、stage 接口页移除迁移要求和待补测试清单。
- commit 或 PR：分支 `codex/agent-03-handling-report-contract`，本记录所在文档整理提交。
- 验证及结果：公开字段和枚举与实现核对、构造示例执行、UTF-8、相对链接和 `git diff --check` 检查通过。产品代码与测试未修改；工作区没有未跟踪临时文件，RED/GREEN 证据保存在仓库外。
- 未验证范围：本次为文档整理，没有新增运行时验收或他人审核结果。

### 2026-09-06 Agent 领域公开类型中文说明

- 交付内容：为 `server/src/domain/agent` 的 55 个公开类补齐中文 docstring，为 `StimulusErrorCode` 和 `InteractionSnapshot` 两个类型别名补充源码说明；说明现有字段含义、关键构造约束、取消状态及结算关系，标明七个占位类型的构造失败行为。
- SPEC 检查：现有 `domain/stimulus.md`、`domain/handle-input.md` 和 `domain/handling-report.md` 已满足，本次仅补充源码文档。运行时 RED/GREEN 不适用；未创建 SPEC、RED 或 GREEN commit。
- 验证及结果：使用 `D:/Anaconda/envs/lty/python.exe`，在 `server` 目录运行 `-m pytest tests/domain -q` 为 328 passed；`-m ruff check src/domain/agent`、`-m compileall -q src/domain/agent` 和 `git diff --check` 通过。静态检查确认所有公开类均有自身的中文 docstring，两个别名均有中文源码说明；移除文档字符串后，八个 Python 文件的语法树与 HEAD 一致。作者已核对说明与当前实现和接口契约。
- 未验证范围：未运行完整 Server、客户端或生产链路验收；没有新增他人代码审查结果。

### 2026-09-06 Issue #61 realization SPEC 草案与现行行为核对

- 交付内容：完成 ActionPlan、Action、两个 sink/receipt、ExecutionContext、输出和执行报告的第一版待评审草案；逐项核对总设计中的用途与重复信息，记录思考提示、私密发布归属、音频异常终包、音频分块、表情恢复及活动/日程范围等风险。新增和精简建议均未标为已确认契约。
- interface spec：[`domain/realization.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/realization.md)；依据与风险见 [`Issue-61-realization-契约核对.md`](../设计文档/Issue-61-realization-契约核对.md)。
- commit 或 PR：`codex/agent-04-realization-contract` 分支上的本记录所在 SPEC 草案提交。
- 验证及结果：按 `c523b2a6` 的实际代码核对聊天、触摸、语音、演唱、日记、动态和学歌入口；阅读现有音频终包测试，未运行它们。新增文档 UTF-8、代码围栏、相对链接及 `git diff --check` 静态检查通过。草案阶段 RED/GREEN 不适用。
- 未验证范围：没有产品代码或测试实现，没有接入 Agent、sink 或外部服务；没有验证真实播放、设备、生产环境或完成他人评审。远程工单未修改。

### 2026-09-06 realization SPEC 会话结论落实

- 交付内容：将 realization 文档更新为已确认、尚未实现的目标契约；增加由 stage 直接消费的 StartThinking 独立计划，明确其处理结算与业务执行的区别；以 MessageEndOutput/MESSAGE_END 替代音频结束草案，覆盖纯文字、正常音频、错误和取消终包；说明 ExecutionContext 的创建/使用位置，消除 SinkRejectedError 的措辞歧义，保留成功回执与拒绝异常两条路径。
- 顺序约定：本版保持计划、行动和输出的正常顺序，沿用客户端终止包及播放队列实现表情恢复；严格乱序检测、丢包恢复和跨连接投递去重不作为本版要求。未新增播放完成回执。
- interface spec：[`domain/realization.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/realization.md)；同步 domain 索引、核对记录及 PRD/历史总体设计的权威指向。
- commit 或 PR：`codex/agent-04-realization-contract` 分支上的本记录所在 SPEC 修订提交；没有新增 RED/GREEN commit。
- 验证及结果：本轮文档 UTF-8、代码围栏、新增相对链接、关键契约词项和 `git diff --check` 静态检查通过。文档修订的运行时 RED/GREEN 不适用。
- 未验证范围：未修改产品代码、测试或远程工单；未运行客户端播放、真实依赖或生产环境验收。

### 2026-09-06 realization 领域契约 RED / GREEN

- 交付行为：`src.domain.agent` 新增 42 个公开类型，包含七种 Action、ActionPlan、执行上下文、四种具体输出、两个 sink Protocol/回执、执行报告和值/错误枚举。实现显式关键字构造、不可变值和稳定错误、StartThinking 独立首计划、Say 音频互斥、私密发布归属、消息终止组合及部分执行结果校验。公开类型、方法和属性均有中文 docstring；AgentOutputKind 及快照测试改用 MESSAGE_END。
- interface spec：[`domain/realization.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/realization.md)；同步 handle 输入枚举文档。SPEC commit `17ee66a1` 已满足，本轮未增加接口。
- commit 或 PR：RED `aa0fd0a5`；GREEN 为 `codex/agent-04-realization-contract` 分支上本记录所在提交。
- 验证及结果：使用 `D:/Anaconda/envs/lty/python.exe`，工作目录 server。RED 的 `-m pytest tests/domain -q --tb=no -rN` 为 103 failed、326 passed，其中 101 项为新协议缺失，2 项为已确认的输出枚举更名；没有收集或导入错误。保持 RED 测试不变，GREEN 领域测试为 429 passed；Ruff、compileall 通过。静态检查确认 42 个新增公开类型及其公开方法/属性具有中文 docstring。
- 未验证范围：没有实现实际接收器、Agent 门面/执行器、stage 思考通知消费、消息终包发送、客户端播放或真实持久效果；没有运行完整 Server、客户端、外部服务或生产验收。Protocol 声明与领域值测试不构成这些运行时行为的证明。

### 2026-09-06 单次处理流程与 processing 整理

- 交付行为：门面委托 Handling.run 和 Execution.run；处理器取消与清理共用 invocation.call_handler；计划与输出按本次调用顺序交付。移除业务流程中的 ledger/outbox、历史报告复用、重复调用合并和重发恢复；失败停止，保留已确认结果，retryable=False。Ledger 源码保留并补充中文接口说明与类型提示。
- interface spec：agent/facade.md、plan-emitter.md、output-delivery.md、handler-routing.md 与领域报告说明已同步；总设计和 PRD 撤销对应恢复要求。远端 15 项相关 issue 已补充范围说明，保持开放。
- 验证：Agent/AgentRuntime 142 passed；完整 Server 687 passed、350 skipped、1 个第三方弃用警告。跳过项沿用原配置。保留单次顺序、取消、部分效果和日志测试，移除旧账本恢复测试及无引用 SQL 样例；修复捕获取消后继续发送与输出日志身份缺失。
- 提交组织：按用户要求在 codex/agent-facade-flow 分支分别提交文档、测试和代码；本轮不是 TDD 阶段拆分。
- 未验证范围：真实业务 Handler、外部服务、客户端和生产环境；已有数据库记录未清理。
