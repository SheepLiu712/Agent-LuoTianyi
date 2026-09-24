# 05: 实现 handle 请求幂等、PlanEmitter 与交互上下文核心

**What to build:** 通过公开 `handle_stimulus` 实现一次认知请求的统一内核：Request Ledger 校验合法重投，InteractionContextStore 隔离临时认知，PlanEmitter 可靠发射零到多个完整计划，并由 façade 生成逐 ID HandlingReport。

**Blocked by:** 04: 扩展两接口 Agent façade 与内部路由。

**Status:** ready-for-agent

**GitHub Issue:** [#64](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/64)

## Decision rule

SPEC 第 5.2、5.4、6.2、6.6、7、8.7 节优先。持久化或事务细节未规定时，使用项目现有数据库和生命周期模式实现 Agent 内部 repository，不暴露新业务 interface；当前聊天对象只能作为兼容输入参考，不能进入新公开协议。

## Architecture constraints

- 本票首次承载并建立 `agent/context/`、`agent/planning/` 和 `agent/ledgers/` 的 handle 侧实现；文件按 SPEC 6.1 的所有权放置，不建立 `common.py` 或全局 store locator。
- Handler 只取得 `(character_id, interaction_id)` scoped context accessor 和 PlanEmitter，不取得全局 context store、外部 sink 或 ledger repository。
- context 只保存临时认知工作集以及带来源、版本、TTL 的检索证据引用/受控快照；stage pending/deadline/连接、长期记忆/画像和权威 world 状态不得写入。
- Request/Execution Ledger 可共享一个持久 Adapter，但逻辑模型和职责必须分开；ledger 不依赖 Handler，也不判断 Reflection 条件。

## Scope

- Request Ledger 保存 request fingerprint、终态、plan acceptance、内部 mutation receipt 和 reflection scheduling state，并支持进程恢复所需的可靠记录。
- PlanEmitter 生成稳定 plan ID/ordinal/fingerprint，在外部 sink 接收前后记录状态，正确处理相同重投、内容冲突、背压、sink 关闭和 cancellation。
- InteractionContextStore 按 `(character_id, interaction_id)` 隔离，提供 context revision 的 compare-and-set、TTL 和结束清理；不保存 stage pending 或长期画像。
- façade 把 HandlerDecision 转成满足集合不变量的 HandlingReport，并只对成功接受的计划列出 emitted plan IDs。

## Acceptance criteria

- [ ] 相同 request ID + 相同 fingerprint 重投返回相同计划身份、ordinal、mutation receipt 和最终报告，不重复调用不可逆内部 mutation。
- [ ] 相同 request ID 配不同 interaction revision、anchor 或 pending fingerprint 明确契约失败。
- [ ] sink 已接受但返回链路中断后，重投不会生成内容不同的计划；不同 draft 复用 ordinal 被拒绝。
- [ ] emit 前 cancellation 阻止新计划；sink 拒绝旧 revision/关闭/超时时，Agent 不绕过 sink 输出。
- [ ] 两个用户或 interaction 共享角色 Agent 时临时上下文不串用；context revision 与 interaction revision 不混用。
- [ ] 外部模块不能导入或查询 `agent.context/planning/ledgers`；Handler 不直接依赖数据库、CapabilityManager 或 SystemRuntime。
- [ ] 零计划、单计划、多计划、retained、部分 consumed、失败/取消报告都满足 SPEC 不变量。

## Verification

- 所有证明从 Agent 的公开 `handle_stimulus` seam 观察，Fake Handler/Skill/sink 只模拟外部依赖，不断言私有调用次数。
- 先建立失败测试，至少覆盖重投、冲突、取消、背压、多 plan ordinal、CAS 冲突、TTL/结束清理和跨 interaction 隔离。
- 运行 Agent、domain 和数据库相关 focused tests，记录 Red 原因与 Green 结果。

## Explicit exclusions

- 不实现具体业务 Handler、Action realization 或 Reflection worker。
- 不让 stage 读取 ledger/context，也不增加 ledger 对外查询业务方法。

## Handoff

提交一个 Agent 内核 PR；若实现规模超过一个上下文，必须先回到本工单拆分存储 schema 与行为切片，不能无记录扩大。
