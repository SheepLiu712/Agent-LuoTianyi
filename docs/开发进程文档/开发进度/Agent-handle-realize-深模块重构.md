# Agent `handle_stimulus / realize_action_plan` 深模块重构进度

> 最后更新：2026-09-05
>
> 当前阶段：工单 01 Stimulus 职责与校验 interface 修订
>
> 总体状态：进行中

## 对应文档

- PRD：[`Agent-handle-realize-深模块重构.md`](../需求说明（PRD）/Agent-handle-realize-深模块重构.md)
- interface spec：[`Agent-handle-realize-深模块重构.md`](../设计文档/Agent-handle-realize-深模块重构.md)
- 本地工单草案：[`issues/`](../../../.scratch/agent-handle-realize/issues/)
- 当前 Agent interface：[`agent/README.md`](../../项目说明/项目架构与接口（spec）/接口文档/agent/README.md)
- 当前 domain interface：[`domain/README.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/README.md)

## 本次提交

- 提交方式：按用户要求直接提交到当前 `refactor/agent` 分支，不创建 PR，避免触发自动审查。
- 目标：收窄 Stimulus 公开 interface 和审核标准，删除预防性的 source/persist/ephemeral 唯一组合矩阵。
- 范围：外部调用方选择强类型 Stimulus 并提供 source/ephemeral；目标 Stimulus 移除公开 `PersistPolicy`；持久化判断归 Agent 内部；构造只校验字段自身与变体结构；同步领域词汇、当前/目标 domain interface、本地工单和 GitHub Issue #60。
- 明确不包含：不修改测试或产品实现，不立即删除 PR #90 已实现的迁移期 `PersistPolicy` 字段/导出，不改变聊天、触摸、主动发言或 world 链路的可观察持久化结果。
- 前置事实：PR #105 已于 2026-09-05 合入 `refactor/agent`；其中字段/schema 稳定错误接口继续保留，组合非法错误边界由本次修订撤销。
- 验证及结果：5 份变更文档均通过严格 UTF-8 解码且无 Unicode replacement character；旧“来源矩阵/表外组合/Stimulus 与 interaction 组合白名单”等约束定向检索无残留；`git diff --check` 通过；GitHub Issue #60 已同步并回读确认。不运行产品 pytest、模型、TTS、GPU、设备或真实外部服务。

## 历史设计轮次目标与范围

- 把已形成的 Agent 深模块 PRD 转为可评审 interface spec，并按首轮评审意见收窄当前版本；
- 分开描述 Agent 对外行为与 Agent 内部 Handler / Skill / Store / Ledger / Reflection 行为；
- 明确定义 `PlanEmitter`、`InteractionContextStore`、Request/Execution Ledger、ReflectionCoordinator 和 ReflectionHandler 的职责及交互；
- 为 `handle_stimulus(request, plan_sink)` 与 `realize_action_plan(plan, execution_context, output_sink)` 给出完整类型提示；
- 为每个 Stimulus、InteractionSnapshot、Action、AgentOutput、报告和内部 job 字段补充类型、含义与约束；
- 把用户打字、打开/关闭图片选择页面定义为影响全部 pending stimuli 正式处理时点的协调刺激；
- 讨论并锁定歌曲抓取、模型处理、Agent 知识/记忆写入和跨进程学歌任务之间的边界；
- 区分 `world`、`world_clock` 与长期 `WorldStage`，并区分 world 领域定时和 stage 交互定时；
- 让 HandlingReport 分别表达 request 生命周期与逐 ID pending settlement，避免把“trigger 已处理”和“全部 pending 已消费”混为一谈；
- 用各 owner 的强类型 revision 替代含义不明的全局 StateVersion，并明确 stage 拥有打断决定、Agent 只协作取消；
- 把 ledger 定位为幂等事实账本，并明确 Reflection 由 settlement 时点唤醒、由 ReflectionPolicy 判断条件；
- 增加最终架构收束和当前行为兼容的验收标准，详细列出聊天信号、触摸、登录主动发言和全部 `WorldClock` 注册链路；
- 把整体重构拆为 30 个适合独立上下文和小 PR 的 expand—migrate—contract—accept 工单，写明真实 blocker、验收、验证和不确定时的参考顺序；
- 工单先保存为独立 Markdown，经用户确认后发布为 GitHub [#60](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/60) 至 [#89](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/89)。
- 固定 Agent 内 `handlers / skills / context / planning / ledgers / reflection` 的目标目录所有权、允许/禁止依赖和当前文件的渐进迁移路线；
- 明确 `agent/skills` 是角色语义层、既有 `capabilities` 是技术实现层，二者不一对一镜像，Handler 只能依赖强类型 Skill；
- 把目录与依赖约束同步到实际承担相应迁移的本地工单和 GitHub Issue，使开发者只读单张工单也不会误建旁路。

该历史设计轮次只修改 SPEC、本地工单、对应 GitHub Issue 和进度文档；未修改产品代码、测试、客户端/网络协议或现有运行行为。

## 已完成

- [x] Agent、stage、Adapter、world、subconscious、capabilities 和 AgentRuntime 的职责划分；
- [x] `handle_stimulus` / `ActionPlanSink` / `HandlingReport` 的外部行为与完整类型签名；
- [x] `realize_action_plan` / `AgentOutputSink` / `ExecutionReport` 的外部行为与完整类型签名；
- [x] PlanEmitter 的 draft、身份、ordinal、Request Ledger 和外部 sink 协作设计；
- [x] InteractionContextStore 的隔离键、临时字段、revision 更新、TTL 和清理边界；
- [x] Request Ledger 与 Execution Ledger 的不同职责、记录内容和 ReflectionCoordinator 读取关系；
- [x] ReflectionHandler 的输入、输出、允许调用的 Skill，以及不得输出/递归 handle 的约束；
- [x] Chat、Toy、World 三种当前版本 InteractionSnapshot；
- [x] 所有当前版本 Stimulus 变体的语义、字段类型、字段用途和合法 Interaction；
- [x] `UserTyping`、`ImageSelectionOpened`、`ImageSelectionClosed` 对 pending 等待、旧 handle 取消和重评的约定；
- [x] 所有当前版本 Action、AgentOutput 和报告字段的语义、类型与约束；
- [x] `ChangeExpression` 改为 `Say` / `Sing` 内嵌值对象，不再作为独立 Action；
- [x] 移除 `PerformHaptic` / `HAPTIC`，明确触摸反馈仍使用音频、文字和表情；
- [x] `RecordIntentionalMemory`、`UpsertSongKnowledge`、`RecordLearnedSong` 改为 Agent 内部状态变更 Skill；
- [x] `RequestSongLearning` 保留为需经 realize 与 Execution Ledger 结算的持久外部长任务 Action；
- [x] 歌曲抓取/机械模型处理在 world/capability，稳定候选与完成事实再触发 Stimulus，角色意义判断和知识接纳留在 Agent；
- [x] 自动记忆、上下文压缩、用户画像和重要日期检查的内部异步 Reflection 设计；
- [x] `world` 作为外部事实/效果所有者、`world_clock` 作为时间驱动、`WorldStage` 作为人格—箱庭持续交互协调器的边界；
- [x] world 领域定时与 stage pending 重评定时的不同产生和路由链；
- [x] Request/Execution Ledger 的幂等用途、被动证据职责，以及不直接触发 Reflection 的约束；
- [x] façade settlement notice、ReflectionPolicy 和上下文长度触发压缩之间的协作；
- [x] stage 打断权、Agent cancellation 协作、plan sink revision 校验和 output/Adapter 即时通道控制的分工；
- [x] `HandlingReport.request_status` 与 considered/consumed/retained pending IDs 的正交结算语义；
- [x] `interaction_revision`、`activity_revision`、`schedule_revision` 和 `context_revision` 的所有权与校验边界；
- [x] Agent 只保留两个业务 interface、内部类型不导出、旧 AgentRuntime/CharacterRuntime/capability 旁路最终删除的架构验收硬门槛；
- [x] 文字、图片、打字、图片选择、普通超时、旧判断作废和部分 pending 结算的当前聊天行为基线；
- [x] 触摸预制音频、表情恢复、瞬时非持久输出、快速路径失败回退和触摸合流行为基线；
- [x] 首次登录、长时未登录、当天首次登录、同日重复登录和通知 claim 的主动发言行为基线；
- [x] 当前 `WorldClock` 九类注册任务的调度、实际动作、失败/跳过语义和目标收束路径；
- [x] `Say.prepared_audio_ref` 与 `OutputDelivery`，用于表达触摸瞬时反应和首次登录预制音频，而不增加独立 HAPTIC 或表情 Action；
- [x] Call/Realtime、`UserJoinedActivity`、`ActivityInterrupted` 和原 5.5 相邻接口移出当前版本；
- [x] 30 个独立 Markdown 工单草案，覆盖强类型协议、Agent 内核、聊天、Reflection、触摸、主动发言、Toy、WorldStage、九类 WorldClock 链路、旧路径删除和最终验收；
- [x] 每个工单写明 `What to build`、blocker、SPEC 优先的决策规则、范围、验收、测试证据、明确不包含和交接要求；
- [x] SPEC 增加工单执行约定、TDD/小 PR 要求、expand—migrate—contract 顺序、完整依赖表和可立即开始的 frontier；
- [x] 用户确认无需继续拆分，30 个工单已按依赖顺序发布为 GitHub #60—#89，Issue 内 Blocked by 使用真实编号；
- [x] Agent 目标目录按公开 domain 协议、façade、三类 Handler、四类 Skill、临时 context、planning/ledger 和 reflection 协调层明确所有权；
- [x] 固定 external→domain/façade、Handler→Skill/context/planning/ledger、Skill adapter→subconscious/capability 的单向依赖，并列出禁止的外部内部包导入、Handler 直连 capability/database/runtime 和 Skill 反向依赖；
- [x] 明确 Handler 行为族拆分标准、Skill 与 capability 的语义/技术边界、context 只保存 interaction-scoped 临时工作集和检索证据；
- [x] 为 `luotianyi_agent.py`、`main_chat.py`、`response_realizer.py`、`agent/reflex`、`affection_manager.py`、`text_cleaning.py`、CapabilityManager 和 AgentRuntime/CharacterRuntime 写明渐进迁移归属；
- [x] 增加 A9 包所有权与依赖方向验收门槛，并更新 contract/集成验收工单的 A1—A9 范围；
- [x] 将目录/依赖/迁移约束同步到受影响的本地工单与 GitHub Issue；纯机械 world 工单继续明确不进入 Agent；
- [x] 本轮 SPEC 架构规划修订和本进度更新。

## 待评审与未验证

- [x] PR #91 曾为 22 个 `StimulusKind` 固定 source 与 persistence 组合；本次用户复审确认该设计过度防御，现已由“调用方显式提供 source、Agent 内部判断持久化、无组合白名单”的新 SPEC 取代；
- [x] scheduler/`world_clock` 继续明确为时间驱动和投递机制，不是新的语义 source，也不得覆盖外部调用方已经填写的 source；
- [x] 已删除没有当前生产者的 `StimulusSource.SYSTEM`；同时删除仅表示触发机制、与 source 定义冲突的 `SCHEDULER`；
- [x] PR #91 已获 owner 批准并 squash merge 到 `refactor/agent`；PR #90 的 interface 前置门禁已经闭合；
- [x] PR #90 的首个公开 domain seam 契约测试已获 owner 批准；PR #94 已将最小 Green 实现 squash merge 到 PR #90，形成当前完整 Green 候选；
- [x] Red：`conda run -n agent python -m pytest tests/domain/test_agent_handle_contract.py -q` 因 `ModuleNotFoundError: No module named 'src.domain.agent'` 在收集阶段失败（1 error，0.77s）；
- [x] Green：同一 focused 命令在当前完整候选上为 `1 passed in 0.18s`；
- [x] 已实现 `src.domain.agent` 的 `TextMessage` 最小切片，并让旧 Stimulus 复用同一四成员 `PersistPolicy`；该字段/导出现在只作为尚未迁移的当前实现，不再属于目标 interface；
- [x] 已同步 domain 当前/目标 interface 文档，明确 PR #90 的现状与本次目标差异，不能把迁移期合法样例解释成唯一组合；
- [x] PR #105 已实现 Stimulus 字段/schema 构造错误的 interface 设计；本次保留稳定异常和错误码，删除组合非法触发条件；
- [x] 已明确 reviewer 只能阻塞字段自身、schema、幂等持久化和当前行为回归问题，不得要求理论组合矩阵、笛卡尔积测试或无失败依据的防御分支；
- [ ] 目标 `TextMessage` 尚未通过 TDD 移除公开 `persist_policy`；Agent 内部持久化判断及同一 `stimulus_id` 的幂等事实也尚未实现；
- [ ] 工单 01 的其余 Stimulus、InteractionSnapshot、HandleStimulusRequest、CancellationToken、HandlingReport、稳定枚举和错误族测试尚未开始；
- [x] PR #90 时 `tests/domain -q` 为 `1 passed in 0.18s`；Ruff、py_compile、BasedPyright 和 `git diff --check` 通过；三处公开路径导出的 `PersistPolicy` 为同一对象且四成员完整。该证据只描述迁移期当前实现；
- [ ] 离线回归为 `400 passed, 4 deselected, 6 failed`；当前 `refactor/agent` 对照为 `399 passed, 4 deselected, 6 failed`，失败集合一致，未发现本切片新增回归，但仓库默认回归门禁仍未全绿；
- [ ] no-excuse 检查仅报告旧 `Stimulus` dataclass 未使用 `slots=True`；本切片不顺带改变旧对象布局；
- [ ] 本次纯文档提交未运行真实 LLM、TTS、设备或生产环境验证；
- [ ] `ImageSelectionClosed` 与图片消息到达顺序需要在后续测试/实现讨论中确认；关闭信号本身不携带图片内容；
- [ ] `RequestSongLearning` 的持久任务 Adapter、任务状态和完成 Stimulus 事务边界尚未选择具体实现；
- [ ] Agent 自有状态变更与 Reflection 之间的 evidence 去重键、revision 冲突策略只有目标语义，尚未落实；
- [ ] Reflection 的可靠接受、至少一次投递和 shutdown 保留策略只有目标契约，尚未选择具体 Adapter；
- [ ] InteractionContextStore、Request Ledger、Execution Ledger 尚未实现，多用户/多 interaction 隔离仍是实现风险；
- [ ] 目标 `handlers / skills / context / planning / ledgers / reflection` 目录尚未实现；本轮只锁定所有权和迁移顺序，禁止先提交空包骨架宣称完成；
- [ ] `WorldStage`、world 事实投递和现有 WorldRuntime/WorldClock 的迁移已经拆为工单，但具体实现仍未开始；
- [ ] 各 ReflectionPolicy 的上下文阈值、证据准入和调度频率尚未选择实现参数；
- [ ] 各 typed revision 与现有数据库/任务记录的映射尚未验证；
- [x] 已创建 `ready-for-agent` 仓库标签，并应用到 #60—#89 全部实现工单；
- [ ] `WorldClock` 九类链路来自当前源码和配置的静态盘点，尚未逐项运行真实网络、LLM、唱歌模型或数据库任务；
- [ ] 当前歌曲抓取与学歌任务仍直接写数据、刷新库或发布动态，与目标 Stimulus 边界不同；
- [ ] 当前 `Stimulus.payload` 和 `PlannedAction.payload` 仍是任意 Mapping，目标强类型联合尚未实现；
- [ ] 先前整体 SPEC 编写轮次未运行真实 LLM、TTS、设备或生产环境验证；对应实现工单必须分别记录实际验证。

## 下一步

先按修订后的 Issue #60 重新规划下一个 Red-only 切片：从目标 `TextMessage` 公开构造参数中移除 `persist_policy`，只覆盖字段自身/schema 的最小错误场景，不再开发或测试 source/kind/ephemeral 组合校验。Agent 内部持久化判断作为独立可观察行为切片，在明确从哪个 Agent interface 验证幂等会话记录和记忆候选后再进入测试。
