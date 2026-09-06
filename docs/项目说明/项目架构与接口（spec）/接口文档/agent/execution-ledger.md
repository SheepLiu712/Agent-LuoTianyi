# Execution Ledger 与逐行动恢复契约

状态：已实现。公开入口保持 `Agent.realize_action_plan(plan, execution_context, output_sink)`，输入、输出和错误使用现有 domain 类型。

## 所有权与装配

`agent/ledgers/execution_ledger.py` 保存执行身份及逐行动事实，`_execution_codec.py` 校验持久事实；`agent/execution.py` 协调准入、按行动执行和受限输出。AgentRuntime 通过已有 `sql_session_factory` 装配参数注入 `database_manager.open_sql_session`，账本使用原数据库中的独立表，关闭自己创建的 SQLAlchemy Session。事务只覆盖登记、读取和结算，不跨越 Handler 或 sink 的 await。初始化失败沿用 AgentRuntime 初始化回滚。

ActionHandler 保持 `realize(action, execution_context, outputs: AgentOutputSink) -> ActionResult`。门面创建每行动受限 outputs；处理器不能取得外部 sink 或账本。生产路由保持为空。Agent 包只导出 Agent，业务方法仍为两个。

## 身份与入口

持久唯一键是 `(character_id, execution_id)`。指纹包含完整 ActionPlan：具体类型及全部字段，包括 plan_id、origin_request_id、plan_ordinal、target_character_id、interaction_id、basis_interaction_revision、source_stimulus_ids 的顺序及每个 Action 的具体类型、全部嵌套字段和顺序。使用确定、版本化编码，不使用 Python hash、repr 或 pickle。execution context 的令牌对象、状态和取消原因不参与身份；current_interaction_revision 是每次准入事实。

相同键不同指纹返回 `FAILED / CONTRACT_MISMATCH / retryable=False`，不调用 Handler/sink、不覆盖原记录，不把原计划的行动和效果泄漏到冲突报告。不同角色可独立使用相同 execution_id；不同 execution_id 独立执行。

顶层类型错误抛 TypeError；计划包含编码白名单以外的具体类型时返回 INTERNAL_ERROR、无投递；绑定角色或 plan/context 交互身份错误，以及运行时停止接受时，沿用门面的入口拒绝，不读取其他执行事实。接受状态通过后先读取匹配执行，再检查当前 revision、令牌和全计划路由。首次执行的修订过期、预取消、任一行动未注册均零行动、零输出，不占用该 execution；预取消报告保持 retryable=False，换新令牌仍可首次执行。

已有匹配记录全部已完成，或者已有不可安全继续的可信失败时，直接读取既有终态；完成项转换为 ALREADY_COMPLETED，保留 effect_ref、不可逆标记和累计 output_started，retryable=False。新的 revision、令牌或路由集合不改变已经发生的终态事实。对于仍可安全继续的执行，准入拒绝只阻止本次新动作：旧 revision 返回 STALE_INTERACTION，未注册返回 UNSUPPORTED_ACTION，预取消返回 CANCELLED；完成前缀仍为 ALREADY_COMPLETED，其余为本次 NOT_STARTED，retryable=False。存储中原可信失败保留，准入拒绝不覆盖它；后续合法调用仍可从该安全位置继续。output_started 表示已确认接收事实，False 不证明未知输出没有发生。

## 持久执行与恢复

数据库原子取得执行权，随后按计划顺序处理每项 Action。登记内容包含格式版本、计划指纹、运行占用、逐行动状态、可信 ActionResult 和逐行动输出事实。可信事实使用显式 JSON/标量编码，解码只接受已知类型和字段，不动态加载类型。账本保存恢复需要的效果引用，不保存令牌、Handler、sink 或协程。

每项行动在调用业务处理器前持久标记 STARTED。可信返回必须是属于当前 action_id 的有效 ActionResult，不能是 NOT_STARTED。单项结算提交成功后才能开始下一个行动，完成报告也必须在结算成功后返回。成功结算的 COMPLETED/ALREADY_COMPLETED 在同 execution 重投时均报告 ALREADY_COMPLETED，原输出和外部效果不重做；从第一个允许安全开始的未完成行动继续。

| 行动事实 | 同 execution 的安全继续 |
| --- | --- |
| NOT_STARTED | 可在准入检查通过后开始 |
| COMPLETED / ALREADY_COMPLETED | 保留结果，跳过执行 |
| 可信 FAILED/CANCELLED，未提交效果且本行动没有已确认或未知输出 | 允许再次执行该行动 |
| 可信 FAILED/CANCELLED，已有不可逆效果、已确认输出或未知输出 | 保留原失败，retryable=False，不重做 |
| STARTED，缺少可信结算 | 无法证明未发生效果，DEPENDENCY_UNAVAILABLE、retryable=False，不接管执行 |

