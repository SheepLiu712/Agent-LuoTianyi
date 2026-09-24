# 28: 保持过期事件清理为纯 EventStore 维护

**What to build:** 在重构期间保持 `purge_expired_events` 每日清理规则、缓存失效和统计，并证明它不产生 Stimulus、不调用 Agent 或 WorldStage。

**Blocked by:** 03: 冻结 WorldClock 调度与九类注册基线。

**Status:** ready-for-agent

**GitHub Issue:** [#87](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/87)

## Decision rule

SPEC 第 8.6 的过期事件行优先。日期字段和缓存行为不清时参考当前 cleanup task、EventStore 和测试；不得扩大删除/失活范围，特别是 recurring、source=user 和仅 date_mmdd 事件。

## Scope

- 保持全局每日 00:00 注册和 WorldTaskResult 统计。
- 仅把 active、非 recurring、非 source=user 的已过期事件标 inactive。
- 有 end_date 时以 `end_date < today`；只有 start_date 时保留一天缓冲；只有 date_mmdd 时不清理。
- 提交成功后失效 due-event cache；任务保持纯数据库维护。

## Acceptance criteria

- [ ] end_date 昨日/今日边界、start_date 一天缓冲和 date_mmdd-only 分支逐项正确。
- [ ] recurring 和 source=user 事件始终保留，不因年份/角色缺省被误清理。
- [ ] 重复运行幂等，purged 数只计算本轮实际失活记录。
- [ ] 数据库失败时不报告成功 purge，cache 不处于与事务不一致状态。
- [ ] 任务不产生 Stimulus/Action，不调用 AgentRuntime、CharacterRuntime 或 WorldStage。
- [ ] 单次失败不停止下一日或其它 clock action。

## Verification

- 从 WorldTask/EventStore 公共 seam 写日期边界回归测试，使用固定本地日期和隔离数据库。
- 覆盖所有保留/清理组合、重复、事务失败、cache invalidation 和统计。
- 运行 event cleanup、EventStore、WorldClock/WorldRuntime 和提醒查询回归。

## Explicit exclusions

- 不硬删除事件、不改变用户事件保留政策、不新增归档功能。
- 不把清理结果变成角色可感知事件。

## Handoff

一个纯维护任务保护 PR；现有行为已满足时记录回归 Green 而不制造实现改动。
