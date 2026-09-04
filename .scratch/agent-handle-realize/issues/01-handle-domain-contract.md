# 01: 固定 handle 侧强类型领域契约

**What to build:** 以向后兼容的扩展方式增加 `handle_stimulus` 的输入与结算领域对象，使后续调用方可以只用不可变、强类型的 Stimulus、InteractionSnapshot、request 和 HandlingReport 表达一次认知与逐 ID 结算；计划及 sink 协议由 02 号工单补齐，现有聊天链暂不迁移。

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

**GitHub Issue:** [#60](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/60)

## Decision rule

SPEC 第 5.2、5.4、7、8.1 节是规范来源。字段或失败语义不清时，依次查看当前分支的领域对象、聊天输入校验和相关测试，再遵守开发守则；当前实现只能补充 SPEC 未说明的兼容细节，不能恢复任意 `payload`、Call/Realtime 或默认角色回退。若二者冲突，先停止并修订 SPEC。

## Scope

- 增加 `HandleStimulusRequest`、`CancellationToken`、`HandlingReport` 及其稳定枚举和错误族。
- 增加 SPEC 列出的全部 Stimulus 变体及 Chat、Toy、World 三种 InteractionSnapshot；公共字段、专有字段、时区、引用和 revision 约束必须逐项一致。
- 在迁移期允许旧 `Stimulus` 并存，但新类型不得继承或包裹任意 Mapping 扩展口；新调用者只导入目标协议。
- 公开包只导出跨模块协议，不导出 Handler、Skill、ledger、Recall 或模型对象。

## Acceptance criteria

- [ ] 每个 Stimulus 变体都能通过公开构造入口创建，非法字段、未知 kind/schema、目标角色缺失和 snapshot kind 不匹配返回稳定契约错误。
- [ ] `UserTyping`、`ImageSelectionOpened/Closed` 可作为不进入 pending 的协调刺激；内容刺激在对应 snapshot pending 中只能出现一次。
- [ ] HandlingReport 强制满足 considered = consumed ∪ retained 且二者不重叠；`request_status` 与 pending 是否全部消费相互独立。
- [ ] `interaction_revision` 只表示 stage 交互修订；协议中不存在含义不明的全局 StateVersion。
- [ ] 当前版本没有 Call/Realtime、`UserJoinedActivity`、`ActivityInterrupted` 变体，也没有任意 payload 兜底。
- [ ] 旧生产链在本工单结束时仍可运行；本工单不删除旧领域对象或旧调用方。

## Verification

- 先从 `domain` 的公开导出写失败契约测试，再写最小实现；测试覆盖每类变体的一个合法样例和代表性的非法组合。
- 记录 focused tests、领域模块回归和类型/静态检查的实际命令与结果；不通过私有构造 helper 证明协议正确。

## Explicit exclusions

- 不实现 ActionPlan/plan sink、Agent façade、Handler 路由、PlanEmitter、stage 迁移或任何角色回复。
- 不改变 WebSocket/客户端协议，不删除旧 `Stimulus.payload` 使用者。

## Handoff

只提交本协议扩展、对应测试和开发进度更新。PR 必须写明这是 expand 阶段，后续删除旧协议由 29 号工单负责。
