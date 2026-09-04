# 11: 实现慢 Recall、多个完整计划与请求恢复

**What to build:** 允许一次 `handle_stimulus` 在等待内部慢 Recall 时先发一个完整临时计划，Recall 完成后再发一个完整正式计划，并在取消、过期 revision、背压和请求重投下保持稳定 ordinal 与不重复执行。

**Blocked by:** 05: 实现 handle 请求幂等、PlanEmitter 与交互上下文核心；06: 实现 realization、Execution Ledger 与 Say 输出核心；08: 迁移文字聊天、聚合超时与普通回复；10: 实现聊天旧判断失效、重新思考与部分结算。

**Status:** ready-for-agent

**GitHub Issue:** [#70](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/70)

## Decision rule

SPEC 第 5.2、5.4、6.2、6.8、8.7 节优先。临时回应文案、是否需要深 Recall 和当前记忆搜索细节只在 SPEC 留白时参考现有 Agent/潜意识；不得引入 `RecallCompleted` Stimulus、可变半计划或递归 handle。

## Scope

- Conversation Handler 可启动内部 Recall future，并根据策略通过 PlanEmitter 发射完整临时计划。
- handle coroutine 保持存活；Recall 返回后检查 cancellation，再形成新的完整正式计划。
- stage 可在 handle 尚未完成时执行已接受计划；同 request 严格按 ordinal，实现与 handle 生命周期独立取消。
- Request Ledger/PlanEmitter 支持响应丢失后的相同 request 重投，复用已接受计划和最终报告。

## Acceptance criteria

- [ ] 临时计划和正式计划各自 actions 非空、不可变、可独立 realize，ordinal 连续且 plan ID 重投稳定。
- [ ] Recall result/future 不出 Agent，不形成新 Stimulus，也不存入 stage。
- [ ] Recall 完成前取消时不再 emit 正式计划；已接受临时计划按真实 execution 结算。
- [ ] Recall 完成后若 interaction revision 已变化，stage sink 拒绝迟到正式计划。
- [ ] plan sink 背压/关闭产生稳定失败；同 request 重投不重复临时回复或生成不同正式内容。
- [ ] 多计划执行顺序可从 output 和 ExecutionReport 观察，不能依赖 Agent 实例上的调用局部可变字段。

## Verification

- 使用可控 Recall Fake 和 sink barrier 从公开 handle/realize seam 先写失败测试。
- 覆盖正常双计划、无需临时计划、Recall 取消、旧 revision、sink 拒绝、handle 返回丢失后重投和并发 interaction。
- 运行 Agent、chat integration、backpressure 与 ledger 回归。

## Explicit exclusions

- 不把所有聊天强制改成双计划；是否临时回应仍由 Handler 策略决定。
- 不实现 Reflection 或跨进程长任务。

## Handoff

一个渐进回复纵向 PR；PR 记录完整时间线、plan identities 和实际 Red/Green 证据。
