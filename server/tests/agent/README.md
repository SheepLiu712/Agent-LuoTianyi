# Agent 门面入口测试

## 已知回执结算补齐 SPEC / RED 修正（2026-09-06）

SPEC 修正 `d7db3897` 在原 SPEC `2194c0a9` 上明确：有效回执已经确定接收，本地 ack 写入失败不能降级为未知接收。保存报告的事务原子补齐 emitter 实际校验的回执，成功后终态保留 FAILED / DEPENDENCY_UNAVAILABLE 和原计划 ID、retryable=False，重建 Agent 不再交付该计划；补齐或结算失败则保留占用。作者自审确认没有信任 Handler 自报 ID，也没有改变真正未知结果的恢复。

本次修正原 RED `5ec6537a` 的 `test_ack_commit_failure_settlement_saves_receipt_without_redelivery`：外部已确认、一次 ack commit 失败而最终保存成功后，新实例重投必须零 emit，返回与首次相同的持久失败报告。原来要求再次 emit 的断言会诱导重复已知接收，已删除。永久结算失败保留占用由现有 `test_report_commit_failure_preserves_accepted_ids_and_blocks_reprocessing` 覆盖。

实际命令（server 目录）：`D:/Anaconda/envs/lty/python.exe -X utf8 -m pytest tests/agent/test_plan_delivery_recovery.py::test_ack_commit_failure_settlement_saves_receipt_without_redelivery tests/agent/test_request_idempotency.py::test_report_commit_failure_preserves_accepted_ids_and_blocks_reprocessing -q --tb=short --show-capture=no` 为 **1 failed、1 passed**。修改用例仍先因旧实现不接受 draft、sink 没有收到计划而失败，尚未到达 ack/结算分支，不把此 RED 声称为已验证原子补齐。Ruff 和 diff 检查通过。作者自审只修改文档与该测试，不含产品实现或完成记录。


## PlanEmitter 白名单错误分类 GREEN（2026-09-06）

保持 RED `dbd19ecd` 两项测试不变，在存储包装前校验完整计划白名单；非法 Action
或嵌套类型现在返回 INTERNAL_ERROR，并且零交付。初步 GREEN 为 `dce6f839`。
最终完整相关 pytest 为 **755 passed、2 skipped**，相关 Ruff/compileall/diff 检查通过；
四份 Agent 接口文档 UTF-8、代码围栏和本地链接检查通过。作者自审核对恢复权、
受控取消、真实回执原子补齐、未知历史保留和旧测试迁移，未发现剩余阻断问题。
独立 PR 审核及真实外部依赖仍未进行。

## PlanEmitter 白名单错误分类 RED（2026-09-06）

GREEN `dce6f839` 作者自审发现：领域容器接受的 Action/Tone 子类不在持久白名单，
编码拒绝被存储包装误报 DEPENDENCY_UNAVAILABLE。新增公开 handle 的两个子类场景，
要求 INTERNAL_ERROR、retryable=False 和零交付；运行
`-m pytest tests/agent/test_plan_emission.py -k non_whitelisted -q --tb=short`
为 **2 failed**，均精确失败于错误码。没有修改产品代码或原42项RED断言。

## PlanEmitter GREEN（2026-09-06）

SPEC `2194c0a9`、确认结算修订 `d7db3897`；RED `5ec6537a`、修订 `8a0f166e`。
42 项 RED 预期保持不变，全部通过。内部 Handler 提交 Draft；Emitter 串行分配稳定计划身份，
完整 outbox 提交后才交付，确认和报告原子结算；公开重投仅恢复原计划。
外部确认后 ack 提交失败但最终结算恢复成功时，真实确认被原子补齐，终态重投零交付。

旧 Handler 测试改为提交 Draft，报告使用真实回执 ID，断言使用外部 Sink 捕获的身份。
五项旧完整计划身份伪造用例迁移为完整计划/错误草稿类型/非法来源拒绝；身份由 Emitter
固定的事实在成功调用中逐项检查。其余错误、消费、并发、取消、重复和关闭断言保留。
删除仅为 RED 准备的缺失类型和缺失装配参数 fallback。

