# 13: 由 Agent settlement 调度事后记忆与日期反思

**What to build:** 把回复后的自动记忆整理和重要日期检查从 ChatStage/ReflectionWorker 收进 Agent，由 façade 的 settlement notice 唤醒 ReflectionCoordinator，查询 ledger 与 ReflectionPolicy 后可靠投递 ReflectionJob。

**Blocked by:** 05: 实现 handle 请求幂等、PlanEmitter 与交互上下文核心；06: 实现 realization、Execution Ledger 与 Say 输出核心；08: 迁移文字聊天、聚合超时与普通回复；12: 将用户明确记忆请求收进 Agent 内部状态变更。

**Status:** ready-for-agent

**GitHub Issue:** [#72](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/72)

## Decision rule

SPEC 第 6.6、6.9、7、8.1/8.3 节优先。当前 ReflectionWorker 的证据收集、日期模型和记忆写入只用于兼容细节；ledger 不得成为业务触发条件，Reflection 不能生成计划、输出、Stimulus 或递归 handle。

## Architecture constraints

- settlement/policy/job/scheduler 归 `agent/reflection`；具体自动记忆与日期步骤归 `agent/handlers/reflection`，底层能力归 `agent/skills/reflection`。
- 只有 ReflectionCoordinator 可以创建/投递 ReflectionJob；Reflection Handler 不依赖 stage、PlanEmitter、output sink 或公开 report，不递归调用 façade。
- ledger 由 coordinator 只读结算事实并记录 scheduling state，不能反向依赖 reflection policy；step 通过 typed Skill adapter 写长期存储。
- 包只在本票首次真实承载相应行为时建立，不保留 stage 侧第二套 worker 作为永久路径。

## Scope

- handle 完成或 execution 形成新可结算事实时发送内部 settlement notice。
- Coordinator 查询 Request/Execution Ledger，等待需要的最终 execution facts，再由 Policy 选择 TurnMemoryConsolidation/ImportantDateReview。
- ReflectionJob 使用最小证据引用、allowed kinds、稳定 idempotency key、至少一次投递和 step 级幂等。
- 关系 job 按 character/user 有序，无用户 job 按 character/interaction 有序；队列有界且 shutdown 可证明不丢。
- 自动记忆依据 evidence key 避免重复 IntentionalMemoryCommit。

## Acceptance criteria

- [ ] consumed 内容无计划、计划完成、取消/失败后已有真实效果三种 settlement 都按 SPEC 选择证据；全部 retained 不创建完成式反思。
- [ ] NOT_STARTED Action 和未被 consumed 刺激不能成为反思事实。
- [ ] 自动记忆与显式记忆不产生语义重复；相同 job/step 最多成功提交一次。
- [ ] 日期只对用户明确表达且字段充分的事实写 confirmed；歧义只形成隔离且有 TTL 的 PendingClarification。
- [ ] 用户可见输出不等待具体 Reflection；后台失败不撤销已发送回复，也不被静默丢弃。
- [ ] stage 不再调日期或自动记忆代理；ReflectionHandler 不产生追问输出。
- [ ] `agent.reflection -> handlers.reflection -> skills.reflection` 的依赖方向可由静态检查证明，外部无内部 job/handler 导入。

## Verification

- 从 Agent 两公开接口及最终 subconscious 状态观察，使用可控 settlement、Fake provider 和隔离存储先写失败测试。
- 覆盖无计划、有计划、部分执行、重复投递、容量满、shutdown、显式记忆去重、confirmed/ambiguous 日期。
- 运行 Agent、memory/date、chat integration、shutdown 回归。

## Explicit exclusions

- 本票不迁移上下文压缩和用户画像；由 14 号工单负责。
- 不删除整个旧 ReflectionWorker，直到其所有职责迁完。

## Handoff

一个内部异步纵向 PR；PR 必须记录可靠接受边界和仍由旧 worker 承担的职责。
