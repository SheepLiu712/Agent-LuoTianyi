# 25: 迁移每日日记筛选、生成与私密发布

**What to build:** 保持 `diary:{character_id}` 每日筛选、阈值、上限、去重和 private Agent dynamic 结果，同时让 world 只产生 DiaryPlanningDue，日记内容由 Agent handle 决定，WriteDiary 经 realize 幂等发布。

**Blocked by:** 05: 实现 handle 请求幂等、PlanEmitter 与交互上下文核心；06: 实现 realization、Execution Ledger 与 Say 输出核心；19: 建立长期 WorldStage 与 world 事实投递。

**Status:** ready-for-agent

**GitHub Issue:** [#84](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/84)

## Decision rule

SPEC 第 5.2/5.3、6.3—6.5、8.6 的 diary 行优先。Conversation 查询、source identity、解析格式和现有日记去重未说明时参考当前 diary task/capability/tests；不得让 world 直接取得 diary LLM/capability 生成角色内容。

## Architecture constraints

- 用户筛选/阈值/每日去重归 world；DiaryPlanningDue 的角色生成归 `agent/handlers/stimulus/proactive.py` 与 cognitive Skill。
- WriteDiary 归 `agent/handlers/action/publishing.py` 与 typed execution Skill；world 不取得 diary capability，stimulus Handler 不直接写 dynamic。
- Conversation 证据以强类型受控引用进入 snapshot/scoped context；数据库 session、完整查询器和长期对话真相源不进入 Agent context。

## Scope

- 每角色每日 00:00 筛选当日 Conversation 至少 50 条且当天无已发布 diary 的用户；超过 20 人随机取 20。
- 对每个入选用户构造 DiaryPlanningDue，经 WorldStage/Agent 使用 persona/style、对话证据和事实生成 WriteDiary。
- 实现 WriteDiary Action Handler，以日期/source/dedup key 发布 private Agent dynamic；不新增独立 diary 表。
- 逐用户报告 created/failed；LLM/capability 不可用时保持 skipped/失败边界。

## Acceptance criteria

- [ ] 统计按 character、user、date 隔离；低于 50、已有 source diary 的用户不入选。
- [ ] 超过 20 人才随机抽样，未超过时全部处理；随机源可控测试。
- [ ] 角色内容只在 Agent 内生成，world 只提供候选和受控证据引用。
- [ ] 每用户/日期最多发布一次 private Agent dynamic；重投不重新生成或重复发布。
- [ ] 不创建独立 diary 表，source identity/visibility 与当前数据兼容。
- [ ] capability/LLM 不可用时不会把用户标成已创建，created/failed/skipped 统计真实。
- [ ] world→WorldStage→façade 与 Agent 内 proactive Handler→cognitive Skill/publishing Action Handler→execution Skill 的依赖方向可静态证明。

## Verification

- 从 diary clock task 到 WorldStage/Agent 和最终 dynamic store 写失败集成测试，使用隔离数据库、固定随机和 Fake LLM/publisher。
- 覆盖阈值、上限、已有日记、角色隔离、重复 execution、生成失败、发布失败和全任务 skipped。
- 运行 diary、dynamics、world runtime、Agent integration 回归；真实 LLM 另列人工验证。

## Explicit exclusions

- 不改变日记 prompt、解析格式或可见性产品规则。
- 不新增 diary 表或客户端页面。

## Handoff

一个日记纵向 PR；PR 明确生成成功与发布成功的结算边界。