实际验证（工作目录 `server`）：完整相关命令
`D:/Anaconda/envs/lty/python.exe -X utf8 -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system -q --tb=short`
为 **753 passed、2 skipped**；agent/runtime 为 **208 passed**。
相关 Agent/Runtime 产品与 agent/runtime/domain/world/system 测试 Ruff、产品 compileall、diff 检查通过。
临时 SQLite 证明跨实例及独立 Python 进程恢复、PR115 旧数据库终态兼容与接收器持久去重。
两项 world 网络探测仍跳过，未运行真实业务 Handler、外部接收队列或生产数据库验收。

## PlanEmitter SPEC / RED（2026-09-06）

SPEC commit `2194c0a9`：内部 ActionPlanDraft、连续 ordinal、稳定计划身份、持久 outbox、请求 provisional/终态和只恢复投递的公开重投契约。作者自审检查了 source 可为空、合法部分消费不丢失、恢复预取消不改写 provisional、永久拒绝的最终错误码以及 PR115 旧数据库终态兼容。业务方法及 domain 字段没有增加。

新增 42 个展开用例：

- `test_plan_emission.py`：零/单/多计划及身份字段、已确认 ordinal 的同值重投与改内容/改来源/非法 ordinal 拒绝、非法草稿、空来源 StartThinking 首计划、角色隔离、接收后取消、失效 emitter、捕获异常后仍有日志、同次并发草稿顺序。
- `test_plan_delivery_recovery.py`：超时/普通异常/错回执/背压后的重建恢复、合法部分消费、确认前缀不重复交付、永久拒绝终态、待确认槽位阻止新计划及同槽位正向重试、当前令牌和 fingerprint 校验、outbox/确认写入故障、恢复取消清理后重新获得处理权、恢复并发与 shutdown、认知尚未结算时禁止接管、新 Python 进程恢复完整六种业务 Action 并验证终态零交付。
- `fixtures/request_ledger_v1.sql` 由 PR115 的公开 handle 对人工样例生成，恢复旧数据库后先断言历史终态不交付，再验证新计划与旧记录共存；不通过表名或私有 SQL 步骤断言行为。

实际验证（工作目录 `server`）：

- `D:/Anaconda/envs/lty/python.exe -X utf8 -m pytest tests/agent/test_plan_emission.py tests/agent/test_plan_delivery_recovery.py -q --tb=no -rN`：**41 failed、1 passed**。零计划为补回归，既有实现已支持。
- `D:/Anaconda/envs/lty/python.exe -X utf8 -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system -q --tb=line --show-capture=no`：**41 failed、712 passed、2 skipped**，两项真实网络探测仍跳过；只有上述新行为失败。原 711 项回归单独运行同样通过。
- 新测试、辅助样例与 conftest 的 Ruff 通过；`git diff --check` 通过。

RED 失败首先表现为旧 `_PlanDelivery` 拒绝内部 draft，产生 FAILED/空交付，或 Handler 捕获后仍错误返回 COMPLETED。因此这些 RED 证明缺少目标协议和投递行为，**不代表已经逐项运行到恢复分支**；GREEN 后完整断言才验证持久化、恢复和并发。没有依赖导入、语法、测试环境或生产网络错误制造失败。

作者自审：只修改测试/样例/测试启用清单，未修改产品代码或追加实现完成记录。测试从公开 handle/shutdown 观察输出和报告；SQLAlchemy 故障钩子只作用于外部数据库提交。持久 Fake 接收器明确拥有自己的去重记录，证明可识别重复的效果，不声称任意新 sink 都恰好一次。SQLite 连接、引擎与异步任务均释放。

GREEN 迁移旧测试时，内部 Handler 改为构造 Draft，报告计划 ID 从真实 PlanReceipt 或首次 sink 接收取得；保留原身份冲突、取消、消费、重投和关闭断言，不复制计划 ID/fingerprint 算法，也不能删除难适配场景。移除本轮 draft helper 中仅用于 RED 的缺失类型 fallback。真实生产 Handler、Say 实现、真实接收队列与外部服务均未验证。


## Request Ledger 结算日志 GREEN（2026-09-06）

保持 RED `3129691c` 不变，移除处理器和存储失败分支的提前/重复结算日志；公开 handle
在最终报告确定后记录一次结束状态。完整相关回归实跑 **711 passed、2 skipped**，
包含 44 项请求幂等、11 项损坏恢复补回归及 1 项日志 RED。Ruff、compileall 和 diff 检查通过。