可信无效果失败的 retryable 表示原 execution 可安全继续，而非错误码属于某个固定集合；取消后使用新令牌也能继续。已完成前缀的效果与输出不阻止后续安全行动重试。普通异常、超时、伪造返回或任务取消都不能证明本行动无副作用，即使 output_started=False 也不自动重跑。首次普通异常仍按门面稳定错误映射报告本次失败，retryable=False；后续读取未知 STARTED 时返回依赖不可用。未知行动报告为 FAILED/DEPENDENCY_UNAVAILABLE，后续 NOT_STARTED，不把“没有可信效果引用”解释为效果不存在。

失败或取消立即停止启动后续行动。可信返回的 FAILED/CANCELLED 保留真实 effect_ref、不可逆标记和输出事实。处理器返回完成后令牌取消，保留该完成事实，整体 CANCELLED、后续 NOT_STARTED；若仍有未开始行动则 retryable=True，新令牌从其继续。调度期间令牌取消且业务处理器尚未进入时，当前行动可恢复为 NOT_STARTED。

## 输出事实与重试安全

受限 outputs 仍校验 execution_id、interaction_id、action_id，以及回执的 execution_id、sequence_no。外部 emit 前先持久记录本行动存在尚未确认的投递；提交失败不调用 sink。有效 ACCEPTED/ALREADY_ACCEPTED 回执先保存已确认事实，再返回和检查令牌。output_started 只表示已确认接收，不把未知投递计成已确认。

SinkRejectedError 表示此次明确没有新增接收；可清除此轮新产生的未知标记，但不能清除更早的已确认或未知投递。普通异常、超时、错误回执、投递中 task 取消均保留未知状态。处理器吞掉投递异常并返回“无效果失败”不能使未知输出变得可重试。未知输出不得因外部接收器没有确认而自动重投。多个 emit 的已确认及未知事实是累计关系，后一轮拒绝不能覆盖前一轮。

已确认回执的本地写入失败时，本次报告保留已观察到的 output_started=True，但禁止继续行动；持久未知状态阻止以后重做。单项结算失败同样保留本次可信效果与接收事实，整体以 DEPENDENCY_UNAVAILABLE 表达无法安全结算；必要时将本项状态改为 FAILED 以符合报告状态关系，不能宣称完成已持久化。

## 并发、取消、存储失败

同一 Agent 的相同 execution 并发调用加入同一次执行，取得同一报告；等待者的 sink 不被使用。等待者 task 取消只取消等待，不能取消拥有者或其他等待者。不同内容立即冲突，不等待；不同 execution 可并行。

其他 Agent/Runtime/进程看到运行占用而没有本地拥有者时，不调用 Handler/sink，返回 DEPENDENCY_UNAVAILABLE/retryable=False，并保留可读取的完成前缀和输出事实。拥有者可信结算后释放运行权，后续调用按逐行动规则恢复。进程硬退出留下 STARTED 时不能根据时间或内存为空推断无效果。

拥有者 task 取消沿用门面受控清理与 CancelledError 传播规则，重复取消只向处理器转发一次。若处理器在取消清理中正常返回可信 ActionResult，先持久保存该结果，再向拥有者传播 CancelledError；已完成行动以后不重做。无可信结果的在执行行动保持未知；并发等待者取得依赖不可用报告，不接管任务。所有已进入账本的调用及等待者计入运行时在途集合；shutdown 停止接受后等待清理与结算，超时保留依赖供后续关闭重试。

登记、读取、开始标记或结算失败均返回 DEPENDENCY_UNAVAILABLE/retryable=False。登记/开始失败不开始外部工作；结算失败保留已知事实并阻止重做。未知版本、损坏 JSON、计划指纹或行动身份不一致、非法状态组合均拒绝恢复，不丢弃记录重建。使用 utils/logger.py 记录角色、execution、interaction、稳定错误码、异常类型和栈文件、行号和函数名，省略源码行、局部变量、异常原文及计划正文。

## 公开验证

测试从 realize_action_plan 与 AgentRuntime.shutdown 观察，使用真实临时 SQLite、内部受控处理器和外部 sink；数据库故障只在 SQL 会话边界注入。

- 同实例、重建 Runtime、新 Python 进程重投完成计划，返回 ALREADY_COMPLETED，输出与独立外部效果不重复。
- 完整计划字段冲突、角色作用域、并发同键及异键、等待者取消、拥有者取消和关闭等待。
- 已完成前缀带输出及效果，下一行动在可信无效果失败或取消后可安全继续。
- 已确认/未知输出或已提交效果后失败不能重做；普通异常与硬退出不能被误判为安全失败。
- 旧 revision、预取消和路由拒绝保留已有前缀；存储/提交失败、损坏记录不重新执行。
