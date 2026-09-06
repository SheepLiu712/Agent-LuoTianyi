# PlanEmitter 计划交付契约

状态：当前工作区已实现。代码位于 `agent/processing/plan_emitter.py`，由 Handling 为单次调用创建和关闭。

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ActionPlanDraft:
    source_stimulus_ids: tuple[str, ...]
    actions: tuple[Action, ...]

class PlanEmitter:
    async def emit(self, draft: ActionPlanDraft) -> PlanReceipt: ...
```

Handler 提交完整、不可变的行动草稿；角色、请求、交互、依据修订、plan_id 和 plan_ordinal 由 emitter 绑定。source_stimulus_ids 只能来自触发刺激及 pending。计划及嵌套值按领域约束和明确的类型集合校验，非法草稿在调用 sink 前拒绝。StartThinking 只能是序号零的独立计划。

计划序号在本次调用内从零开始；有效接收确认后才允许下一次交付。plan_id 根据角色、请求标识及序号计算，用于关联计划，不表示跨调用去重承诺。emit 不提供指定旧序号的重发参数。

同次并发 emit 通过锁串行执行。每次先检查取消，构造并校验完整计划，然后 await sink.emit。返回值必须是 PlanReceipt 且 plan_id 匹配。确认后记录标识，再检查取消；报告按交付顺序包含这些已确认标识。

普通交付异常会被保存为本次调用的失败状态并记录日志；即使 Handler 捕获异常，后续 emit 仍抛出原失败，不再调用 sink。最终报告保留合法消费事实和已接收标识，状态为 FAILED，retryable=False。任务取消也阻止本 emitter 再次发送；若 Handler 捕获取消并返回，报告为 CANCELLED。

未确认接收不能计入 emitted_plan_ids；不因结果未知而重发。计划正文和接收结果只在本次调用中使用，不写 outbox。close 释放请求和 sink 引用，之后 emit 抛 RuntimeError。

日志包含 character_id、request_id、interaction_id、plan_id、ordinal、错误码、异常类型和栈位置，不包含计划正文、异常原文、源码行、局部变量或异常链。

测试覆盖零个及多个计划、顺序、身份绑定、非法草稿、失败停止、取消、交付器关闭和日志内容隔离。
