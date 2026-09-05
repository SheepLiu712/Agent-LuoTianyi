# 17: 迁移当天登录提醒与周期主动提醒

**What to build:** 让当天首次登录和 `proactive_topic_check` 对 due event 的筛选、claim、合并/随机选择、入队、失败释放和 Agent 表达保持当前行为，同时移除 ProactiveTopicMaker/TopicReplier 作为角色决策旁路。

**Blocked by:** 03: 冻结 WorldClock 调度与九类注册基线；08: 迁移文字聊天、聚合超时与普通回复；16: 迁移首次登录主动欢迎。

**Status:** ready-for-agent

**GitHub Issue:** [#76](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/76)

## Decision rule

SPEC 第 5.2、8.5、8.6 中 `proactive_topic_check` 行优先。event 筛选字段、trigger key 和 claim 事务不清时参考当前 ProactiveTopicMaker、EventStore 和既有提醒测试；不得增加新事件类型或恢复久别问候。

## Architecture constraints

- EventStore 查询/候选过滤/claim 属于 world/ChatStage；稳定 `ProactivePromptDue` 之后的角色判断归 `agent/handlers/stimulus/proactive.py` 和 cognitive Skill。
- proactive Handler 不导入 EventStore、WorldClock、ChatStage 或 TopicReplier；它只读取强类型事实/证据并形成计划。
- Say/Sing 输出继续通过 communication Action Handler + execution Skill，不能让 world task 或 stage 直接调用角色 capability。

## Scope

- 非首次且当天第一次登录时查询角色 due events，过滤其它角色、其它用户 personal、已通知和不支持类型。
- 仅 holiday、travel、new_song、birthday、anniversary 进入登录提醒；原子 claim 后合并本次内容，构造一个 ProactivePromptDue。
- 周期任务每 300 秒遍历活跃流，只处理 idle 至少 30 秒者，每个流从候选随机选一项并 claim。
- ChatStage 入队失败/取消释放 claim；成功后同 `(event,user,character,trigger)` 不重复，登录与周期共享 inflight claim。

## Acceptance criteria

- [ ] 当天首次登录按规则合并所有成功 claim 的受支持事件并产生一次正式 Agent 回复；同日再次登录不派发。
- [ ] 不支持事件在登录路径不被提前标记，仍可供其它合法路径处理。
- [ ] 周期扫描仅处理 idle 流且每流最多随机一项；忙碌流不被 claim。
- [ ] 角色/用户过滤发生在 claim 前，personal event 不跨用户。
- [ ] build/enqueue/cancel 失败释放 claim；登录和周期并发只允许一方取得同一 claim。
- [ ] 角色化内容、Recall 和 Say/Sing 都经 Agent 两接口；world task 不调用 TopicReplier。
- [ ] 依赖扫描证明 EventStore/claim 不进入 Agent context，proactive Handler/Skill 不被 stage/world 外部导入。

## Verification

- 先从登录和周期任务公开入口写失败集成测试，固定随机源和时钟，使用隔离 EventStore。
- 覆盖支持/不支持类型、同日登录、idle 边界、并发 claim、构建失败、入队失败、取消和成功去重。
- 运行 proactive、birthday/reminder、world task 和 chat integration 回归。

## Explicit exclusions

- 不改变 event 生成来源或 WorldClock 300 秒配置。
- 不实现 citywalk/B 站/学歌如何创建 event。

## Handoff

一个主动提醒纵向 PR；进度记录 ProactiveTopicMaker 剩余非角色职责或是否已无生产调用。