## Request Ledger 结算日志 RED（2026-09-06）

对 GREEN `e8a6b49a` 自审时发现：终态提交失败之前，旧处理器层已经记录 COMPLETED，
随后外层又重复记录 FAILED。新增公开 handle + SQL 提交失败 + 日志接收器用例，要求
仅记录最终返回的失败结算；`-m pytest tests/agent/test_request_storage_recovery.py -k logs_only -q --tb=short`
实跑 **1 failed**，实际出现 3 条结算日志，第一条错误宣称 completed。

## Request Ledger GREEN（2026-09-06）

SPEC `cfa5858e`、RED `8f9e25c4`；44 项原 RED 测试保持不变，GREEN 后全部通过。
真实 SQL 数据库按角色和请求 ID 仲裁占用、持久化完整终态；门面合并同实例在途调用，
重复读取不会重新交付，取消与关闭仍等待拥有的工作。会话工厂由 AgentRuntime 注入。

新增 `test_request_storage_recovery.py` 的 11 项补回归，通过 SQL 外部存储边界注入
未知记录/报告版本、损坏 fingerprint/JSON、缺失字段、非法状态或身份集合、错误请求/
触发刺激/修订/pending，观察公开 handle 拒绝且不再次交付。它们对初步 GREEN 首次执行即通过，
不记作新 RED。注入代码依赖账本存储格式以模拟损坏，不断言内部 SQL 查询次数。

实际验证（工作目录 `server`）：

- `D:/Anaconda/envs/lty/python.exe -X utf8 -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system -q --tb=short`：**710 passed、2 skipped**。
- 新请求幂等原用例 **44 passed**，新增存储恢复用例 **11 passed**；两个跳过项为 world 真实网络探测。
- 相关 Agent、AgentRuntime、测试及 conftest 的 Ruff、产品 compileall、`git diff --check` 均通过。

已有独立 Python 子进程读取终态和同数据库双实例争用证据；未运行跨进程同时首次插入的争抢测试、
真实业务 Handler、外部能力或生产数据库验收。同步 SQL 的锁等待仍受注入数据库引擎配置约束。

## Request Ledger RED（2026-09-06）

SPEC：`agent/request-ledger.md`，提交 `cfa5858e`。`test_request_idempotency.py` 通过公开 handle、AgentRuntime 初始化及 shutdown 验证 44 个展开用例：

| 场景 | 数量 | 测试目的 |
| --- | ---: | --- |
| 终态与实例重建 | 8 | 成功、部分消费、失败、取消、零计划的报告值稳定，已确认计划不再次交付，reconsider_at 和 retryable 原样恢复 |
| 聊天请求语义变更 | 16 | 同 request_id 的触发锚点、正文、来源、时间、客户端 ID、ephemeral、快照身份/修订/用户/时间/时区/期限/连接/输出集合、pending 顺序和正文变化被拒绝 |
| 取消与集合身份 | 2 | 新令牌不参与 fingerprint，已完成报告优先于后来的取消；预取消形成终态 |
| 玩偶和世界事实 | 7 | device、online、world、活动修订、规划周期及日程修订参与身份 |
| 未支持刺激和装配失败 | 2 | 未支持刺激终态在重新注册后仍可恢复；数据库初始化失败回滚资源 |
| 并发与占用 | 4 | 取消重复等待者不取消首调用、不重复交付；冲突不等待；另一实例拒绝活动占用并在终态后读取；首调用取消后等待者及重建实例不接管 |
| 角色和请求隔离 | 1 | 不同 request_id 和不同角色独立结算 |
| 存储故障 | 2 | 读写依赖不可用不进入处理器；终态提交失败保留已接收计划 ID，重建后拒绝重跑；日志关联身份并隐藏异常正文 |
| 生命周期和进程恢复 | 2 | 关闭等待首调用和重复等待者，不提前释放依赖；独立 Python 进程读取同一临时 SQLite 中的终态 |

测试装配给真实 AgentRuntime 注入具有 `open_sql_session` 的数据库替身，该方法返回真实临时 SQLite SQLAlchemy Session；未模拟 ledger，不查询私有表或算法。所有临时引擎结束时 dispose，子进程有超时和返回码检查。

