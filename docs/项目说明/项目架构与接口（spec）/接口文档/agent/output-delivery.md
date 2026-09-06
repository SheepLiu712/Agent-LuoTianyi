# 输出身份、持久序列与安全投递

状态：输出生产者与持久序列已实现；本文的仅投递恢复及最终结算补齐为目标契约，尚未实现。公开入口为 `Agent.realize_action_plan(plan, execution_context, output_sink) -> ExecutionReport`；领域输出、回执、错误和报告沿用 [realization](../domain/realization.md)。

## 所有权和调用

`agent/outputs/drafts.py` 定义私有不可变、关键字构造的草稿；`agent/outputs/emitter.py` 负责身份分配、串行投递与回执处理；`agent/ledgers/output_outbox.py` 保存完整输出和投递事实，显式编码辅助文件放在同目录。`agent/execution.py` 决定重入安全行动或只恢复已生成输出，并阻止未完成交付后的新行动。会话工厂沿用 Execution Ledger 的运行时注入，数据库事务不跨越外部 await。

ActionHandler 的内部参数为 `outputs: OutputEmitter`，调用 `await outputs.emit(draft) -> OutputReceipt`。Handler 不填写 interaction_id、execution_id、action_id 或 sequence_no，也不能取得外部 sink 和账本。输出对象在处理器清理退出后失效。Agent 包仍只导出 Agent，两个公开业务方法保持不变，生产处理器注册集合为空。

| 私有草稿 | 字段 | 形成的领域输出 |
| --- | --- | --- |
| TextFinalDraft | delivery、text | TextFinalOutput |
| AudioChunkDraft | delivery、data: bytes、framing | AudioChunkOutput |
| MessageEndDraft | delivery、status、error_code | MessageEndOutput |
| ExpressionDraft | delivery、expression: ChangeExpression | ExpressionOutput |

OutputDraft 表达以上四类的联合；字段含义与领域输出相同。只接受这四种具体草稿和合法领域值，未知类型/非法内容返回 INTERNAL_ERROR，完整 AgentOutput 不能作为草稿绕过身份分配。值校验在分配槽位与调用 sink 前完成。delivery 与音频字节无损保留，framing、表情、消息终止状态和错误码均不重解释。

## 身份、序列和存储

每个输出绑定当前 plan 的 interaction、context 的 execution 和正在执行的 Action。持久唯一键为 `(character_id, execution_id, sequence_no)`，序号在整个 execution 内从零连续递增，跨 Action、输出类型和 Runtime 重建保持同一序列。不同角色和 execution 独立编号。

槽位先保存完整规范 payload 和指纹，再调用外部 sink。编码有明确版本及类型白名单，保存所有身份、呈现方式和具体字段，audio data 使用无损字节编码；不使用 repr、pickle 或按存储字符串动态导入。槽位分配与 next_sequence 更新原子提交，失败不会先发出输出。读历史时验证版本、完整字段、指纹、行动身份及顺序、连续序号和状态关系；损坏记录返回 DEPENDENCY_UNAVAILABLE/retryable=False，不删除后重建。

旧版 Execution Ledger 只有逐行动 confirmed/unknown 布尔值，没有完整输出与 next_sequence。旧记录全部可信完成且无未知输出时，可读取 ALREADY_COMPLETED 终态并保留 output_started，不要求重建输出。旧记录尚需继续，且曾有 confirmed/unknown 输出时，无法确定下一序号，返回 DEPENDENCY_UNAVAILABLE/retryable=False、无新行动及输出；不能把空 outbox 当作从未输出。旧记录没有任何 confirmed/unknown，且行动原本允许安全继续时，可以从 sequence=0 开始。新版持久格式必须可识别其输出序列完整性，不能仅凭当前 outbox 是否为空判断旧历史。

每次 emit 串行执行，包括同一 Handler 并发提交的 emit。一个槽位未确认时不能开始后续槽位。新草稿优先匹配当前行动既有的安全 pending 槽位：同内容投递原存储值，不重新生成输出；不同内容返回 CONTRACT_MISMATCH、retryable=False，不覆盖旧值或调用 sink。冲突封闭本次后续输出和行动，即使 Handler 吞错也不能跳过该槽位。确认成功后才允许分配下一槽位；已确认槽位始终保留其原内容。

## 投递事实

