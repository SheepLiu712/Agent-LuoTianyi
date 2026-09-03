# Agent `handle_stimulus / realize_action_plan` 深模块重构进度

> 最后更新：2026-09-03
>
> 当前阶段：需求与 interface 方向评审
>
> 总体状态：进行中

## 对应文档

- PRD：[`Agent-handle-realize-深模块重构.md`](../需求说明（PRD）/Agent-handle-realize-深模块重构.md)
- 当前 Agent interface：[`agent/README.md`](../../项目说明/项目架构与接口（spec）/接口文档/agent/README.md)
- 相关电话设计：[`v0.4.0-电话功能设计.md`](../需求说明（PRD）/v0.4.0-电话功能设计.md)

## 当前 PR 范围

- 按新讨论修订 Agent PRD；
- 将两个目标 interface 收敛为 `handle_stimulus` 和 `realize_action_plan`；
- 将 Recall 及其完成事件收回 Agent 内部；
- 将 `handle_stimulus` 改为通过 `ActionPlanSink` 输出零到多个完整计划，并在结束时返回 `HandlingReport`；
- 明确 Chat、Call、Toy、CharacterActivity 是不同 stage 实现，只共享 Agent 调用和结算约定；
- 拆分 Realtime 媒体上行与 Agent 语义回合两个窄端口；
- 补齐 VCPedia 新歌发现与学会歌曲的知识、记忆和日记链路；
- 明确 `AgentOutputSink` 如何把通道无关输出路由到聊天、电话和玩偶 Adapter；
- 明确小 PR 迁移的最终完成条件是不再保留绕过 Agent 的旧角色决策路径；
- 增加每日规划、活动中刺激、电话和玩偶场景；
- 同步领域术语；
- 不修改 interface spec、生产代码和测试。

## 已完成

- [x] 当前调用链静态盘点；
- [x] Agent、subconscious、capabilities、stage、Adapter、world 的职责划分；
- [x] `ActionPlanSink` 与最终 `HandlingReport` 的双通道结果设计；
- [x] stage 家族及共享协调约定，不建立统一 BaseStage；
- [x] InteractionSnapshot 的 Chat、Call、Toy、CharacterActivity 强类型变体；
- [x] Recall 和三类上下文的所有权设计；
- [x] 慢 Recall 在同一次 handle 内续程，不生成 `RecallCompleted` Stimulus；
- [x] 临时计划和正式计划作为两个完整 ActionPlan 的渐进回复设计；
- [x] handle/realize 分别取消、迟到 Recall 丢弃和多计划结算规则；
- [x] 交互等待与持久日程的区分；
- [x] 每日规划和活动中刺激场景；
- [x] 电话开始、语音、打断、语音结束和通话结束场景；
- [x] Realtime 原始媒体与语义回合的双端口设计；
- [x] 识别并记录现有 CallStream 处理供应商语义、绕过 Agent 的架构冲突；
- [x] 玩偶振动与语音场景；
- [x] stage-bound `AgentOutputSink` 与各通道 Adapter 的路由设计；
- [x] `SongKnowledgeDiscovered`、`SongLearned` 及角色歌曲记忆落库边界；
- [x] 渐进迁移不保留永久双路径的完成标准；
- [x] PRD 渐进计划修订版。

## 尚未开始

- [ ] PRD 评审和确认；
- [ ] Agent、stage、domain、AgentRuntime、Realtime 双端口和输出 sink 的详细 interface spec；
- [ ] 每种 Stimulus 和 Action 的强类型字段；
- [ ] interface 契约测试；
- [ ] 产品实现；
- [ ] 旧聊天和 world 路径迁移；
- [ ] 旧代理方法、内部类型泄漏和直接能力调用清理。

## 当前风险

- 当前 `Stimulus.payload` 和 `PlannedAction.payload` 仍是任意 Mapping，不能直接作为目标强类型协议。
- 当前 stage 直接依赖 `agent.main_chat` 的回复类型，并直接执行 speech/singing。
- Agent 是每角色共享实例，交互认知上下文若没有 interaction 隔离会产生串话风险。
- stage 尚无同时管理 handle 生命周期、ActionPlanSink 队列和 realization worker 的机制。
- 多计划流程若没有稳定 plan ordinal、背压和 sink 幂等，会重复执行或产生乱序。
- 电话打断和通话关闭必须由 stage 实时执行，不能等待 Agent 或 LLM。
- 目标 Realtime 供应商是否能由同一会话稳定实现媒体写入与语义回合两个端口尚未通过契约测试验证，电话实现前必须针对目标 Qwen 接口验证。
- 现有电话详细设计及实现方向仍由 CallStream 消费供应商语义输出，容易形成绕过 Agent 的第二套回复心智，开始电话迁移前必须单独修订。
- 当前 VCPedia 新歌抓取和歌曲学习任务仍直接写数据库或触发动态；迁移前要先区分运行数据与角色知识/经历。
- Chat、Call、Toy 的 AgentOutputSink 尚未形成 interface spec，关闭通道、背压和不支持输出的失败规则还没有代码保障。
- 持久 Action 没有先定义幂等键时，重试会重复写记忆、动态或日程。

## 下一 PR

PRD 评审后，只提交 interface spec 和进度更新：固定 `HandleStimulusRequest`、四种 `InteractionSnapshot`、`ActionPlanSink`、`HandlingReport`、`ActionPlan`、`ExecutionContext`、各 stage 的 `AgentOutputSink`、`AgentOutput`、`ExecutionReport`、`RealtimeMediaIngress`、`RealtimeTurnPort`，以及 `SongKnowledgeDiscovered` / `SongLearned` 和对应 Action 的字段。该 spec 还要明确多计划顺序、背压、通道路由、关闭与拒绝、取消、迟到 Recall、刺激结算和 Realtime 会话生命周期。该 PR 不写测试和实现。
