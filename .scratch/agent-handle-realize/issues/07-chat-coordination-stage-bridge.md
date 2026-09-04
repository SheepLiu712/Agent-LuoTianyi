# 07: 让 ChatStage 通过新 façade 处理输入协调信号

**What to build:** 在不迁移正文回复的前提下建立 ChatStage 到两个 Agent interface 的生产桥接，并把用户打字、打开图片选择和关闭图片选择三类协调信号迁到强类型 request/HandlingReport 结算。

**Blocked by:** 05: 实现 handle 请求幂等、PlanEmitter 与交互上下文核心；06: 实现 realization、Execution Ledger 与 Say 输出核心。

**Status:** ready-for-agent

**GitHub Issue:** [#66](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/66)

## Decision rule

SPEC 第 4.2、5.2、5.4、8.3 节优先。等待秒数、WebSocket 别名和无 pending 行为不清时参考当前 Chat pipeline、listen timer、入口校验和测试；Adapter 只负责协议校验，Agent 不得读取 WebSocket 对象。

## Scope

- ChatStage 管理 immutable snapshot、pending ID、interaction revision、handle cancellation、stage-bound plan sink、execution worker 和 output sink。
- 将 `USER_TYPING`、`USER_IMAGE_SELECTING`、`USER_IMAGE_SELECTING_CANCEL` 转成强类型协调 Stimulus；不把它们持久化或加入内容 pending。
- stage 按 HandlingReport 的 ID 和 basis revision 结算，绝不通过 consume-all 清空当前队列。
- 暂未迁移的文字/图片内容仍走旧链，必须有明确的按输入种类分流，不能双处理。

## Acceptance criteria

- [ ] typing > 0 仅在有 pending 或 handle 运行时把期限延到 10 秒；无 pending/handle 时不回复。
- [ ] typing == 0 移除扩展等待并唤醒基于全部 pending 的正式重评；入口拒绝缺失、布尔或负数长度。
- [ ] image selecting open 把期限延到 60 秒并使旧未提交判断失效。
- [ ] image selecting close 在有 pending/handle 时恢复普通期限，无二者时清除期限；信号本身不伪造图片也不强制立即回复。
- [ ] 三类信号的 HandlingReport 可以 COMPLETED + consumed empty + retained all；stage 只在 revision 仍匹配时应用。
- [ ] stage-bound sink 只可靠入队，不同步重入 realization；关闭和容量满返回稳定失败。
- [ ] 同一外部信号不会同时进入新旧两条处理链。

## Verification

- 先从 WebSocket/ChatStage 可观察 seam 写失败测试；复用现有 waiting-signal 行为作为兼容基线，不测试私有 Handler。
- 覆盖有/无 pending、正在 handle、close 后图片另行到达、旧 revision report 和有界队列。
- 运行 stage、Adapter、Agent focused tests，记录 Red/Green。

## Explicit exclusions

- 不迁移文字、图片、语音回复，不移动 Reflection。
- 不删除 TopicPlanner/TopicReplier 或 AgentRuntime 旧代理。

## Handoff

一个协调信号纵向 PR；进度中明确当前仍是新旧按输入种类分流的中间状态。
