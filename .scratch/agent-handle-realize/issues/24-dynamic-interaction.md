# 24: 迁移动态回复决策与动态记忆

**What to build:** 保持 `dynamic_interaction` 每轮候选上限、reply/ignore 状态和记忆状态，但让 world 只投递 DynamicObserved，Agent 决定是否回复/记忆，ReplyDynamic 经 realize 发布，Agent 自有记忆在内部幂等提交。

**Blocked by:** 05: 实现 handle 请求幂等、PlanEmitter 与交互上下文核心；06: 实现 realization、Execution Ledger 与 Say 输出核心；19: 建立长期 WorldStage 与 world 事实投递。

**Status:** ready-for-agent

**GitHub Issue:** [#83](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/83)

## Decision rule

SPEC 第 5.2/5.3、6.3—6.7、8.6 的 dynamic_interaction 行优先。候选查询、线程评论表示、reply/ignore 和状态字段未说明时参考当前 task/dynamics tests；不得让 world 调 AgentRuntime 记忆代理或 CharacterRuntime 生成内容。

## Architecture constraints

- 候选选择/原记录状态归 world；DynamicObserved 的角色处理归 `agent/handlers/stimulus/proactive.py`，图片/回复判断复用 cognitive Skill，记忆写入归 mutation Skill。
- ReplyDynamic 归 `agent/handlers/action/publishing.py` 与 typed execution Skill；stimulus Handler 不直接发布，world 不直接调用 publish capability。
- receipt 通过公开 settlement 回写 world 状态；Agent context 只留当前 interaction 受控证据，不持有 world pending 列表或长期记忆副本。

## Scope

- 每 600 秒的 world task 选择并规范化最多 10 条待回复正文、20 条待回复评论、10/20 条待记忆正文/评论。
- 每项形成 DynamicObserved 交 WorldStage；媒体可复用 ImageReading，回复/忽略和记忆由 Agent Handler/Skill 决定。
- 实现 ReplyDynamic Action Handler 和目标引用校验；Execution receipt 驱动 replied/ignored/failed。
- Agent 内部记忆 mutation receipt 驱动 memory 状态，并记录可关联观测事件。

## Acceptance criteria

- [ ] 回复 LLM 可用时，正文生成并发布评论；评论先明确 reply/ignore，再写准确状态。
- [ ] 回复 LLM 不可用时不伪造回复，但记忆批次仍按当前语义处理。
- [ ] 每轮四种上限、thread comment 目标和默认角色范围保持。
- [ ] ReplyDynamic 重投不重复评论；失败只把对应项标 failed，不污染其它项。
- [ ] 记忆写入/忽略幂等，状态与真实 receipt 一致；同一项不因任务重跑重复记忆。
- [ ] world 不读取 Agent memory，不生成角色回复，不直接调用 publish capability。
- [ ] dynamic world task、proactive Handler、mutation Skill、publishing Action Handler 的依赖方向符合 SPEC 6.1，无 CharacterRuntime/AgentRuntime 业务代理旁路。

## Verification

- 从 clock task + WorldStage + Agent + dynamics store 写失败集成测试，固定候选和 Fake LLM/publisher。
- 覆盖 post/comment reply、ignore、LLM 缺失、发布失败、memory 成功/忽略/失败、上限和重复任务。
- 运行 dynamics、world task、memory 和 Agent/world integration 回归；真实平台另列人工验证。

## Explicit exclusions

- 不改变动态 API、可见性或候选排序产品规则。
- 不把系统动态当成可回复/记忆内容。

## Handoff

一个动态互动纵向 PR；进度记录回复状态与记忆状态如何由不同 receipt 结算。