实跑：`D:/Anaconda/envs/lty/python.exe -m pytest tests/agent/test_request_idempotency.py -q --tb=no` 为 **42 failed、2 passed**。失败来自尚无请求账本导致的重复交付、错误接受冲突、未恢复终态及未使用数据库；活动冲突/被取消拥有者的等待超时是目标等待行为缺失，不是测试环境失败。两项首次通过的是同实例零计划结果值和角色/请求隔离，作为既有回归，不伪造 RED。

连同 Agent、AgentRuntime、domain、world、system 回归为 **42 failed、657 passed、2 skipped**；两项真实 world 网络探测保持跳过。Ruff 通过。没有产品实现变更，也不表示 #64 完成。JSON 损坏和未知版本行的精确恢复、跨进程同时争抢尚无自动化测试证据；代码审查须核对唯一约束、版本与解码失败的保守处理。计划 outbox 不属于这组测试。

对应 SPEC：`docs/项目说明/项目架构与接口（spec）/接口文档/agent/facade.md`，SPEC commit `d5303223`。

## 测试目的

| 文件 | 展开用例 | 目的 |
| --- | ---: | --- |
| `test_facade_contract.py` | 21 | 两个异步业务方法、中文方法说明、包导出与内部对象隐藏；空注册失败；角色/交互/修订校验；两类预取消；拒绝时保留 pending、行动全部 NOT_STARTED、无 sink 输出；关闭后拒绝；顶层参数类型错误 |
| `../agent_runtime/test_agent_lookup.py` | 12 | 每角色缓存、新旧对象隔离、严格角色查找；保留旧注册表和可调用旧方法；关闭幂等及初始化失败回滚 |
| `../agent_runtime/test_legacy_agent_access.py` | 5 | get_agent 语义改变后，SystemRuntime.agent、get_default_agent 和旧 TopicReplier 仍使用 get_character_runtime；话题队列仍完成回复持久化、发送和反思交付 |

## 旧调用链检查

对 `server` Python 源码的 get_agent 调用搜索发现三个生产调用点：

- `src/agent_runtime/agent_runtime.py` 的 `get_default_agent()`；
- `src/system/system_runtime.py` 的 `SystemRuntime.agent`；
- `src/chat_session/chat_pipeline/topic_replier.py` 的话题 Agent 选择。

GREEN 必须统一改成从 `get_character_runtime(...).conscious` 取得旧对象。测试中的 SplitRuntime 在公开边界明确分开新门面与旧对象，避免因旧运行时暂时仍返回旧 Agent 而误判兼容通过。TopicReplier 当前只把选择的 Agent 用于非空检查，实际规划/实现仍走 runtime 代理；因此同时断言旧队列效果和不访问新 get_agent，两者缺一都会漏掉该迁移问题。覆盖默认角色、第二角色、原有未知角色回退路径；回退用例只验证取对象路径及原队列编排，不证明真实未知角色业务可以完成。

## RED 证据

工作目录 `server`：

```powershell
D:/Anaconda/envs/lty/python.exe -X utf8 -m pytest tests/agent tests/agent_runtime --collect-only -q
D:/Anaconda/envs/lty/python.exe -X utf8 -m pytest tests/agent tests/agent_runtime tests/domain tests/world -q --tb=no -rN
D:/Anaconda/envs/lty/python.exe -m ruff check tests/agent tests/agent_runtime tests/agent_runtime_support.py tests/conftest.py
```

2026-09-06 收集 38 项新增测试，无跳过。合并回归为 32 failed、550 passed、2 skipped；其中新增测试 32 failed、6 passed，既有 domain/world 为 544 passed、2 skipped。Ruff 通过。

失败原因：新门面及导出未实现、运行时仍返回旧 Agent、空字符串及 falsy 非字符串角色参数回退默认角色、三个旧入口仍调用 get_agent。门面行为用例目前首先在真实运行时返回对象缺少两个方法的明确断言处失败，尚未到达报告断言；没有导入错误、语法错误或环境错误。既有通过项是回归基线，不伪造 RED。

离线装配保留真实 AgentRuntime、CharacterRegistry、AgentRegistry、CharacterRuntime、LuoTianyiAgent 和 MainChat；向量存储、LLM 服务和旧潜意识等协作者使用受控替身，角色资源写入 pytest 临时目录。不会调用真实模型、capability 或生产数据库。

