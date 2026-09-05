# 14: 迁移上下文压缩、用户画像并退出 stage ReflectionWorker

**What to build:** 在 Agent 内部 Reflection 链补齐 ContextCompaction 和 UserProfileUpdate policy/handler，使上下文过长和画像更新只依赖 Agent 自有状态与固定 evidence；迁移完成后 ChatStage 不再持有 ReflectionWorker。

**Blocked by:** 13: 由 Agent settlement 调度事后记忆与日期反思。

**Status:** ready-for-agent

**GitHub Issue:** [#73](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/73)

## Decision rule

SPEC 第 6.9、7、8.1/8.3 节优先。阈值、上下文来源和画像格式未规定时参考当前 Conversation Context Store、配置和 ReflectionWorker；不得用 Request/Execution Ledger 状态本身代表“上下文过长”。若需要新的外部配置字段，先补 SPEC。

## Architecture constraints

- ContextCompaction/UserProfileUpdate 分别放入 `agent/handlers/reflection` 与 `agent/skills/reflection` 的既有边界；不要重新建立通用 ReflectionWorker 或 stage callback。
- conversation context 的长期内容与画像由其现有存储拥有；`agent/context` 只保留临时工作集，压缩时使用固定 evidence/context revision，不复制长期真相源。
- policy 选择步骤，Handler 编排步骤，Skill 隐藏持久/模型机制；三者不得合并成可由 stage 直接调用的 service。

## Scope

- ReflectionPolicy 在安全 settlement 时点读取固定 conversation context revision，并按消息/token 阈值选择 ContextCompaction。
- UserProfileUpdate 仅在 user/evidence 满足策略时运行，按 character/user 隔离并幂等写入。
- 已完成 step 重投跳过，失败 step 使用同一 job 安全重试；压缩 CAS 冲突不覆盖更新后的上下文。
- 删除 ChatStage 对 ReflectionWorker 及日期、记忆、画像、压缩业务代理的持有/调用；兼容类若无调用者留到 29 删除。

## Acceptance criteria

- [ ] 未超过阈值时 compaction SKIPPED，超过时只压缩指定 revision；并发新增消息不会被旧结果覆盖。
- [ ] Request/Execution Ledger 只提供结算事实和幂等凭证，不直接决定压缩或画像条件。
- [ ] user_id 为空的画像 step 明确跳过，不使用默认用户。
- [ ] Reflection 失败不阻塞或改写已完成回复；积压/失败/重试可观测。
- [ ] ChatStage 不再导入、创建或调用 ReflectionWorker/具体反思步骤。
- [ ] Agent 对外仍只有两个业务方法，没有“run_reflection”入口。
- [ ] stage 与公开 Agent 包均不导出 ReflectionCoordinator/Handler/Skill/job；旧 ReflectionWorker 无生产调用。

## Verification

- 从正常聊天输出完成后的最终上下文/画像和观测事件写失败集成测试，不直接调用 ReflectionHandler。
- 覆盖阈值上下、CAS 冲突、重复 settlement、空用户、队列满、shutdown 保留和后台失败。
- 运行 chat integration、Agent、subconscious、shutdown 回归。

## Explicit exclusions

- 不改变压缩摘要或画像产品策略，除非 SPEC 先更新。
- 不删除其它尚有生产调用者的 AgentRuntime 代理。

## Handoff

一个 Reflection 收束 PR；进度中说明 stage worker 已退出生产调用但最终死代码删除等待 29。
