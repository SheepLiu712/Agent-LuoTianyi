# Agent 两接口门面契约

状态：当前工作区已实现单次处理流程。领域对象见 [handle 输入](../domain/handle-input.md)、[处理报告](../domain/handling-report.md) 和 [计划与执行](../domain/realization.md)。

## 实例与装配

`src.agent` 只导出 `Agent`，业务方法只有以下两个。AgentRuntime 在初始化时为每个启用角色直接装配角色身份及两个路由器，缓存独立 Agent；Agent 构造不接收数据库会话工厂。旧调用通过 `get_character_runtime(...).conscious` 取得兼容对象。

```python
async def handle_stimulus(self, request: HandleStimulusRequest,
                          plan_sink: ActionPlanSink) -> HandlingReport: ...

async def realize_action_plan(self, plan: ActionPlan, context: ExecutionContext,
                              output_sink: AgentOutputSink) -> ExecutionReport: ...
```

请求、上下文和 sink 属于本次调用，不保存在共享 Agent 的当前用户或当前交互字段中。每次调用独立处理，不查历史报告、不合并重复调用、不恢复旧计划或输出。相同标识再次调用也会独立处理，调用方不能据此假定不会重复产生效果。两类报告的 `retryable` 均为 False。

## handle 流程

1. 检查请求类型和 sink.emit；错误类型抛 TypeError。
2. 检查触发刺激和全部 pending 的目标角色包含绑定角色，否则返回 FAILED / CONTRACT_SNAPSHOT_MISMATCH。
3. 检查 Agent 是否接受工作；关闭期间返回 FAILED / DEPENDENCY_UNAVAILABLE。
4. 登记本次在途调用，执行 `await Handling(self, request, plan_sink).run()`。
5. Handling 先检查取消，再按触发刺激的 kind 查找一个处理器。已取消返回 CANCELLED / error_code=None；未注册返回 FAILED / UNSUPPORTED_STIMULUS。
6. 创建本次 PlanEmitter，调用处理器，校验并整理 HandlingReport，最后关闭 emitter。
7. 门面记录结果日志，并解除在途登记。

入口失败或处理器没有返回合法报告时，considered 和 retained 包含按快照顺序排列的全部 pending，consumed 为空。处理期间已经确认接收的计划标识仍保留。合法报告的消费事实保持不变；交付失败不能被处理器捕获异常后返回的成功报告掩盖。Agent 不直接修改 stage 的 pending。

## realize 流程

1. 检查计划、执行上下文及 sink.emit；错误类型抛 TypeError。
2. 检查角色和交互身份匹配，否则返回 FAILED / CONTRACT_MISMATCH；停止接受时返回 DEPENDENCY_UNAVAILABLE。
3. 登记本次在途调用，执行 `await Execution(self, plan, context, output_sink).run()`。
4. 检查计划依据修订与当前修订一致、令牌未取消，并预先解析全部行动的处理器。分别以 STALE_INTERACTION、CANCELLED、UNSUPPORTED_ACTION 拒绝；全部行动保持 NOT_STARTED。
5. 按计划顺序执行行动。每项使用独立 OutputEmitter，输出序号在本次执行内跨行动从零连续递增。
6. 校验 ActionResult 的类型、action_id 和状态。失败或取消停止后续行动，保留已返回的效果与已完成结果，剩余行动为 NOT_STARTED。
7. 关闭当前 emitter，返回 ExecutionReport；门面结束在途登记并记录结果。

StartThinking 由 stage 消费，不能注册为 Agent 行动处理器。`output_started` 只表示本次有输出得到有效接收确认；False 不证明外部一定没有接收。接收确认不表示客户端播放或展示完成。

## 错误与取消

- 投递失败后不重发，记录错误并终止本次后续交付；异常结束不回滚已发生的业务效果。
- TimeoutError 映射 PROVIDER_TIMEOUT。SinkRejectedError 的 STALE_INTERACTION、SINK_CLOSED、BACKPRESSURE_TIMEOUT 映射同名码；其他拒绝在 handle 中为 INTERNAL_ERROR，在 realize 中为 CONTRACT_MISMATCH，UNSUPPORTED_OUTPUT 在 realize 中保留同名码。其他普通异常为 INTERNAL_ERROR。
- 有效接收确认先记入本次内存状态，再检查协作取消。行动已返回的完成或失败结果不被晚到取消抹掉；未发生交付失败时，可信失败优先于晚到取消。
- `processing/invocation.py` 的 call_handler 由两条流程共用。处理器开始前再次检查令牌；调用任务取消时只向处理器转发一次取消，并等待清理结束。重复取消不提前释放依赖，清理后传播 CancelledError，不保证返回报告。
- 普通错误日志包含调用身份、稳定错误码、异常类型和栈位置，省略源码、局部变量及协作者异常原文。

## 生命周期与代码位置

`processing/` 包含 Handling、Execution、call_handler、两种 emitter、输出草稿和计划身份工具。路由仍在 `handlers/stimulus/router.py` 和 `handlers/action/router.py`，详见 [路由契约](handler-routing.md)。生产注册集合为空。

AgentRuntime.shutdown 停止新工作后，有界等待在途调用与清理退出，再释放资源。等待超时抛 RuntimeError 并保留依赖；后续 shutdown 可继续等待。进程终止后，不恢复未完成的门面调用。

## 验证

从两个公开入口和运行时生命周期验证准入、计划及输出顺序、部分结果、错误、取消和关闭。当前测试说明见 `server/tests/agent/README.md`；旧持久化、重复调用合并和重放测试已移除。