本轮证明空生产注册版本的入口与兼容契约。已注册处理器的成功路由、重复注册、处理中取消、sink 拒绝后的部分结算、在途处理器关闭超时尚无测试证据；这些场景需要内部测试装配支持，不能把当前空注册拒绝测试算作覆盖。版本构造约束由现有 domain 测试覆盖。

## GREEN 证据

RED commit `0601a6d2`，本轮保持其 38 项测试不变。实现空注册门面、严格角色查找及三个旧调用点迁移后，新增测试 38 passed；与 domain/world 合并运行 582 passed、2 skipped。上述 Ruff 命令及门面/AgentRuntime 产品文件检查通过，git diff --check 通过。

通过单次 pytest 插件解除两个指定旧测试文件的全局暂缓标记：`test_runtime_initialization_rollback.py` 为 5 passed；`test_system_runtime_shutdown.py` 为 1 failed，原因是旧测试用 object.__new__ 构造 CapabilityManager，缺少其关闭锁 _stop_lock。该关闭逻辑未在本轮改变，失败未修复；没有修改默认暂缓策略。

原有未覆盖场景仍未实现，本轮 GREEN 仅指这组入口与兼容测试，不表示 #63 全部契约已经交付。

## #63 已注册处理器与在途关闭 RED（2026-09-06）

SPEC：`4c031a4c`，在提交并自审路由调用、单次交付事实和关闭规则后增加测试。该阶段没有修改产品实现。

新增 69 项测试，分布如下：

- `test_handler_registration.py`：19 项，验证精确枚举键、同对象多键、快照注册序列、重复拒绝、非法输入、未知键、START_THINKING 禁止注册。当前先断言 Agent 尚缺少注册装配入口；这些属于接口能力缺失证据，不能替代成功处理的业务 RED。
- `test_handler_dispatch.py`：46 项，通过真实 AgentRuntime.get_agent 的两个业务方法调用装配的受控协作者。覆盖成功计划交付/消费、Action 顺序与终止输出位置、全部 sink 拒绝码、异常映射、回执及输出身份核对、伪造报告/消费拒绝、已确认事实保留、交付后失效、明确部分失败、取消和并发 interaction 隔离、内部错误日志。
- `test_facade_inflight_shutdown.py`：4 项，覆盖 handle/realize 在途时关闭超时和重试、调用任务取消时等待清理、run_sync_owned 同步线程仍运行期间重复 shutdown 不提前释放依赖。

注册协作者只用于模块内测试装配，遵循 SPEC 的 handle/realize 协议；不建立真实业务 Handler。装配参数尚未实现时，测试仍运行原有门面，由真实返回 UNSUPPORTED 与目标行为的差异证明 RED，未提供虚假生产实现。等待事件只用于建立明确并发时序，所有后台调用在 finally 中释放并回收。

实际验证：

- 新增测试最终运行：`python -m pytest tests/agent/test_handler_registration.py tests/agent/test_handler_dispatch.py tests/agent/test_facade_inflight_shutdown.py -q --tb=no`：**68 failed、1 passed**。首次通过的是整计划预检拒绝回归，不制造 RED。
- 增加最后一项同步线程关闭测试前，合并回归 `tests/agent tests/agent_runtime tests/domain tests/world tests/system/test_system_runtime_shutdown.py`：**67 failed、584 passed、2 skipped**。现有 38 项门面/兼容测试和 domain/world 回归保持通过；两项真实网络探测仍跳过。
- 恢复旧 `test_system_runtime_shutdown.py` 到 `tests/system`：SpeechCapability 使用真实空配置构造，旧 CapabilityManager 测试替身补充现行停止锁与状态，原断言不变，单独运行 **1 passed**。这是修复旧测试装配并恢复回归，不是产品 Bug GREEN。
- Ruff 检查新增测试、父 conftest 与该恢复测试通过；git diff --check 通过。

作者自审：SPEC 先于 RED；断言观察报告、sink 接收结果和资源释放边界，不读取路由私有映射；普通协作者 KeyError 不得冒充路由缺失。sink 接收后取消、非法 Handler 报告保留既有回执、重复 shutdown 等待同步清理均有独立测试。真实模型、能力、设备、生产链和持久账本未验证。

## 重复调用方取消 RED（2026-09-06）

