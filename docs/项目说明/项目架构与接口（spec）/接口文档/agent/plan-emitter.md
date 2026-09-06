# PlanEmitter 与计划投递恢复契约

状态：已实现。公开入口保持 `Agent.handle_stimulus(request, plan_sink)`；结果使用现有 HandlingReport，外部接收器使用现有 ActionPlanSink。

## 所有权与内部输入

`agent/planning/emitter.py` 定义内部 PlanEmitter 和 ActionPlanDraft，`agent/planning/identity.py` 保存稳定身份与计划编码规则。持久 outbox 位于 `agent/ledgers/plan_outbox.py`，使用 AgentRuntime 已注入的 SQLAlchemy 会话工厂与同一数据库。Handler 只能取得本次 emitter，不能取得外部 sink、账本或其他请求的投递对象。Agent 包仍只导出 Agent，生产处理器注册表保持为空。

```python
@dataclass(frozen=True, kw_only=True)
class ActionPlanDraft:
    source_stimulus_ids: tuple[str, ...]
    actions: tuple[Action, ...]

class PlanEmitter:
    async def emit(self, draft: ActionPlanDraft, *, ordinal: int | None = None) -> PlanReceipt: ...
```

Draft 是完整不可变计划的内部语义输入，复用现有 domain Action；不携带角色、请求、交互、修订、公开计划 ID 或 ordinal。字段要求与 ActionPlan 的对应字段一致；错误类型、空行动集合、重复身份和非法行动组合在 sink 前拒绝。source 允许为空，非空时只能引用触发刺激及当前 pending。完整 ActionPlan 的领域约束仍适用，包括 StartThinking 只能是 ordinal 0 的独立计划。

默认 emit 为下一份完整计划分配从 0 连续增长的 ordinal；计划在投递前固定身份与完整值。显式 ordinal 只能引用本次已创建槽位：非 int（包括 bool）、负数、跳号均拒绝。已有槽位同 draft 且已确认时返回同 plan_id 的 ALREADY_ACCEPTED，不再调用 sink；内容不同时抛契约错误，不能覆盖计划或吞掉已确认事实。未确认槽位存在时不能创建下一槽位，同槽位可重投原计划。Handler 按正常顺序 await emit；同次并发 emit 必须串行化，先完成的槽位仍决定后续分配。

稳定 plan_id 由版本化请求身份、绑定角色与 ordinal 确定；fingerprint 对完整不可变计划语义做确定编码。相同身份与 ordinal 下内容不同是冲突，不能通过改变 plan_id 掩盖。完整计划按显式白名单 JSON 编码，可跨 Python 进程重建 Action 具体类型及字段；禁止 pickle、对象 repr、动态类型加载或只保存 ID。计划正文是恢复投递所需数据，账本不保存原刺激正文、令牌或 sink。

## 投递事实

每次外部 emit 前检查当前令牌，并在短事务内保存完整计划、fingerprint 和投递状态；事务提交后才调用 sink。数据库事务不跨越 sink await。保存失败不交付，不在内存中假装已登记。

| 外部结果 | 接收事实与处理 |
| --- | --- |
| 有效 ACCEPTED / ALREADY_ACCEPTED，plan_id 匹配 | 先持久化确认，再返回回执；emitted_plan_ids 按 ordinal 包含确认计划一次 |
| BACKPRESSURE_TIMEOUT 明确拒绝 | 本次没有新增接收，保留原计划待重投，公开错误为 BACKPRESSURE_TIMEOUT |
| 其他 SinkRejectedError | 本次没有新增接收，终止该槽位重试，按既有门面错误映射结算 |
| 普通异常、TimeoutError、回执类型或 plan_id 不匹配 | 接收结果未知，保留完整计划待重投；既有错误映射不变，回执错误为 INTERNAL_ERROR |
| 外部确认后本地确认写入失败 | 保留原计划及有效回执；结算事务补齐确认事实与报告，本次仍返回 DEPENDENCY_UNAVAILABLE。补齐成功后该计划不再投递；补齐也失败则保留占用 |

“是否仍待重投”与累计已知接收事实是不同信息；已确认、明确未新增及尚未排除的历史未知分别记录。一次未知结果之后再遇永久拒绝不能据此断言历史未接收。报告中的 emitted_plan_ids 只列已确认事实，不把未知说成已接收或未发生。永久拒绝不自动再次投递；恢复遇永久拒绝时终态保留原认知消费字段，错误码采用最后阻止投递的拒绝映射，retryable=False，保留所有真实确认 ID。

sink 等待返回后，先保存成功回执，再检查协作取消；取消不能抹掉已接收计划。取消后不发新计划。未确认投递失败后，emitter 不允许创建新槽位；Handler 可以返回合法部分结算，门面仍以失败状态表达未完成投递。调用结束关闭 emitter 并释放 sink；保留该对象不能在调用外继续投递。

## 请求终态与恢复

已有版本的请求表与无 outbox 终态继续可读，并与新增计划记录共存；升级不能删除旧表、清空请求或要求重建数据库。历史终态仍直接返回，不能为补建 outbox 重新运行 Handler。

