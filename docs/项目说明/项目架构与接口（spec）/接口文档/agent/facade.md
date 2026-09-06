# Agent 两接口门面契约

状态：#63 的空注册门面入口、运行时缓存与旧入口迁移已实现。已注册处理器路由、处理中的取消及部分结算仍是未实现的契约草案，不能视为可用行为。本文定义本切片的公开行为；领域对象以 [handle 输入](../domain/handle-input.md)、[处理报告](../domain/handling-report.md) 和 [计划与执行](../domain/realization.md) 为准。

## 模块与实例

`server/src/agent/facade.py` 定义 `Agent`，`src.agent` 只导出该公开类型。Agent 的业务方法只有 `handle_stimulus` 和 `realize_action_plan`。构造及内部生命周期协作由 AgentRuntime 使用，业务调用方通过运行时取得实例。

`server/src/agent_runtime` 保持为顶层模块。`AgentRuntime` 初始化时为每个启用角色组装并缓存一个新 Agent，绑定角色身份和所需依赖。装配直接在运行时中完成。`SystemRuntime` 创建 AgentRuntime，并协调其初始化失败清理和关闭。

Agent 不公开旧意识对象、CharacterRuntime、数据库、潜意识、能力管理器或内部处理器，不通过属性转发或 `__getattr__` 暴露旧接口。角色身份绑定后不可更换；一次请求的数据保留在该调用作用域，不写入实例级“当前用户”或“当前交互”字段。不同 interaction 的调用可以并存。

## 公开调用

```python
from src.agent import Agent
from src.domain.agent import (
    ActionPlan, ActionPlanSink, AgentOutputSink, ExecutionContext,
    ExecutionReport, HandleStimulusRequest, HandlingReport,
)

# Agent 的两个异步实例方法：
async def handle_stimulus(
    self, request: HandleStimulusRequest, plan_sink: ActionPlanSink,
) -> HandlingReport: ...

async def realize_action_plan(
    self, plan: ActionPlan, execution_context: ExecutionContext,
    output_sink: AgentOutputSink,
) -> ExecutionReport: ...
```

两个 sink 都由每次调用传入，不保存在共享 Agent 中。公开类和方法提供中文 docstring，说明输入、结果和异常。

## handle 入口

1. 参数必须符合已有领域类型。对象构造时的字段、schema_version 校验仍使用领域构造异常；构造失败不会进入 Agent，也不会产生报告。传入错误的顶层参数类型属于调用错误，抛出 `TypeError`。
2. 进入业务处理前，确认触发刺激及所有 pending 的目标角色集合包含绑定角色。失败返回 `FAILED / CONTRACT_SNAPSHOT_MISMATCH`。快照没有角色字段，角色校验使用刺激的 target_character_ids；handle 的 interaction_id 取自快照。
3. 对有效请求，先检查运行时是否接受工作，再检查调用令牌；已经取消的请求返回 `CANCELLED`，`error_code=None`。两种取消原因都保留在原令牌中，Agent 不改写调用方令牌。
4. 按触发刺激的 `StimulusKind` 精确选择内部处理器，每种 kind 至多注册一个处理器。未注册返回 `FAILED / UNSUPPORTED_STIMULUS`。处理器不支持本次交互时使用 `UNSUPPORTED_INTERACTION`，不把合法输入归为构造错误。
5. 处理器处理的请求、计划和报告保留原请求、角色及交互身份；报告依据修订必须等于输入快照修订。Agent 不根据其他调用维护一个全局“最新 revision”。

入口拒绝时不调用模型、capability 或 sink。报告的 considered 和 retained 都按快照顺序包含全部 pending ID；consumed 和 emitted_plan_ids 为空，reconsider_at 为 None。输入不匹配、不支持和已取消的入口结果均为 `retryable=False`。

处理开始后的计划通过 plan_sink 按正常产生顺序交付；报告只记入已成功接收的计划 ID。取消或失败不抹掉此前成功接收的计划及已形成的结算事实。Agent 不直接修改 stage 的 pending 集合。

## realize 入口

1. 顶层参数类型错误抛出 `TypeError`；领域构造异常保持原约定。
2. plan.target_character_id 必须等于绑定角色，plan.interaction_id 必须等于 execution_context.interaction_id。不匹配返回 `FAILED / CONTRACT_MISMATCH`。
3. plan.basis_interaction_revision 必须等于 execution_context.current_interaction_revision，否则返回 `FAILED / STALE_INTERACTION`。
4. 身份校验通过后检查运行时接受状态和执行令牌。已取消返回 `CANCELLED / CANCELLED`。
5. 按 `ActionKind` 精确选择内部处理器，重复注册使装配失败。开始执行前检查整个计划的行动是否均有处理器；任何一项未注册则整份计划返回 `FAILED / UNSUPPORTED_ACTION`。`StartThinking` 计划由 stage 消费，传入 realize 同样返回 `UNSUPPORTED_ACTION`。

