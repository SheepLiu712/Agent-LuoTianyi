# 21: 迁移 citywalk 报告、旅行事件与动态发布链

**What to build:** 保持 `try_citywalk:{character_id}` 当前概率、环境推进、报告、travel event 和动态结果，同时把角色路线/表达/发布决策收进 WorldStage/Agent，通过 PublishDynamic 或其它已定义 Action realize，不再由 world task 取得 CharacterRuntime。

**Blocked by:** 19: 建立长期 WorldStage 与 world 事实投递。

**Status:** ready-for-agent

**GitHub Issue:** [#80](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/80)

## Decision rule

SPEC 第 6.7、8.2、8.6 的 citywalk 行优先。概率、报告结构、EventStore 字段和动态发布失败语义未说明时参考当前 citywalk task/service 和测试；不得把地图/环境机械过程搬进 Agent，也不得把动态失败回滚为 citywalk 未完成。

## Scope

- WorldClock 仍按每角色每日 04:00 唤醒，按配置 `daily_run_probability` 抽样。
- 地图、环境推进和报告生成留在 world；形成稳定报告/观察后投递 WorldObservation 给 WorldStage。
- Agent 决定需要的角色表达和 PublishDynamic；实现通用 Publishing Action seam，确保幂等。
- 保持成功时 travel event、动态正文/ID 回写报告；发布失败与 citywalk 完成分别结算。

## Acceptance criteria

- [ ] 概率 miss、service 不可用、运行错误或无报告时按当前语义 skipped/failed，不产生角色输出或重复 event。
- [ ] 成功环境流程只写一次该角色 travel event，并把稳定事实交 WorldStage。
- [ ] 动态发布只由 Agent plan + realize 发生，同 execution/action 重投不重复发布。
- [ ] 动态失败不删除 travel event、不抹掉完成报告，结果能区分两种效果。
- [ ] world task 不再访问 CharacterRuntime、Agent 记忆/提示词或 dynamic capability 来生成角色内容。
- [ ] 调度时间、角色展开和 0.1 当前配置不因迁移改变。

## Verification

- 先从 WorldClock task + WorldStage + Agent façade 写失败集成测试，固定概率和 Fake 地图/发布供应商。
- 覆盖所有 skip/failure、成功无动态、成功有动态、发布重投、角色隔离和报告回写。
- 运行 citywalk、dynamics、world runtime 和 Agent integration 回归；真实地图/LLM 另列人工验证。

## Explicit exclusions

- 不修改 citywalk 地图算法、概率或报告产品内容。
- 不把纯环境数据变成 Agent 内部状态。

## Handoff

一个 citywalk 纵向 PR；进度记录机械流程与角色流程的新边界。