请求 fingerprint、入口角色/接受状态检查、首次认知处理权和并发等待沿用 [Request Ledger](request-ledger.md)。没有待恢复计划的完整报告仍永久缓存，不重跑 Handler。存在待恢复 outbox 时，门面在 Handler 及其清理退出后保存 provisional report 和可恢复状态，成功提交后才允许公开重投恢复。

合法 Handler 返回保留已验证的 considered、consumed、retained、reconsider_at；只有异常退出或伪造结果才全部 retained。尚有未确认投递时不能将 Handler 的 COMPLETED 当成全部成功：provisional 为 FAILED，携带实际投递错误和已确认计划 ID。retryable=True 在此表示还有可重投的持久计划，而不是授权重新执行 Handler。恢复确认全部计划后，保留原认知 FAILED、错误码及消费事实，仅补充已确认 ID，并将 retryable=False 后保存终态；不能凭投递恢复宣称中断的认知已完成。

公开相同请求重投：

1. 通过相同 fingerprint、角色与运行时接受校验。终态返回原报告。可恢复状态先检查本次令牌，已取消不投递且保留待恢复状态，返回 CANCELLED 的本次观察结果；本次 CANCELLED 观察不覆写 provisional 的原失败与消费事实，旧令牌不永久取消后续重投。
2. 原子获得恢复权，只按 ordinal 投递已存计划，使用本次 sink 和令牌；不再次解析/调用 Handler，不生成新计划，不改变原请求语义。
3. 相同 Agent 并发重投等待同一恢复；其他实例已占用恢复时按未完成占用拒绝，不能同时开始交付。恢复完成后可读终态。
4. 普通投递失败保持可恢复。恢复任务取消须等待受控 sink 清理，保存未知或已确认事实并释放为可恢复，再传播 CancelledError；不得把普通取消造成永久占用。真正进程硬崩、状态写入失败或不存在可信 provisional report 时保持占用，不凭内存为空或时间推断可以接管认知。

有效回执已经确定接收，本地确认写入失败不把这项事实变成未知。首次处理或恢复结束时，保存报告的同一事务补齐 emitter 在本次调用实际校验成功的回执；不能仅根据 Handler 返回的 emitted_plan_ids 推断确认。补齐成功且没有其他待重投计划时，保存 FAILED / DEPENDENCY_UNAVAILABLE / retryable=False 终态，保留已确认 ID；重建 Agent 重投读取该终态，不再次调用 sink。仍有其他未知或背压待重投计划时只恢复这些计划，不重投已补齐确认的槽位。补齐与报告保存任一失败则整个事务不提交，保留占用、拒绝接管。拥有者在 Handler 尚未结束或任务取消而未形成可信结算时，即使 outbox 存在也不能自动重放，否则无法知道认知是否会继续产生效果。恢复调用计入运行时在途所有权，关闭不能提前释放数据库或遗留 sink 任务。

恢复保证重新提交相同 plan_id、ordinal 和完整内容。调用方显式重投可能导致接收器再次收到计划；现有 ActionPlanSink 只在识别重复时返回 ALREADY_ACCEPTED，不能据此声称任意新连接或新接收器都恰好一次。测试使用持久去重 Fake 证明可识别的重复不会新增接收，也单独观察重复调用确实携带相同内容。

## 错误与日志

内部草稿、ordinal 或重投内容冲突映射 INTERNAL_ERROR，保留已确认计划和可信消费事实。外部异常沿用门面错误映射；有持久待重投项时 retryable=True，全部确认或永久拒绝后 False。存储失败且无可信可恢复状态时 retryable=False。

通过 `utils/logger.py` 记录 character_id、request_id、interaction_id、plan_id、ordinal、稳定错误码、异常类型及栈位置（文件名、行号和函数名）。日志不格式化 traceback 源码行、局部变量或原异常链，省略协作者异常原文、计划正文、刺激正文、完整序列化数据及连接凭据。源码中的异常字面量同样不得进入日志；仅替换异常消息不满足这一约定。处理器捕获 emit 异常不应使投递错误消失于日志。

从公开 handle 验证：接收器在带有字面量的源码行抛出异常，并携带原始 cause；处理器捕获 emit 异常并返回合法消费结算。报告保留失败状态、错误码和消费事实；格式化后的实际日志保留投递身份、异常类型及接收器栈位置，不包含源码行、异常正文或 cause 正文。

## 验证入口

从公开 handle 与 AgentRuntime.shutdown 观察，使用临时 SQLite、真实路由、受控内部 Handler 与接收器：零/单/多计划、稳定身份、已有 ordinal 的同值/冲突、非法草稿、StartThinking 首计划、取消前后、明确拒绝与背压、未知接收/错回执、写入失败、重建 Agent 和新 Python 进程恢复、部分消费保存、恢复并发及取消后重试。终态重复无交付；处理中占用无接管；存储故障不静默重跑。生产业务处理器及外部真实队列不是这些离线测试的证据范围。
