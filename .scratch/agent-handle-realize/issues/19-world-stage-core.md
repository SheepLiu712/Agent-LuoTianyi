# 19: 建立长期 WorldStage 与 world 事实投递

**What to build:** 建立按 `(character_id, world_id)` 隔离的长期 WorldStage，使 world 只能提交稳定、强类型事实，由 stage 管 pending/revision/cancellation、调用 Agent 两接口并路由 world 行动；WorldClock 仍只负责唤醒任务。

**Blocked by:** 03: 冻结 WorldClock 调度与九类注册基线；05: 实现 handle 请求幂等、PlanEmitter 与交互上下文核心；06: 实现 realization、Execution Ledger 与 Say 输出核心。

**Status:** ready-for-agent

**GitHub Issue:** [#78](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/78)

## Decision rule

SPEC 第 4.1—4.4、5.、7、8.1—8.2 节优先。实例生命周期和 world revision 来源不清时参考当前 WorldRuntime/SystemRuntime 组装及 EventStore；不得让 world 直接调用 Agent，也不得把权威 world 状态复制进 Agent context。

## Scope

- SystemRuntime 显式装配 WorldStage registry、AgentRuntime 和受限 world/output Adapter，不新增全局查找。
- WorldStage 维护长期 interaction、pending、interaction revision、WorldInteractionSnapshot、handle cancellation、plan sink 和 execution worker。
- world task 通过窄投递 seam 提交 WorldObservation 等领域事实；stage 不解释抓取/供应商原始数据。
- world output sink 对无即时通道输出明确支持/拒绝；持久效果由对应 Action Handler/Adapter 实现。

## Acceptance criteria

- [ ] 同一 character/world 复用一个长期 stage，不为每个事件创建 one-shot runner；不同 scope 严格隔离。
- [ ] world 不能取得 Agent façade 并直接调用；只有 WorldStage 调用两个业务方法。
- [ ] 新事实递增 interaction revision、取消旧 handle并按 ID 结算，stage 定时不注册成 world 领域 clock action。
- [ ] WorldSnapshot 只含受控事实引用及 world/activity/schedule revision，不含数据库/任务/连接对象。
- [ ] world 仍拥有权威事实和 revision；Action 提交点由 owner Adapter 校验 StateDependency。
- [ ] stage/output sink 不生成角色表达，也不调用 subconscious/capability。

## Verification

- 先以 Fake world producer + 真实 WorldStage/Agent façade 写失败集成测试。
- 覆盖 scope 复用/隔离、事实顺序、旧 revision、无输出支持、关闭和 world owner revision 冲突。
- 运行 world/runtime/stage/Agent integration 与 shutdown 回归。

## Explicit exclusions

- 本票只建立通用投递与持续交互，不迁移具体九类任务或活动计划。
- 不把 WorldClock 移入 stage。

## Handoff

一个 WorldStage expand PR；进度明确哪些 world task 尚未接入。
