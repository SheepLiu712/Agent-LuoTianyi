# Agent `handle_stimulus / realize_action_plan` 深模块重构进度

> 最后更新：2026-09-05
>
> 当前阶段：工单 01 `TextMessage` 非法持久化组合 Red-only 测试
>
> 总体状态：进行中

## 对应文档

- PRD：[`Agent-handle-realize-深模块重构.md`](../需求说明（PRD）/Agent-handle-realize-深模块重构.md)
- interface spec：[`Agent-handle-realize-深模块重构.md`](../设计文档/Agent-handle-realize-深模块重构.md)
- 本地工单草案：[`issues/`](../../../.scratch/agent-handle-realize/issues/)
- 当前 Agent interface：[`agent/README.md`](../../项目说明/项目架构与接口（spec）/接口文档/agent/README.md)
- 当前 domain interface：[`domain/README.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/README.md)

## 本 PR

- PR：[#106](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/106)（分支 `test/agent-dm-01-text-message-validation`，目标 `refactor/agent`，Red-only Draft，等待评审）
- 目标：从 `src.domain.agent` 公开接口锁定 `TextMessage` 持久化策略与生命周期不符合唯一矩阵时的稳定构造失败。
- 范围：参数化覆盖 `NONE/False`、`EPHEMERAL_ONLY/True` 和 `CONVERSATION_AND_MEMORY_CANDIDATE/True` 三个代表性非法组合；断言直接构造抛出 `InvalidStimulusError`，且只读取稳定 `code="CONTRACT_INVALID_STIMULUS"` 与 `retryable=False`。
- 明确不包含：不写产品实现；不测试 schema、目标角色、字段类型、source、其他 Stimulus、InteractionSnapshot、request/report、Agent façade 或生产调用链迁移。
- 前置门禁：Stimulus 构造错误 interface 设计 PR [#105](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/105) 已获自动审查通过并于 2026-09-05 squash merge 到 `refactor/agent`，合并提交 `b90b29f`。
- 验证及结果：`conda run -n agent python -m py_compile tests/domain/test_agent_handle_contract.py` 通过；`conda run -n agent python -m pytest tests/domain/test_agent_handle_contract.py -q -p no:cacheprovider` 在收集阶段 exit 2，仅因 `ImportError: cannot import name 'InvalidStimulusError' from 'src.domain.agent'` 失败（1 error，0.47s），符合已批准公开错误接口尚未实现的预期 Red；`git diff --check` 通过。本 Red-only PR 未运行产品实现后的 Green 回归或真实外部服务。

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

- [x] PR #91 已为全部 22 个 `StimulusKind` 固定唯一 `StimulusSource`；scheduler/`world_clock` 明确为时间驱动和投递机制，不是语义 source；
- [x] PR #91 已固定全部 kind 的 `PersistPolicy / ephemeral` 唯一合法组合和表外稳定失败规则，并决定新旧 Stimulus 协议复用单一 `PersistPolicy` 类型；
- [x] 已删除没有当前生产者的 `StimulusSource.SYSTEM`；同时删除仅表示触发机制、与 source 定义冲突的 `SCHEDULER`；
- [x] PR #91 已获 owner 批准并 squash merge 到 `refactor/agent`；PR #90 的 interface 前置门禁已经闭合；
- [x] PR #90 的首个公开 domain seam 契约测试已获 owner 批准；PR #94 已将最小 Green 实现 squash merge 到 PR #90，形成当前完整 Green 候选；
- [x] Red：`conda run -n agent python -m pytest tests/domain/test_agent_handle_contract.py -q` 因 `ModuleNotFoundError: No module named 'src.domain.agent'` 在收集阶段失败（1 error，0.77s）；
- [x] Green：同一 focused 命令在当前完整候选上为 `1 passed in 0.18s`；
- [x] 已实现 `src.domain.agent` 的 `TextMessage` 最小切片，并让旧 Stimulus 复用同一四成员 `PersistPolicy`；
- [x] 已同步 domain 当前 interface 文档，记录 `src.domain.agent` 公开路径、`TextMessage` 字段与不变量、无副作用及当前仅支持合法构造的校验边界；
- [x] Stimulus 构造错误 interface 设计 PR #105 已通过并合入 `refactor/agent`；
- [ ] `TextMessage` 非法持久化/生命周期组合 Red-only 契约测试等待评审；
- [ ] 工单 01 的其余 Stimulus、InteractionSnapshot、HandleStimulusRequest、CancellationToken、HandlingReport、稳定枚举和错误族测试尚未开始；
- [x] `tests/domain -q` 为 `1 passed in 0.18s`；Ruff、py_compile、BasedPyright 和 `git diff --check` 通过；三处公开路径导出的 `PersistPolicy` 为同一对象且四成员完整；
- [ ] 离线回归为 `400 passed, 4 deselected, 6 failed`；当前 `refactor/agent` 对照为 `399 passed, 4 deselected, 6 failed`，失败集合一致，未发现本切片新增回归，但仓库默认回归门禁仍未全绿；
- [ ] no-excuse 检查仅报告旧 `Stimulus` dataclass 未使用 `slots=True`；本切片不顺带改变旧对象布局；
- [ ] 本 PR 未运行真实 LLM、TTS、设备或生产环境验证；
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

提交 `TextMessage` 非法持久化/生命周期组合 Red-only Draft PR 并等待评审；通过后另开最小 Green 子 PR，只实现 `InvalidStimulusError` 公开接口和该组合校验。
