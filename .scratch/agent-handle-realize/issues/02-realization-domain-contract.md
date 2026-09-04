# 02: 固定 realization 侧强类型领域契约

**What to build:** 在 01 的输入/结算类型之上增加 ActionPlan、ActionPlanSink/PlanReceipt、ExecutionContext、AgentOutput、output sink/receipt 和 ExecutionReport 强类型协议，使计划、输出与不可逆效果可以被排序、校验和幂等结算，同时不迁移现有执行链。

**Blocked by:** 01: 固定 handle 侧强类型领域契约。

**Status:** ready-for-agent

**GitHub Issue:** [#61](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/61)

## Decision rule

SPEC 第 5.3、5.4、6.10、7、8.1 节优先。SPEC 未说明的媒体格式、当前表情映射或唱歌失败细节才参考现有回复对象、realizer、capability 和测试；开发守则决定测试位置与 TDD 流程。发现需要新增 Action/Output kind 时停止并先改 SPEC。

## Scope

- 增加 ActionPlan、StateDependency、ActionPlanSink、PlanReceipt、ExecutionContext、AgentOutputSink、OutputReceipt、ExecutionReport、ActionResult 和稳定错误/状态枚举。
- 增加 SPEC 列出的 Action 联合：Say、Sing、PerformMotion、TransitionActivity、WriteDiary、PublishDynamic、ReplyDynamic、CreateSchedule、CancelSchedule、RequestSongLearning。
- 增加 TEXT、AUDIO、EXPRESSION、MOTION、SONG_STATE 输出变体及 `OutputDelivery`。
- 保留旧 PlannedAction/ResponseEnvelope 供迁移期使用，但新协议不接受任意 payload。

## Acceptance criteria

- [ ] 每个 Action、输出和 report 字段的构造约束与 SPEC 表格一致，ActionPlan actions 非空、有序且不可变。
- [ ] `ChangeExpression` 只能嵌入 Say/Sing；没有独立表达 Action、HAPTIC/PerformHaptic、NO_REPLY 或 CALL_CAPABILITY。
- [ ] Say 的 TTS 文本与预制音频互斥；空显示文本只有在存在预制音频时合法；delivery 能区分对话持久输出和瞬时反应。
- [ ] StateDependency 只能引用明确的 world/activity/schedule 聚合及 revision，ExecutionContext 不携带连接、数据库会话或 revision 字典。
- [ ] execution/action/output identity、sequence 和重投一致性可以从公开类型验证。
- [ ] 旧生产执行链保持可用，本工单不删除旧 Action 类型。

## Verification

- 先写公开领域协议失败测试；覆盖所有 Action/Output 变体、Say 互斥约束、非法独立 expression/haptic、revision 依赖和报告部分失败表示。
- 运行领域模块 focused tests、静态检查并记录结果；不要在测试中复写实现算法。

## Explicit exclusions

- 不实现 capability、Execution Ledger、realizer 或 stage output sink。
- 不新增通话输出、供应商 session 或客户端协议字段。

## Handoff

只提交 realization 协议扩展、测试和进度更新；29 号工单最终删除旧 PlannedAction/ResponseEnvelope。