| 状态 | 事实 | 同 execution 再调用 |
| --- | --- | --- |
| PREPARED | 已保存完整值，尚未开始外部 emit | 按下方行动结算规则重入 Handler 或仅投递存储原值 |
| REJECTED | 明确未新增接收，且没有更早未知接收 | 按下方行动结算规则重入 Handler 或仅投递存储原值 |
| UNKNOWN | 已进入外部 emit，未取得可信接收或明确拒绝结果 | 不重投、不跳过、不重跑行动 |
| ACCEPTED | 有效 ACCEPTED/ALREADY_ACCEPTED 回执已确认接收 | 永不再调用外部 sink |

外部 emit 前先持久写 UNKNOWN；失败时不调用 sink。有效回执必须匹配 execution_id、sequence_no；先记录已确认事实再返回并检查令牌。SinkRejectedError 仅证明本次没有新增接收，不能消除更早 UNKNOWN。普通超时、错误回执、连接异常及投递中任务取消均保持 UNKNOWN；即使 Handler 吞错并返回 COMPLETED，也不能报告整个 execution 完成、开始后续行动或允许重投。首次调用保留已捕获异常的稳定映射，例如超时 PROVIDER_TIMEOUT、错误回执 INTERNAL_ERROR；任务取消仍传播 CancelledError。后续读取未知输出返回 DEPENDENCY_UNAVAILABLE/retryable=False。

有效回执后本地确认提交失败，本次保留 output_started=True，停止本次新工作并报告 DEPENDENCY_UNAVAILABLE/retryable=False。Handler 最终返回可信 ActionResult 时，最终结算事务原子补齐已经校验的回执与结果；仅投递恢复使用账本中已有的可信结果完成同样补齐，不要求重新运行 Handler。补齐成功后，后续调用读取已确认事实，不再次发送；补齐仍失败则持久 UNKNOWN 保守阻止重投。即使补齐成功，本次仍报告存储失败，不开始下一行动。

完整 payload 首次保存失败时没有可恢复输出值，即使 Handler 吞错返回 COMPLETED、随后数据库恢复，也不能只保存该完成结果；保留未可信结算的 STARTED，后续 DEPENDENCY_UNAVAILABLE，不生成空 outbox 的成功终态。PREPARED/REJECTED 的完整值已持久保存，但本轮 UNKNOWN 标记提交失败时，尚未调用外部 sink；最终可信结算可以保存原 safe pending 状态与可信结果，后续按行动分流恢复。本次仍停止新工作并报告 DEPENDENCY_UNAVAILABLE/retryable=False。最终结算再次失败时不得宣称已恢复。此规则同样适用于仅投递恢复，不把未实际调用 sink 的内存 UNKNOWN 当作接收事实。

output_started 仅表示该 execution 曾确认接收过输出，未知接收不会令其变 True。已有 confirmed 后又出现 UNKNOWN，仍保持 output_started=True。当前接收协议没有跨连接去重保证；本机制只重投可证明未接收的原值，不借任意 sink 声称恰好一次投递。

## 行动结算和安全继续

Action 的可信结果与其输出接收事实分别保存。完成 Action 的外部效果不重做，输出 pending 也不能被 ActionResult.COMPLETED 掩盖。存在 pending 时不能启动下一 Action；一次调用不会在同一明确拒绝后自动循环补投。Handler 可以在同次调用捕获明确拒绝，再次 emit 同一草稿复用该槽。

| 已有行动事实 | 下一次同 execution 调用 |
| --- | --- |
| 完成，所有输出已确认 | ALREADY_COMPLETED，跳过 Handler 与 sink，继续后续安全行动 |
| 可信 FAILED/CANCELLED，无不可逆效果且本行动没有 confirmed/unknown | 重入 Handler；首次 emit 复用旧 safe pending 槽位；先运行 Handler，再由它提交原草稿 |
| 可信 COMPLETED/ALREADY_COMPLETED，有 safe pending | 只投递存储原值，不重跑 Handler；确认后报告 ALREADY_COMPLETED，再继续后续行动 |
| 可信 FAILED/CANCELLED，已有不可逆效果或 confirmed，且有 safe pending | 只投递存储原值，不重跑 Handler；确认后保留原失败/取消、错误与效果，后续行动 NOT_STARTED |
| 可信 FAILED/CANCELLED，已有不可逆效果或 confirmed，且没有 pending | 保留原终态，retryable=False，不重跑 Handler 或调用 sink |
| 存在 UNKNOWN，或 STARTED 没有可信 ActionResult | DEPENDENCY_UNAVAILABLE/retryable=False；不接管 Handler 或输出 |

safe FAILED/CANCELLED 重入时如果未 emit 旧 pending 就返回 COMPLETED，仍保存 pending，不丢弃、不跳号；本次返回未完成交付且 retryable=True，不开始下一行动；后续调用转为仅投递恢复，确认后才能继续。已可信完成的 Handler 不再重跑。新的可信结果为失败时继续按上表判定。

