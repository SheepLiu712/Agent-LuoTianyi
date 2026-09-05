# 20: 实现每日规划、活动生命周期与持久日程 Action

**What to build:** 让 DailyPlanningDue、ActivityDue/Started/Observation/Ended 和 WorldObservation 经 WorldStage/ActivityHandler 形成 CreateSchedule、CancelSchedule、TransitionActivity、Say/Sing/PerformMotion 等计划，并由权威 owner 按 revision 幂等提交。

**Blocked by:** 18: 实现 ToyStage 设备事实、振动与动作输出；19: 建立长期 WorldStage 与 world 事实投递。

**Status:** ready-for-agent

**GitHub Issue:** [#79](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/79)

## Decision rule

SPEC 第 4.4、5.2/5.3、6.3—6.5、7 节优先。当前代码不存在的活动语义不得从旧 PRD 或猜测扩张；实现只覆盖 SPEC 已列变体和字段。若某个具体活动规则未被 SPEC 定义，先停在协议/通用状态机，不添加产品策略。

## Architecture constraints

- Activity Handler 归 `agent/handlers/stimulus/world_activity.py`，可复用 cognitive Skill，但不调用聊天 pipeline、world owner 或 scheduler。
- Create/CancelSchedule、TransitionActivity 分别归 `agent/handlers/action/scheduling.py`，PerformMotion 归 motion Action Handler；底层提交由 typed execution Skill/owner Adapter 完成。
- activity/schedule revision 在 domain StateDependency 中传入并由 owner 校验；不得复制进 Agent context 充当权威状态。

## Scope

- ActivityHandler 处理每日规划、活动到期、开始、观察和结束事实，复用 Recall/Attention 但不使用聊天 pipeline。
- 实现 CreateSchedule、CancelSchedule、TransitionActivity Action Handler，以及 world/scheduler Adapter 的 revision 校验和 effect receipt。
- 到期持久日程由 world/scheduler 转成强类型 Stimulus 再交 WorldStage；clock 不直接构造回复。
- PerformMotion 的实现复用 18 号设备/动作能力（如果当前部署无设备，world sink 明确拒绝而非伪成功）。

## Acceptance criteria

- [ ] 日程创建/取消和活动迁移按 dedup key + action ID 幂等，同 execution 重试不重复。
- [ ] activity/schedule revision 冲突分别返回 STALE_ACTIVITY/STALE_SCHEDULE，不用 interaction revision 覆盖。
- [ ] 到期后只产生一次匹配 schema 的 Stimulus；任务中间状态不伪装成活动完成。
- [ ] ActivityObservation 只携带规范化事实，供应商/环境原始对象留在 world。
- [ ] Agent 决定角色计划和表达，world owner 决定权威状态是否仍可提交。
- [ ] 未定义的 UserJoinedActivity/ActivityInterrupted 和 Call 仍不存在。
- [ ] stimulus Handler→cognitive Skill 与 action Handler→execution Skill 单向依赖成立，任何 Handler 都不直接导入 world/scheduler/设备 SDK。

## Verification

- 从 WorldStage + Fake scheduler/world owner 写失败测试，固定时钟并观察持久日程、Stimulus 和 ExecutionReport。
- 覆盖创建/取消重投、到期一次、三类 stale revision、取消竞态、活动完整生命周期和无动作通道。
- 运行 world/stage/Agent/scheduler integration 回归。

## Explicit exclusions

- 不设计具体游戏地图或每日计划内容策略。
- 不新增活动事件种类或通用 capability Action。

## Handoff

一个世界活动纵向 PR；PR 列明哪些行为是通用机制、哪些已有产品规则未在本票范围。