以上入口拒绝均不执行行动、不调用 output_sink。action_results 按计划原顺序包含所有行动，状态均为 NOT_STARTED、单项 error_code 为 None、无已提交效果；output_started=False、retryable=False。执行身份取自 context，计划身份取自 plan。

接受后的行动按计划顺序执行；失败或取消后停止启动后续行动。报告记录已完成、失败或取消的行动及其实际效果，剩余行动为 NOT_STARTED。输出保持正常调用顺序及 MessageEndOutput 的位置；sink 接收回执不代表播放完成。

## 错误、取消与关闭

- sink 明确拒绝沿用 `SinkRejectedError`；不将拒绝记作成功接收。STALE_INTERACTION、SINK_CLOSED、BACKPRESSURE_TIMEOUT 映射为同名处理或执行错误码，其中只有 BACKPRESSURE_TIMEOUT 的 retryable=True。IDENTITY_MISMATCH、CONTENT_CONFLICT 在 handle 中映射为 INTERNAL_ERROR，在 realize 中映射为 CONTRACT_MISMATCH；UNSUPPORTED_OUTPUT 在 handle 中映射为 INTERNAL_ERROR，在 realize 中保留同名码。这些错误的 retryable=False。
- 协作者抛出的 `TimeoutError` 转为 `PROVIDER_TIMEOUT`，retryable=True；未分类的普通异常转为 `INTERNAL_ERROR`，retryable=False。失败报告保留已经确认的输出、计划和效果，异常详情留在内部日志。
- 协作式取消在进入处理器前、每次等待返回后以及启动下一次计划交付或行动前检查。已经发起的外部效果不能因令牌取消被描述为未发生。
- 调用任务本身收到 `asyncio.CancelledError` 时，在清理该调用拥有的工作后传播取消，不包装为 INTERNAL_ERROR，也不承诺一定返回报告。
- `AgentRuntime.shutdown()` 开始时停止所有新 Agent 接受工作，再等待已接受调用退出，最后释放它们使用的资源。关闭期间新调用返回 `FAILED / DEPENDENCY_UNAVAILABLE`、retryable=False，其他字段按入口拒绝规则填写。
- 关闭等待沿用运行时的有界超时；超时明确抛出 `RuntimeError`，保留仍在运行的工作和其依赖供后续关闭重试。不得把仍在运行的同步工作当作已关闭，也不得在它使用依赖时释放依赖。成功关闭后重复 shutdown 幂等；已取得的 Agent 引用仍拒绝新工作。
- 日志关联角色、request_id 或 execution_id、interaction_id、结束状态及错误码，不记录完整刺激内容、记忆或密钥。观测不增加业务方法或报告字段。

## 本版装配行为

本切片只新增 `agent/facade.py` 作为门面实现文件，并在现有 AgentRuntime 中组装；内部注册和接受状态属于实现细节。本版生产装配的刺激、行动处理器集合为空，因此合法且未取消的请求返回对应 UNSUPPORTED 错误。领域类型可以构造不等于该行为已经获得运行时支持。

## 验证入口

测试通过 AgentRuntime.get_agent 和上述两个业务方法观察结果。门面测试放在 `server/tests/agent`，运行时与兼容入口测试放在 `server/tests/agent_runtime`；内部测试装配可以注入受控协作者，外部契约测试不取得或断言私有注册表。

| 场景 | 可观察结果 |
| --- | --- |
| 同角色重复查找、不同角色查找 | 同角色同实例，不同角色不同实例 |
| 未知、禁用、空字符串角色 ID | KeyError，不回退默认角色 |
| 包导出与实例公开业务面 | 只导出 Agent，只提供两个业务方法，不泄漏旧对象 |
| 目标角色或交互不匹配、修订不一致 | 稳定失败，sink 与处理器无调用 |
| 未注册刺激或计划中任一行动 | UNSUPPORTED，完整保留 pending 或全部 NOT_STARTED |
| 已取消及等待期间取消 | 不启动后续工作，已确认事实不丢失 |
| 注册冲突、协作者异常、sink 拒绝 | 装配失败或明确错误报告，无通用 LLM 回退 |
| 关闭、新调用、关闭超时与重试 | 停止接受、有界等待、保留未完成工作和资源、成功关闭幂等 |
| 旧兼容入口 | 仍取得旧 LuoTianyiAgent，旧聊天方法可以调用 |

版本不兼容继续由已有领域构造测试验证，不通过导入失败或绕过不可变对象构造来制造 RED。