可信完成但交付被明确拒绝时，本次报告 FAILED，使用拒绝映射错误并保留效果；报告中该行动以 FAILED 表达未完成交付，账本仍保留处理器可信完成结果。可信失败/取消与 pending 并存时保留其原状态和错误。retryable=True 表示仍有安全行动或 safe pending 可以继续，可能只剩投递恢复；仅投递恢复成功不能把可信业务失败变成完成，恢复完仍有不可安全重入的失败时 retryable=False。一次恢复调用遇明确拒绝只尝试一次，原 safe pending 留待下次，不自动循环。存储故障报告 retryable=False。

已有完成前缀的输出、效果和序列不妨碍后续安全行动重入。没有 pending 且无需新工作的终态沿用历史优先规则；安全行动和仅投递恢复都必须再次通过 current revision、当前令牌和全计划路由检查，后续行动未注册也拒绝当前补投。运行时停止接受沿用 facade 的入口拒绝，不读取账本；已经接受的恢复计入关闭等待。

恢复准入拒绝只影响本次报告，retryable=False，不投递、不覆盖账本原业务结算。已可信完成的行动即使留有 safe pending，仍以 ALREADY_COMPLETED 保留效果；尚未开始行动为 NOT_STARTED。仅投递恢复的可信 FAILED/CANCELLED 行动，用本次拒绝对应的状态和错误码投影该项，保留 effect_ref、不可逆标记和累计 output_started，使单项与整体报告符合领域约束。安全 Handler 重入的准入拒绝沿用原有 NOT_STARTED 投影；之后合法调用仍可恢复并返回原业务失败。

仅投递恢复遇新的未知接收或存储故障，同样只将本次报告投影为对应稳定错误并保留已知效果/接收事实，不能覆写账本原 ActionResult。超时为 PROVIDER_TIMEOUT、错误回执为 INTERNAL_ERROR；后续 UNKNOWN 读取为 DEPENDENCY_UNAVAILABLE，均 retryable=False。补投成功或明确拒绝时，可信 FAILED/CANCELLED 保留原状态和错误；完成行动被明确拒绝则按拒绝映射报告未完成交付。

## 在途、取消和日志

Handler 调用与仅投递恢复都取得 Execution Ledger 的原子执行权。同实例同 execution 并发者加入拥有者；等待者的 sink 不使用，等待者取消不取消拥有者。其他 Runtime/进程不接管在途工作。等待者观察拥有者结束后的最新接收、效果和结算事实。

拥有者任务取消只向正在运行的 Handler 或恢复 sink worker 转发一次，重复取消仍等待清理退出后传播 CancelledError；清理正常返回有效 receipt 时先持久确认，返回可信 ActionResult 时先持久结算。仅投递恢复始终保留已有 ActionResult，不以未开始 Handler 为由重置历史。取消中没有可信回执的投递保持 UNKNOWN。协作令牌在 emit 前及确认后检查，确认后取消不抹掉接收事实。在途调用与等待者均计入 AgentRuntime.shutdown 的等待，超时保持依赖可用。

输出错误通过 utils/logger.py 记录角色、execution、interaction、action、sequence、稳定错误码、异常类型及栈位置；不记录输出正文、音频 bytes、异常原文、局部变量和源码行。

## 公开验证

测试入口为公开 realize_action_plan 与 AgentRuntime.shutdown；使用真实临时 SQLite、受控内部 Handler 与外部 sink，数据库故障在 SQL 会话边界注入。

- 四种输出字段与完整音频保真，跨 Action 连续编号，并发 emit 按 await 串行发送。
- 完成前缀跨 Runtime 不重发；safe pending 同槽重入与内容冲突，未再次 emit 不能丢弃。
- 可信完成/不安全失败只恢复原 payload，不重做效果；恢复后继续的行动沿用连续序号，失败不伪造成完成。
- 恢复准入保留原结算；全计划路由、同实例等待者、跨 Runtime 占用及重复取消清理都遵守原子所有权。
- ack 临时故障在最终结算补齐；已保存 payload 的尝试标记失败与首次 payload 丢失严格区分。
- 新 Python 进程恢复完整音频；恢复 sink 及等待者退出前 shutdown 不释放依赖。
- UNKNOWN、错误回执、取消及进程硬退出不自动重投；确认后存储失败仍保留本次已知事实。
- 旧存储历史输出序列不可猜测；损坏、缺号、缺失输出记录均拒绝继续。
