# Agent 门面入口测试

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
