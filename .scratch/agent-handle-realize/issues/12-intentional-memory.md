# 12: 将用户明确记忆请求收进 Agent 内部状态变更

**What to build:** 当用户明确要求角色记住一项事实时，由 Conversation Handler 在当前 handle 内通过 `IntentionalMemoryCommit` 幂等写入 Agent 自有记忆，只有写入成功或可靠接受后才允许发出“已记住”的回复计划。

**Blocked by:** 05: 实现 handle 请求幂等、PlanEmitter 与交互上下文核心；08: 迁移文字聊天、聚合超时与普通回复。

**Status:** ready-for-agent

**GitHub Issue:** [#71](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/71)

## Decision rule

SPEC 第 6.4、6.6—6.7、7、8.1 节优先。记忆记录结构、向量索引和当前显式记忆识别仅在 SPEC 留白时参考 subconscious 和记忆测试；不得创建 RecordIntentionalMemory Action 或让 stage 写数据库。

## Architecture constraints

- `IntentionalMemoryCommit` 归 `agent/skills/mutation`，通过私有 typed adapter 修改 subconscious/记忆存储；Conversation Handler 不直接导入数据库或 subconscious。
- mutation Skill 接收显式 character/user/evidence/idempotency 输入并返回 committed revision；不生成 ActionPlan、HandlingReport 或用户文案。
- 当前 interaction 的证据引用可进入 `agent/context`，已提交长期事实仍由长期存储拥有，不能复制成第二份 context 真相源。

## Scope

- Handler 识别明确记忆意图并生成最小证据；内部 mutation 使用 `request_id + mutation kind + evidence key` 稳定幂等键。
- IntentionalMemoryCommit 写 Agent 自有存储并返回 committed revision；Request Ledger 记录 receipt。
- 只有 mutation 成功/可靠接受后 PlanEmitter 才可发出承诺成功的 Say；失败时保留对应刺激并返回稳定可重试状态。
- 为后续自动记忆 Reflection 暴露内部 evidence 去重事实，但不新增外部接口。

## Acceptance criteria

- [ ] 显式“请记住”成功时先提交一次记忆，再产生成功承诺；输出先于提交即失败验收。
- [ ] 相同 request 重投或进程恢复不重复写相同事实，返回相同 committed revision/receipt。
- [ ] 写入失败时不说“已经记住”，相关 pending retained，retryable 与实际错误一致。
- [ ] 不同 character/user 的记忆隔离，空 user 的场景不伪造默认用户。
- [ ] stage、world 和 output sink 看不到记忆对象、向量结果、数据库 session 或 mutation command。
- [ ] Handler 只依赖 mutation Skill 契约；不存在 `execute(skill_name, payload)`、全局 registry 或 CapabilityManager 直连。
- [ ] 新 Action 联合中仍不存在 RecordIntentionalMemory。

## Verification

- 从公开 `handle_stimulus` 写失败测试，使用隔离记忆存储/Fake 外部模型；断言可观察 plan/report 和最终持久事实，不断言私有调用次数。
- 覆盖成功、重复、冲突、存储失败、取消和跨用户/角色隔离。
- 运行 Agent、subconscious memory、数据库和 chat integration 回归。

## Explicit exclusions

- 不实现自动对话记忆、画像、压缩或重要日期；由 13—14 号工单负责。
- 不把普通推测内容当成显式记忆承诺。

## Handoff

一个内部状态纵向 PR；进度明确记录持久化和重投证据。
