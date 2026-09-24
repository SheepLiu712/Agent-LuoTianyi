# 10: 实现聊天旧判断失效、重新思考与部分结算

**What to build:** 当判断期间到达新内容或延长等待的协调信号时，让 ChatStage 先更新事实并取消旧 handle，拒绝迟到计划/report，再基于新 snapshot 重新思考；同时支持一次只消费部分 pending。

**Blocked by:** 07: 让 ChatStage 通过新 façade 处理输入协调信号；08: 迁移文字聊天、聚合超时与普通回复；09: 迁移图片与非 Realtime 语音输入。

**Status:** ready-for-agent

**GitHub Issue:** [#69](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/69)

## Decision rule

SPEC 第 5.2 HandlingReport、5.4、7、8.3 节优先。竞态顺序不清时参考当前 TopicPlanner snapshot/commit 和 waiting-signal 测试；不能用“尽量取消”替代 sink/report 的 revision 权威校验。

## Architecture constraints

- revision、pending、deadline、取消决定继续归 ChatStage；Agent façade/PlanEmitter 只消费 cancellation 与 basis revision，不能导入 stage 或回读其状态。
- Handler 局部工作集只放在 `agent/context` 的 scoped accessor 或当前 coroutine；不得把跨请求可变状态挂在 Agent/Handler 单例，也不得把 pending 复制到 context。
- 部分消费是公开 report 与 stage settlement 的协作，不为其新建可由 stage 调用的 Agent 内部接口。

## Scope

- 新内容、typing、图片选择和 interaction 终态变化先递增 stage revision，再触发旧 handle cancellation。
- stage-bound plan sink 在 emit 时按当前 revision 拒绝旧 plan；stage 对迟到 report 也按 basis revision 拒绝结算。
- 被取消判断使用的原 pending 仍保留，新 snapshot 包含仍有效旧内容和新内容；不重复持久化。
- 支持 Handler 只 consumed 部分 considered，剩余 retained 并恢复普通期限或等待新刺激。

## Acceptance criteria

- [ ] 新消息在抽取/模型运行期间到达时，旧结果不会发送或清空队列，新判断看到完整的新 pending 集合。
- [ ] typing 或 image-selection 延长等待同样使尚未提交结果失效。
- [ ] 旧 plan 在 cancellation 信号竞态下仍由 sink revision 拒绝；Agent 不能回读 stage 或绕过 sink。
- [ ] 旧 report 不应用到新 revision；stage 永远按 ID 结算，不使用 consume_all。
- [ ] M1 consumed、M2 retained 后只移除 M1，M2 重新设置普通期限并可与 M3 合并。
- [ ] 已经被 sink 接受的计划按真实状态结算；取消不回滚已提交输出/效果。
- [ ] import/对象图证明 stage 不持有 Handler/PlanEmitter/context/ledger，Agent 内部也不持有 ChatStage/队列/定时器。

## Verification

- 先建立可控 barrier 的跨模块失败测试，覆盖消息、typing、图片选择与 close 的关键竞态，不依赖真实模型时间。
- 覆盖旧 plan、旧 report、部分 settlement、持久化去重和 cancellation 发生在 emit 前/后。
- 运行 waiting signals、backpressure、chat integration 和 Agent 契约回归。

## Explicit exclusions

- 不实现慢 Recall 的临时/正式多计划；由 11 号工单负责。
- 不移动 Reflection，也不撤回已经发送的回复。

## Handoff

一个并发语义 PR；必须在 PR 中写出事件顺序和每个 revision 的期望，不能只报告测试通过。
