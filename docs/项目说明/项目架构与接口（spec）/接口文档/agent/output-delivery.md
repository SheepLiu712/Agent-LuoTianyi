# Agent 输出交付契约

状态：当前工作区已实现。`processing/execution.py` 管理单次执行，`processing/output_emitter.py` 负责单个行动的交付；草稿定义于 `processing/output_drafts.py`。

## 草稿与身份

OutputDraft 为 TextFinalDraft、AudioChunkDraft、MessageEndDraft、ExpressionDraft 的联合类型。草稿提供文字、音频、终止状态或表情以及 delivery；完整类型字段以领域 [realization SPEC](../domain/realization.md) 为准。

```python
class OutputEmitter:
    async def emit(self, draft: OutputDraft) -> OutputReceipt: ...
```

Agent 从本次 ExecutionContext 和当前 Action 绑定 interaction_id、execution_id、action_id，按发送顺序分配 sequence_no。序号从零开始，跨行动连续递增。Handler 不能直接提交完整 AgentOutput 或指定身份。领域构造器校验内容，不保存完整输出到数据库。

## 顺序与失败

同一行动的并发 emit 通过锁串行处理。有效接收确认前不会开始下一次交付。确认必须是 OutputReceipt，execution_id 和 sequence_no 与输出一致；确认后才增加序号，并将本次 output_started 设为 True。

第一次普通失败会记录错误类型、调用身份、行动标识、输出序号和稳定错误码，阻止后续 emit。即使 Handler 捕获异常并返回成功，Execution 仍把本项报告为失败，保留 Handler 已确认的效果，后续行动为 NOT_STARTED。背压拒绝、超时及错误确认均不触发自动重发，报告 retryable=False。

投递任务取消会阻止后续发送；若 Handler 捕获取消并返回，Execution 报告 CANCELLED。协作取消在交付前和有效确认后检查，已确认输出不会被抹掉。Handler 已返回的完成或失败结果按门面规则保留。

每项行动结束时关闭 emitter，之后继续使用它会抛 RuntimeError。本次内存状态不用于其他调用，不恢复进程终止前的输出。

## 输出语义

四类输出保留完整内容，包括原音频字节、framing、delivery、表情和终止状态。MessageEndOutput 的位置与正常发送顺序决定客户端后续处理；接收确认不表示播放完成。output_started=False 仅表示没有取得有效确认，不证明外部没有接收到数据。

已有 ALREADY_ACCEPTED 枚举仍可表示接收器明确识别的接收结果；Agent 不因此提供历史记录查询或重投协议。

## 验证

公开 realize 测试覆盖完整字段、跨行动连续序号、并发发送顺序、非法完整输出拒绝、交付失败停止、取消、部分效果和日志。已移除数据库故障、原内容恢复、重启恢复和历史去重测试。