初步 GREEN `d21a2aeb` 通过上述 69 项新增测试，完整相关回归为 652 passed、2 skipped。
自审进一步发现调用方连续两次 Task.cancel 可击穿 run_sync_owned 的同步线程清理等待。
新增 `test_repeated_caller_cancellation_cannot_release_sync_dependencies` 从公开门面启动受控同步工作，
首次取消进入清理等待后再次取消，要求 runtime.shutdown 仍超时且不释放依赖；释放同步工作后才能关闭。

对初步 GREEN 执行 `python -m pytest tests/agent/test_facade_inflight_shutdown.py::test_repeated_caller_cancellation_cannot_release_sync_dependencies -q --tb=short`
结果为 1 failed：关闭未抛 RuntimeError，错误返回成功。测试不读取私有任务或改动通用 asyncio helper。

## #63 完整 GREEN（2026-09-06）

门面路由 GREEN `d21a2aeb` 及重复调用方取消 RED `f5765cee` 之后，门面拥有处理器任务，
只转发一次任务取消，重复取消继续等待清理。原 69 项路由/调用/关闭测试和原 38 项入口/兼容测试保持不变，
加上新的重复取消测试，agent/agent_runtime 聚焦为 108 passed。

工作目录 `server`，实际最终验证：

- `D:/Anaconda/envs/lty/python.exe -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system -q --tb=short`：653 passed、2 skipped、1 项第三方 pkg_resources 弃用警告。
- `D:/Anaconda/envs/lty/python.exe -m ruff check src/agent/facade.py src/agent/handlers src/agent_runtime/agent_runtime.py tests/agent tests/agent_runtime tests/system`：通过。
- `D:/Anaconda/envs/lty/python.exe -m compileall -q src/agent/facade.py src/agent/handlers src/agent_runtime/agent_runtime.py`：通过。
- `git diff --check`：通过。

生产路由器装配为空；成功处理与输出使用内部协议的受控协作者验证，没有运行真实业务 Handler、模型或能力。
两项真实网络探测仍跳过。作者自审与后续独立 PR 审核分别记录。

## 处理器实际启动前取消 RED（2026-09-06）

对 `4f822f6d` 提交自审时，用事件循环已排队的令牌取消实证：门面同步入口检查后、
新建处理器任务实际开始前，令牌可以已取消。新增 handle/realize 两项回归要求不调用处理器，
handle 不消费 pending，realize 所有行动仍 NOT_STARTED。
`python -m pytest tests/agent/test_handler_dispatch.py -k cancel_before_worker -q --tb=short`
为 2 failed：handle 错误消费 m2，realize 错误记录首行动完成；两者最终 CANCELLED 状态无法掩盖已启动业务的错误。

## 处理器启动前检查 GREEN（2026-09-06）

保持 `38322bd9` 两项 RED 不变，门面在拥有的任务实际开始时再次检查令牌。
检查通过才创建业务协程；调度期间取消不调用处理器，handle 保留 pending，realize 保留 NOT_STARTED。
调用登记发生在 worker 创建前，解除发生在 worker 正常退出或取消清理结束后。

最终完整命令 `D:/Anaconda/envs/lty/python.exe -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system -q --tb=short`
为 **655 passed、2 skipped**（agent/agent_runtime 共 110 项）。相关 Ruff 与 compileall 通过；测试没有改变原 RED 期望。


## Execution Ledger 逐行动恢复 RED（2026-09-06）

SPEC 为 `25458406`，取消清理可信返回补充为 `15f7b06c`；两个 commit 均已作者自审。本片保留现有 ActionHandler 输出协议，从公开 `realize_action_plan` 和 `AgentRuntime.shutdown` 验证执行账本，不增加真实 Handler。

新增 38 项展开用例：

- `test_execution_idempotency.py`：30 项。覆盖同实例/重建后完成重投、完整计划字段冲突、角色和 execution 作用域、完成前缀带输出和效果后的安全失败/取消继续、恢复预检保留历史、终态优先级、不安全效果/已确认及未知输出、普通异常未知效果、并发加入、跨 Runtime 争用、等待者/拥有者取消、取消清理可信返回及关闭等待。
- `test_execution_storage_recovery.py`：8 项。使用真实 SQLite 检查读取不可用的安全日志、行动结算/发送前/确认后提交失败（处理器吞错也不允许继续）、损坏版本/JSON；由新 Python 进程产生完成结果或在独立外部效果后硬退出，再通过新 Agent 公开重投检查不重复外部效果。
- 原 `test_handler_dispatch.py` 的 realize BACKPRESSURE_TIMEOUT 期望改为 retryable=False；只有 sink 的拒绝不足以证明异常退出的 Handler 没有其他效果。handle 的原有 retryable 期望不变。

工作目录 `server`，运行 `D:/Anaconda/envs/lty/python.exe -X utf8 -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system -q --tb=short`：**37 failed、756 passed、2 skipped**。新增 38 项为 **36 failed、2 passed**，另 1 项为旧契约期望修订产生的 RED。两项首次通过为不同执行/角色独立及等待者取消隔离回归，不伪造失败。两项跳过仍为 world 真实网络探测。

失败均来自公开行为缺失：重复执行而非 ALREADY_COMPLETED、内容冲突未拒绝、错误 retryable、历史前缀丢失、重复 sink 投递、忽略存储故障及进程恢复；拥有者取消后等待者继续挂起产生的有界等待超时同样是目标缺失。没有导入、语法或环境错误。

数据库结构只用于外部故障注入，不断言 SQL 查询步骤；初始无执行表时不会产生反射失败，由公开重投错误行为证明 RED。后台任务均显式释放并回收，新进程有超时且关闭引擎。Ruff 与 `git diff --check` 通过。没有产品代码、完成进度或 GREEN 记录。


## Execution Ledger 逐行动恢复 GREEN（2026-09-06）

SPEC `25458406` / `15f7b06c` 与 RED `c7694619` 保持；38 项新增测试未改动。
Agent 在同一数据库登记执行完整计划身份、运行占用、每项开始/可信结算和累计输出事实，
同实例合并在途调用，重复执行跳过已完成前缀，只有可信且无效果/未知输出的未完成行动安全继续。
取消清理正常返回的结果在受控 worker 内持久化；存储错误即使被处理器吞掉也阻止继续。
日志去除 traceback 源码行，只保留类型和栈位置，避免异常字面量泄漏。

在 server 运行 `D:/Anaconda/envs/lty/python.exe -X utf8 -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system -q --tb=short`：
**793 passed、2 skipped**；包含38项新增执行用例，两个跳过仍为 world 真实网络探测。
Agent、AgentRuntime 和相关测试 Ruff、Agent compileall、git diff --check，以及 Agent SPEC 的 UTF-8、围栏和相对链接校验通过。
独立 Python 进程完成/硬退出恢复和真实临时 SQLite 故障已验证；真实业务 Handler、外部服务、生产数据库未验证。


## Execution Ledger 拥有者取消后等待者事实 RED（2026-09-06）

初步 GREEN `94c295a3` 作者自审发现等待者读取的是加入前快照；拥有者取消时只发布空结果，
会丢弃加入后发生的完成前缀及已确认输出。两个公开入口回归分别验证：等待期间首行动完成后
拥有者在第二行动被取消，等待者保留完成/输出/效果；取消清理可信返回的结算提交失败时，
等待者保留已知 effect_ref，但当前行动必须 FAILED / DEPENDENCY_UNAVAILABLE，不能冒充已持久完成。
对初步 GREEN 执行 `-m pytest tests/agent/test_execution_idempotency.py tests/agent/test_execution_storage_recovery.py -k "cancelled_owner_waiter or cancel_cleanup_settlement_failure" -q --tb=short`
为 **2 failed、38 deselected**；失败分别为丢失 output_started，以及当前项错误 NOT_STARTED。
SPEC 的累计事实、取消可信返回与结算失败条目已覆盖，无新增公开接口。测试仅经公开 realize 和 SQL 提交故障边界观察。


## Execution Ledger 取消等待者事实 GREEN（2026-09-06）

保持 RED `f0fdf077` 不变。拥有者清理后给等待者发布最新执行事实；结算提交失败的当前项
保留已知效果并标为 FAILED / DEPENDENCY_UNAVAILABLE，只有持久完成前缀转换为 ALREADY_COMPLETED。
取消清理中的存储错误日志使用 DEPENDENCY_UNAVAILABLE。
40 项执行用例全部通过；完整相关回归为 **795 passed、2 skipped**，相关 Ruff、compileall、diff 检查通过。
