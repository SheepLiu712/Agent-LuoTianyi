# Agent `handle_stimulus / realize_action_plan` 深模块重构进度

- 大目标：以两个有限 Agent interface 统一角色对刺激的认知决策与动作实现，逐步迁移聊天、玩偶和 world 调用链，并最终删除旧 AgentRuntime 业务代理和任意 Mapping 协议。
- PRD：[`Agent-handle-realize-深模块重构.md`](../需求说明（PRD）/Agent-handle-realize-深模块重构.md)
- 总体设计背景：[`Agent-handle-realize-深模块重构.md`](../设计文档/Agent-handle-realize-深模块重构.md)
- interface spec 索引：[`Server 模块接口文档`](../../项目说明/项目架构与接口（spec）/接口文档/README.md)
- 对应工单：[GitHub #60—#89](https://github.com/SheepLiu712/Agent-LuoTianyi/issues?q=is%3Aissue%20number%3A60..89)
- 总体状态：进行中

## 已完成事实

### 2026-09-15 #89 验收前置：行为不变量与副作用清单

- 交付物：`docs/开发进程文档/设计文档/行为不变量与副作用清单（#89 验收前置）.md`。
  逐链路列全行为不变量与副作用（爬取／落库／LLM／发送／调度／文件／去重），并给出「旧架构实现 @9ed8d1c → 新实现位置 → 迁移 PR」对照。
- 覆盖：§1 全局架构不变量 G1–G10；§2–§18 共 17 类链路（聊天主链、交互控制与取消、主动提醒、首登欢迎、反思与记忆、明确记忆意图、慢召回多计划、citywalk、VCPedia、学歌、动态互动、日记、B 站/QQ/清理、媒体链、输出与发送面、调度与生命周期、失败与部分效果）；附录 A 副作用矩阵、附录 B 旧→新映射、附录 C 未验证与风险（C1–C10）。
- 用途：作为 #89 的唯一前置清单；每条不变量在 #89 中标注「已验收（测试名）」或「未验收（附 C 编号）」。
- 说明：旧架构引用统一标注 `@9ed8d1c`（切片 29 已删除的代码，用 `git show 9ed8d1c:<path>` 查阅）；本文件不改变任何实现。

### 2026-09-15 旧入口与旁路清理（#88）

- owner 决策：18/20 判定为超范围（本次重构不引入完全的新功能）；主动提醒边界采纳 Stage 侧 `DueEventProvider` 窄端口（选项 A）。
- 执行前证据：旧会话 `ConversationService` 只是包装器，持久化最终委托同一 `database_manager.conversation_service`；旧 `ProactiveTopicMaker` 与 `EventStoreDueEventProvider` 使用同一 `database_manager.event_store`，通知身份均为 `(event_id, user_id, trigger_key, character_id)`。
- Batch 1：删除 `ExecutionLedger`、`RequestLedger`、`PlanOutbox` 三个无生产实例模块及无调用者 `get_GCSM()`；公共 `interrupt/query/cancel/wait` 核对未发现旧会话无调用者 API，`WorldStage.wait_idle` 等真实在用接口保留。回归 **1023 passed、2 skipped**。
- Batch 2：切断登录回退与旧后台绑定，删除 `chat_pipeline/*`、`ProactiveTopicMaker`、无剩余调用者的 `GlobalSpeakingWorker`、`ChatSessionManager`、`ChatStreamManager`、SystemRuntime 构造/访问器，以及 AgentRuntime 八个旧业务代理和默认 conscious locator；保留 `database_manager.conversation_service`、EventStore、Stage 端口及新 `ResponseCompositionSkill` 仍调用的 `generate_topic_reply_for_pipeline`。回归 **1018 passed、2 skipped**；减少 5 项均来自删除的活跃旧链测试 `tests/agent_runtime/test_legacy_agent_access.py`。
- 延迟测试：改动前合并运行相关文件为 **125 passed、2 failed、13 errors**；改动后存续相关文件为 **68 passed、13 errors**。13 个 error 两边均因 `--noconftest` 禁用 `tests/agent_runtime/conftest.py` fixture；改动前两项失败位于随后删除/裁剪的旧链覆盖。纯旧链测试文件随实现删除，混合文件仅移除旧对象用例并保留 ClientLLM、TTS、运行时关闭/回滚断言。
- 未验证范围：未连接真实客户端、真实 LLM/TTS/GPU、生产数据库或外部网络；全量 Ruff 仍报告触及历史文件的既有风格债，删除相关生产符号的引用扫描为零。

### 2026-09-15 登录与周期提醒的 claim 与空闲规则（#76）

- 交付行为：新增 Stage 侧 `DueEvent`/`DueEventProvider(list_due/claim/release)`，由 `SystemRuntime` 用 EventStore 适配器装配；候选在 claim 前过滤支持类型、角色、个人用户与已通知状态。当天首次普通登录合并所有成功 claim 的到期事实；world 每 300 秒只唤醒 Stage 扫描，ChatStage 按 30 秒空闲阈值、每流随机一项投递。登录与周期共享 `(event_id,user_id,character_id,trigger_key)` 原子 claim；处理失败、无计划、取消、离线或执行失败 release，全部计划成功后保留 claim。
- Agent 与边界：到期提醒构造成 `ProactivePromptDue`，内容与输出继续唯一经过 `handle_stimulus`／`realize_action_plan`；#75 的 `first_login` 预制欢迎分支未改变。`ProactiveTopicCheckTask` 不再调用旧 `ProactiveTopicMaker`／`TopicReplier`，维护包不进入 handler。
- 配置与测试：生效键为 `world.proactive_topic_check.clock_config.params.interval_seconds=300`、`stage_manager.stage.proactive_idle_seconds=30`、`stage_manager.stage.login_reminder_wait=1`、`stage_manager.return_user_threshold_seconds=432000`。新增 `tests/stage/test_proactive_due_dispatch.py` 并登记白名单，更新 world 唤醒和登录路由回归；完整套件与 ruff 结果见本切片交付报告。
- 取舍：按提案选项 A 实现最小公开窄端口；`trigger_key` 直接沿用 EventStore 到期查询返回值。新增接口请 owner 复核；未引入 Ledger/outbox/重投/进程恢复，也未经过 WorldStage。

### 2026-09-15 日记筛选、生成与私密发布（#84）

- 交付行为：`DiaryTask` 删除 `CharacterRuntime` 依赖、模型可用性检查（`ensure_llm`）与直接发布调用；保留 00:00 调度、当日每用户对话统计、`≥50` 入选、当天已有日记排除、超 20 人随机取 20、每日唯一；`run_once` 为 async，对每个入选用户投递一条 `DiaryPlanningDue(local_date, timezone, trigger_id, owner_user_id)`（`user_id=None`），结算只来自 N1 端口：`created` 仅在实际提交日记动态效果时计，失败计 `failed`，未结算保持 `pending`，投递被拒只记录不重试；结果报 `diaries_created`/`diaries_failed`/`diaries_pending`。领域类型按 owner 裁决 N2 扩大：`DiaryPlanningDue` 新增非空 `owner_user_id`。
- Agent 侧：新增 `DiaryPlanningDueHandler`（生成正文→交付 `WriteDiary` 计划；素材为空或正文为空则明确失败）、`WriteDiaryHandler`（private、禁止评论、`source_type="diary"`、`source_id` 沿用 `diary:{character_id}:{user_id}:{date}` → `EffectRef(DYNAMIC_POST)`，失败 `DEPENDENCY_UNAVAILABLE` 不声称已提交）、`DiaryWritingSkill`（复用 `DiaryCapability` 的素材收集与日记提示词，能力新增 `generate_diary_body` 只生成不发布）；`AgentRuntime` 注册 `DIARY_PLANNING_DUE` 与 `WRITE_DIARY`，`WorldRuntime` 把结算路由交给日记任务。
- interface spec：`接口文档/domain/stimulus.md` 记录 `DiaryPlanningDue.owner_user_id`（N2）；`接口文档/world/README.md` 新增「日记」条；`接口文档/agent/README.md` 记录日记分支与两个处理器；`接口文档/domain/realization.md` 记录 `WriteDiary` 已有生产 handler。
- 验证及结果：`conda run -n agent python -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system tests/stage tests/adapter -q` → **1015 passed、2 skipped**（上一基线 1010 → +5；2 skip 为既有真实网络探测）。改写 `tests/world/test_world_task_diary.py`（阈值/上限/去重/模型不可用不再由 world 跳过/事实形状/结算驱动计数，且不再依赖 `CharacterRuntime`），新增 `tests/agent/test_diary_writing.py`（private 与禁止评论、按用户隔离、同来源幂等、空正文失败、发布失败不冒充效果），领域契约测试补 `owner_user_id` 非空白校验。
- 未验证范围：真实日记模型生成质量与当日对话素材充分性按运行环境人工验收；不含 29/30 收尾。

### 2026-09-15 动态回复与记忆、业务状态结算（#83）

- 交付行为：`DynamicInteractionTask` 删除 `CharacterRuntime` 依赖、模型可用性检查与内容生成；保留 600s 调度、待回复/待记忆目标的批量上限（10/20 与 10/20）、`dynamic_store` 的 reply/memory 状态列、来源唯一性防重复；**同时待回复又待记忆的同一目标一轮只投递一条** `DynamicObserved`（结构化线程 + 线程消息数作为该动态的单调修订号），回复与记忆共享同一条事实。状态只由 N1 结算写入：`replied` 仅在实际提交 `DYNAMIC_COMMENT` 效果时写，`ignored` 表示 Agent 明确不回复（含线程中已存在角色回复），`failed` 来自处理/执行失败，`written` 表示 Agent 已完成记忆方面处理；未结算保持 `pending`，投递被拒只记录不重试。
- Agent 侧：新增 `DynamicObservedHandler`（先独立提交记忆再读线程决定回复/忽略，线程重复回复防护，模型不可用明确失败）、`DynamicReplySkill`（按结构化线程还原生成视图、复用既有 `replier` 生成、按目标身份发布评论）、`DynamicTopicMemorySkill`（记忆写入 + 记忆轨迹事件，与回复解耦）、`ReplyDynamicHandler`（成功 `EffectRef(DYNAMIC_COMMENT, <评论 id>)`，失败 `DEPENDENCY_UNAVAILABLE` 不声称已提交）；`AgentRuntime` 注册 `DYNAMIC_OBSERVED` 与 `REPLY_DYNAMIC`，`WorldRuntime` 把结算路由交给动态互动任务。
- interface spec：`接口文档/world/README.md` 新增「动态互动」条；`接口文档/agent/README.md` 记录 `DYNAMIC_OBSERVED` 分支；`接口文档/domain/realization.md` 记录 `ReplyDynamic` 已有生产 handler。
- 验证及结果：`conda run -n agent python -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system tests/stage tests/adapter -q` → **868 passed、2 skipped**（本分支基线 856 → +12；2 skip 为既有真实网络探测）。world 侧改写为选择/上限/事实形状/未结算保持 pending/结算驱动回写/显式忽略/失败双方面/记忆方面单列共 6 项；新增 `tests/agent/test_dynamic_interaction.py` 7 项（原帖回复计划与评论效果、评论明确忽略、评论回复父节点与归属、线程已有角色回复不重复发布、模型不可用明确失败但记忆照常、记忆失败不阻塞回复、发布失败不声称效果）。
- 未验证范围与已知收窄：回复生成输入来自事实的结构化线程（原帖正文、有序评论与作者显示名）与角色上下文，**不再包含 world 侧的 `user_description`／`preferences` 等用户画像富化**——这些是世界侧存储富化，Agent 侧无既有公开读取路径；记忆列 `written` 表示 Agent 已完成记忆方面处理，记忆内部「抽取为空」与「写入异常」不再由 world 细分（异常在 Agent 侧记录与轨迹中可见）。以上两点需 owner 裁决是否补一个能力层读取接口或扩展结算载体，本切片不擅自扩大公开接口。本切片不含日记（25）。

### 2026-09-15 学歌派发、完成事实与学会后行为迁移（#82）

- 交付行为：`LearnSingSongsTask` 去掉 `CharacterRuntime` 依赖与动态发布，只保留凭据检查与刷新、愿望清单状态、下载/清理/模型处理、工件校验、媒体库刷新、情绪标签、通知文件、`new_song` 事件与 `already learned` 去重；`run_once` 改为 async，**只有工件验证通过**的新学会歌曲逐首投递 `SongLearned`（`learning_job_id`=`角色:本次任务时刻`、`song_id`=统一歌名、`completed_at` 带时区），结果改报 `submitted_count`。Agent 侧新增 `SongLearnedHandler`（先写角色经验再交付 `PublishDynamic` 计划）、`LearnedSongExperienceSkill`（经验写入角色自身事件记忆，作用域为角色 ID；同日同内容由既有事件记忆去重保证幂等；写入失败只记录、不回滚学会事实）、`SongLearningDispatchSkill`（愿望清单派发 + 唱段/歌词材料读取）与 `RequestSongLearningHandler`（成功 `EffectRef(SONG_LEARNING_JOB, ...)`，重复请求 `ALREADY_COMPLETED`，能力缺失 `DEPENDENCY_UNAVAILABLE`，不等待完整学习）。
- interface spec：`接口文档/world/README.md` 的「世界事实投递（21–25 迁移中）」新增学歌条；`接口文档/agent/README.md` 记录 `SONG_LEARNED` 分支、经验技能与两个行动处理器；`接口文档/domain/realization.md` 记录 `RequestSongLearning` 已有生产 handler。
- 验证及结果：`conda run -n agent python -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system tests/stage tests/adapter -q` → **856 passed、2 skipped**（本分支基线 846 → +10；2 skip 为既有真实网络探测）。新增 `tests/agent/test_song_learned.py` 10 项（经验写入与非法参数、handler 交付发布计划/空正文失败/经验失败仍发布、派发成功/重复/能力缺失/取消、材料回落）与 world 侧学歌用例改写（事实字段、去重后逐首投递、`already learned` 不投递、旧 `dynamic_ids` 断言移除）；`tests/world/test_world_task_dynamics.py` 的学歌端到端用例改为 world→Agent→真实动态落库。
- 未验证范围：真实 QQ 凭据、下载、模型工件校验与唱段/歌词材料仍按运行环境条件人工验收；经验记忆使用「角色 ID 作为记忆作用域」的约定已在此记录，如需改为独立作用域需 owner 裁决。本切片不含动态互动（24）与日记（25）。

### 2026-09-15 citywalk 角色决策与动态发布迁移（#80）

- 交付行为：`CitywalkTask` 去掉 `CharacterRuntime` 依赖（含 `profile.display_name`，角色名改读配置），只保留概率抽样、地图/环境推进、报告生成、`travel` 事件与报告回写；散步成功后投递 `WorldObservation`（`observation_kind.value=citywalk_completed`、`fact_id=citywalk:<报告路径>`、`summary` 取报告叙述或目的地/经过地点/时长摘要、`world_revision` 取完成时刻），并按其 N1 结算端口登记回写订阅者。Agent 侧新增 `CitywalkObservationHandler`（`WORLD_OBSERVATION` 按 `observation_kind.value` 分派；生成角色化正文并交付 `PublishDynamic` 计划）、`PublishDynamicHandler`（成功报告 `EffectRef(DYNAMIC_POST, dynamic_id)`，失败 `DEPENDENCY_UNAVAILABLE`，取消 `CANCELLED`）与共享技能 `DynamicPublishingSkill`（文案生成 + 按来源身份幂等发布）。报告 `dynamic_id`／`dynamic_content`／`diary_text` 由结算回执写回；发布失败不撤销散步事实。
- interface spec：`接口文档/world/README.md` 新增「世界事实投递（21–25 迁移中）」记录 citywalk 事实字段与回写口径；`接口文档/agent/README.md` 记录观察分支与 `PUBLISH_DYNAMIC` 处理器行为；`接口文档/domain/realization.md` 记录 `PublishDynamic` 已有生产 handler 与效果引用。
- 验证及结果：`conda run -n agent python -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system tests/stage tests/adapter -q` → **846 passed、2 skipped**（本分支基线 837 → +9；2 skip 为既有真实网络探测）。新增 `tests/agent/test_citywalk_observation.py` 6 项（分支交付 PublishDynamic、生成失败不交付计划、按类别分派、发布成功/失败/取消三类结算）与 world 侧 citywalk 用例改写（事实字段、被拒丢弃、回执回写报告、摘要回落、无 `character_runtime`）；`tests/world/test_world_task_dynamics.py` 的 citywalk 端到端用例改为 world→Agent→真实动态落库并断言来源身份与回写。新增文件 Ruff 通过；`citywalk/task.py` 保留既有 `BLE001`/`DTZ005` 风格项。
- 未验证范围：真实高德地图、报告生成模型与动态文案模型的端到端效果仍按运行环境条件人工验收；本切片不含学歌（23）、动态互动（24）与日记（25）。
### 2026-09-15 VCPedia 候选知识接纳迁移（#81）

- 交付行为：VCPedia 任务改为只做抓取、字段规范化、来源检查与来源去重，产出强类型 `SongKnowledgeDiscovered`（来源 `vcpedia`、外部歌曲标识、由规范化内容派生的修订号、供应商无关的 `SongKnowledgeCandidate`），逐条经长期 `WorldStage` 的 `WorldFactSink.submit(...)` 投递；world 不再写入歌曲知识或关键词索引。Agent 侧新增 `SongKnowledgeHandler` 与共享技能 `SongKnowledgeAcceptanceSkill`：按名称/safe name 幂等接纳，知识与关键词索引在同一幂等边界内写入（关键词写入失败回滚知识行），不产生任何 ActionPlan 或外部效果；`already learned`/候选不等于学歌请求的语义保持不变。
- interface spec：`接口文档/world/README.md` 新增「世界事实投递（21–25 迁移中）」记录投递事实与统计口径；`接口文档/agent/README.md` 记录接纳处理器与技能的归属与幂等边界。统计口径按实施规格 N3 裁决改为 `discovered`/`skipped_existing`/`fetch_failed` 与 `submitted`/`rejected`，不再声称 `added`。
- 验证及结果：`conda run -n agent python -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system tests/stage tests/adapter -q` → **840 passed、2 skipped**。新增 9 项 agent 侧用例（幂等写入与关键词可查、二次接纳跳过且不重复、关键词失败回滚知识、处理器四类结算与非法刺激拒绝、空白介绍由领域类型拒绝）与 2 项 world 侧用例（候选投递为世界事实、收集阶段不写入任何知识）；既有 world 任务用例改写为新统计口径。新增与改动文件 Ruff 通过。
- 未验证范围：真实 VCPedia 抓取、反爬兜底与 LLM 结构化仍依赖运行环境的 `activated`/网络条件，按既有真实探测口径验收；本切片不含 citywalk/学歌/动态/日记迁移（21/23/24/25）与执行结算端口（N1）。

### 2026-09-15 世界侧结算端口（21/24/25 共同前置）

- 交付行为：新增 `world/world_settlements.py` 的 `WorldSettlementRouter`，由 `WorldRuntime` 持有（`WorldRuntime.settlements`），在 `SystemRuntime.get_world_stage` 创建实例时接到 `WorldStage`；`WorldStage` **新增**可选窄回调 `on_handling_settled(request, report)`（在报告通过一致性校验并应用到 pending 之后调用），既有 `on_execution_finished` 语义不变。任务在投递事实前按刺激 ID 登记订阅者，随后收到 `FactHandlingOutcome`（`request_status`/`consumed`/`error_code`/`plan_ids`，`ignored` 表示明确处理但无计划）与 `FactPlanOutcome`（计划、执行报告与已提交 `EffectRef`）；多计划事实按 `emitted_plan_ids` 计数，最后一个计划结算后自动撤销登记，投递被拒用 `discard` 撤销。订阅者异常与未匹配结算只计数并记录，不打断 Stage。
- interface spec：`接口文档/stage/README.md` 记录新回调的调用时机与语义；`接口文档/world/README.md` 记录端口的登记、回执与清理契约。实施依据为 [World 链路迁移实施规格（21-25）](../../设计文档/World链路迁移实施规格（21-25）.md) 的 N1 裁决（选项 A，不改 #152 既有成员语义）。
- 验证及结果：在 `server` 使用 `conda run -n agent python -m pytest tests/stage tests/world tests/agent tests/agent_runtime tests/domain tests/system tests/adapter -q` → **837 passed、2 skipped**（2 skip 为既有真实网络探测）；新增 `tests/stage/test_world_settlement_wiring.py` 8 项用例，覆盖无计划结算即撤销登记、失败不消费、多计划按序结算与最后撤销、未匹配计数、订阅者异常隔离、非法/重复登记与幂等 discard，以及真 `WorldStage` 装配下处理结算与执行结算（含 `EffectRef`）到达订阅者。新增文件 Ruff 通过，`git diff --check` 干净。
- 未验证范围：本切片只是端口与装配，不含任何 world 任务的迁移（21/23/24/25 消费该端口）；`DiaryPlanningDue` 目标用户字段（N2）与 24 的 ignore 语义落地仍在各自切片内验证。

### 2026-09-15 生产聊天连接接入 Stage（#66）

- 交付行为：生产 `/chat_ws` 在认证后用默认角色调用 `StageManager.connect`，聊天业务事件经同步 `WebSocketService.try_accept_stimulus_event` 和共享 `WebSocketAdapter` 转为领域 Stimulus 投递给 ChatStage，ACK/NACK、认证、心跳、客户端模型响应和接入限流仍留在 user_interface；路由 `finally` 统一调用 `StageManager.disconnect`，保留期内重连复用同一 Stage/context/interaction。首次登录由 `UserInterface.login/auto_login` 直接调用 `StageManager.record_login(user_id, character_id, elapsed_from_last_login=None)`，回访登录继续使用旧 `chat_session_manager.on_user_login`，未恢复 `RETURN_LOGIN`。
- interface spec：[`adapter`](../../项目说明/项目架构与接口（spec）/接口文档/adapter/README.md)、[`stage`](../../项目说明/项目架构与接口（spec）/接口文档/stage/README.md)、[`system`](../../项目说明/项目架构与接口（spec）/接口文档/system/README.md)。
- 验证及结果：`tests/adapter/test_production_stage_wiring.py` 从生产路由证明连接、事件转刺激、Agent 输出回包、断线后重连复用同一 interaction；`tests/system/test_login_stage_routing.py` 证明两种认证入口仅迁移首次登录、回访登录保持兼容路径。`conda run -n agent python -m pytest tests/stage tests/adapter tests/system tests/agent_runtime -q` 为 **71 passed、1 个既有 Starlette/httpx 弃用警告**；新增测试 Ruff、触及生产文件排除其既有全文件告警后的 Ruff、compileall 与 `git diff --check` 通过。LSP 因工具工作区固定在主 checkout，拒绝诊断隔离 worktree 路径。
- 集成注意：本基线的 `try_accept_stimulus_event` 与 `receive_event` 为同步接口。若 slice-09 PR #155 先合入 `refactor/agent`，本分支 rebase 后必须把生产调用点适配为 `await ...`，并重新运行 adapter↔Stage 生产集成测试。
- 未验证范围：未连接真实客户端、生产数据库、LLM、TTS 或外部网络；聊天文本 handler 的真实认知与落库属于后续切片，不由本接线事实宣称完成。

### 2026-09-14 触摸预制反应与独立表情恢复（#74）

- 交付行为：新增公开 `RestoreExpression` Action 及生产 action handler；触摸 handler 先按旧区域别名和 10/30 秒频率策略准入（**默认**上限 8/16 次，区域集合与两个上限可由角色配置 `reflex.touch.fast_reply.policy` 覆盖），再包装旧 `TouchFastReplyBuilder` 的概率、manifest 随机音频和表情映射，成功时依次交付瞬时预制音频 SAY 与独立 `normal` 恢复计划。未知区域、频率超限、资源缺失、读取失败或快速分支未命中均返回非重试 `FAILED`、记录错误并丢弃，不走普通话题或 LLM 兜底。
- 生产接入：`TOUCH_INTERACTION` 从聊天预处理注册移出并绑定专用 handler；`RESTORE_EXPRESSION` 加入领域导出、计划白名单与生产 ActionRouter。触摸资源必须由 manifest 登记，使 MediaRef 可由 PreparedSpeechResources 解析；恢复 handler 在表情后提交正常消息终包，Stage/adapter 不检查 Action 类型且无专用分帧参数。
- 验证及结果：server 下运行 `conda run -n agent python -m pytest tests/domain tests/agent tests/stage -q`，审查修复后结果 **684 passed、1 warning（32.28s）**；warning 为既有 `test_handle_input_contract.py` 使用 zip 参数化的 PytestRemovedIn10Warning。
- 未验证范围：未运行完整 Server、真实客户端播放确认、生产资源目录、真实 LLM/TTS/GPU 或外部服务；本切片不删除仍供旧生产入口使用的 `try_handle_reflex`，只保证新触摸路径不调用该旁路。
- 复审修复（2026-09-15）：把触摸准入策略从写死常量改为**配置驱动**——新增角色配置 `reflex.touch.fast_reply.policy`（`allowed_regions` / `max_touches_10s` / `max_touches_30s`，缺省即旧值），由 `AgentRuntime` 在构造阶段校验（类型问题 `TypeError`、取值问题 `ValueError`）；频率窗口本身仍由领域 `TouchClickFrequency` 固定，故不提供窗口配置。验证：`conda run -n agent python -m pytest tests/domain tests/agent tests/stage -q` → **694 passed**；推迟文件 `tests/test_agent_reflex.py -q --noconftest` 与基座一致（1 passed）；本切片 own 文件 `ruff check` 通过，`agent_runtime.py` 余项均为既有基线。
### 2026-09-15 首次登录欢迎评审修正（#75）

- 修正事实：首次欢迎的两条 `Say` 表情固定为 `normal`，不再采用 manifest expression；登录 pending 按 `(user_id, character_id)` 幂等记录，使同一首次登录的每个目标角色各接收一次且重连不重放；首次登录到期时若 handle 数达到 `max_stimuli`，保留 pending 并延后重试，不超量启动或静默丢弃。
- 边界保持：Stage 仍只负责就绪、计时、容量准入及投递 `ProactivePromptDue(first_login)`，欢迎文案、顺序、表达和持久化仍由 Agent handler 拥有；生产认证/WebSocket 接线继续留给 #66，`RETURN_LOGIN` 继续关闭，旧 `activity_res.first_login` 配置保持不变。
- 验证及结果：server 下运行 `conda run -n agent python -m pytest tests/stage tests/agent tests/system tests/adapter -q` 为 **263 passed、1 个既有 Starlette/httpx 弃用警告**；触及文件 Ruff 与 compileall 通过，`git diff --check` 通过。LSP 因工具工作区固定在主 checkout，拒绝诊断隔离 worktree 路径。

### 2026-09-14 首次登录欢迎接入真实 handler（#75）

- 交付行为：本切片在 Stage/Agent 边界提供首次登录接收 seam：调用方用 `StageManager.record_login(user_id, character_id, ...)` 按角色记录事实，同一登录为每个启用角色各保留一个幂等 marker；ChatStage 完成连接绑定后开始约 1 秒同步窗口，以 `ProactivePromptDue(reason=first_login)` 调用真实 `handle_stimulus`。到期时 handle 容量已满则保留 pending 并延后重试，不突破 `max_stimuli`。`FirstLoginHandler` 按 `agent_runtime.proactive.first_login.prepared_names` 顺序从共享 `PreparedSpeechResources` 取得同源文字与受控音频引用，逐条持久化 `source=agent` 对话并各交付一个 expression 固定为 `normal` 的 CONVERSATION Say 计划；Say realization 产出完整音频和 message-end final package。缺失名称返回依赖失败并记录名称；`RETURN_LOGIN` 仍关闭。
- 配置与范围：使用现有 `agent_runtime.prepared_speech.manifest` 加 `agent_runtime.proactive.first_login.prepared_names`。生产接线（`server_main`、`UserInterface`、`SystemRuntime.record_user_login`）明确留给 #66，本切片不接管认证/WebSocket 生产入口；旧 `chat_session_manager.proactive_topic_maker.activity_res.first_login` 配置和读取器继续保留并服务当前生产链。也不包含到期事件提醒、周期 claim、WorldStage、MediaResolver 或触摸动作。
- 验证及结果：server 下运行 `conda run -n agent python -m pytest tests/stage tests/agent -q` 为 **237 passed**；`conda run -n agent python -m pytest tests/system tests/adapter -q` 为 **24 passed、1 个既有 Starlette/httpx 弃用警告**。相关 Python 文件 compileall 通过；LSP 因工具工作区固定在主 checkout，拒绝诊断隔离 worktree 路径，已记录为未验证项。
- 未验证范围：未连接真实生产数据库或客户端播放器；预制 WAV 通过临时真实文件和完整 Adapter/Stage/Agent/Say 链验证，未执行外部 TTS、LLM 或网络调用。
### 2026-09-14 长期 WorldStage 与世界事实投递（#78）

- 交付行为：新增按 `(character_id, world_id)` 长期复用的 WorldStage 与异步 `WorldFactSink`；Stage 持有 interaction/pending/cancellation、按 ID 结算事实，以同一长期 worker 串行执行计划，并在无实时通道时由 `NoChannelOutputSink` 明确拒绝输出。AgentRuntime 注册世界/活动事实 Handler，SystemRuntime 显式拥有 registry、`get_agent` 与关闭顺序；未迁移现有 world task，也未改变 WorldClock。
- interface spec：[`stage/README.md`](../../项目说明/项目架构与接口（spec）/接口文档/stage/README.md) 已记录当前接口、revision 归属、作用域复用和关闭事实。
- 验证及结果：在 `server` 使用 `conda run -n agent python -m pytest tests/stage tests/world -q`，142 passed、2 skipped；新增聚焦用例覆盖事实顺序、旧 interaction revision、同 worker 串行、无通道拒绝、关闭取消及 registry 复用/隔离。新增产品模块的 basedpyright error 级检查、聚焦 Ruff、compileall 与 `git diff --check` 通过。
- 未验证范围：四个既有 world 任务仍走兼容链路，真实网络探测两项按现有标记跳过；本切片不包含每日规划、活动 scheduler、歌曲/动态/日记任务迁移或生产外部通道验收。
### 2026-09-15 慢 Recall 的多计划回复策略（11b）GREEN

- 交付行为：`ResponseCompositionSkill` 新增内部两段式入口 `compose_staged`，返回 `ComposedResponse(provisional, pending)`——召回超过配置阈值仍未返回时给出一条完整的临时草稿，正式草稿留待调用方 `await formal()`；`compose` 的既有一次性语义不变。`ChatReplyHandler` 据此在同一 handle 内先交付临时计划（ordinal 1，紧随 ordinal 0 的 `StartThinking`），再等待正式结果并交付正式计划（ordinal 2）。两份计划各自完整、可独立实现（均为可直接播放的 `Say`），`plan_id` 与行动标识彼此独立（临时 `-t{n}`、正式 `-r{n}`），正式计划不修改也不引用临时计划，且两者携带相同的 `basis_interaction_revision` 与 `source_stimulus_ids`。交付正式计划前重新检查 `request.cancellation` 与交互依据修订：已取消或修订推进则不交付，迟到的召回结果被丢弃。临时计划交付失败按既有失败停止语义处理，不再调用 sink、不生成正式结果、`retryable=False`，无重试或补偿。
- 隔离与幂等：召回 future 全程留在本次 handle 内，不经公开接口回流，因此未新增 `RecallCompleted` 刺激或任何公开 Stimulus/Action，也不会递归进入处理器。召回命中经 `plans.context.recalled_memory` 按触发刺激 ID 归属写入 Stage 借出的 `InteractionContext`，由 Stage 在结算时按刺激清理；不存在 Agent 全局召回注册表，结果不跨用户或跨角色。`formal()` 可重复调用并返回同一结果，不重复生成。未引入 ledger、outbox 或自动重试。
- interface spec：新增 [`慢召回两段式回复`](../../项目说明/项目架构与接口（spec）/接口文档/agent/slow-recall-reply.md)，记录内部 `ComposedResponse`/`ComposedReply`/`compose_staged` 契约、两段计划的交付顺序与取消语义；`plan-emitter.md` 补充「同一次调用内的多份计划」；`agent/README.md` 增加索引。新增配置事实 `agent_runtime.reply_composition.slow_recall.{provisional_after_seconds,provisional_text,provisional_sound_content,provisional_tone,provisional_expression}`，用户可见的临时文案只来自该配置，处理器与技能内无字面文案；配置经 `AgentRuntime` 读入后由 `Skills.reply_composition_config` 交给技能。
- 验证及结果：工作目录 `server`，conda 环境 `agent`。`python -m pytest tests/agent tests/stage tests/domain -q` 为 702 passed；新增 `tests/agent/test_slow_recall_staged_reply.py`（8 passed，已登记 `_ACTIVE_TEST_FILES`），覆盖两份独立完整计划与连续序号、同一依据修订、召回按触发刺激归属、取消阻断正式计划并丢弃迟到结果、sink 失败停止且不重试、无 `RecallCompleted` 且不递归、配置驱动的临时文案及快召回/未配置时不产生临时草稿。延后文件以 `--noconftest` 与基线 worktree 对照，双方均为 39 passed，无新增失败。触及文件 `ruff check` 剩 6 项均为基线既有（`DTZ005`/`I001`），并顺带消除基线的一处 `UP035`；`git diff --check` 无输出。
- 未验证范围：未运行真实 LLM、生产向量库/数据库、TTS/GPU、真机；生产聊天是否切换到新门面仍由既有迁移切片负责。

### 2026-09-15 明确记忆请求与成功承诺边界（12）GREEN

- 交付行为：cognitive 层的 `ExplicitMemoryIntentSkill` 按 `agent.memory.explicit_intent` 配置和旧默认短语逐条识别明确记忆请求；`ChatReplyHandler` 在同一 handle 内先等待内部 `IntentionalMemoryCommit` 通过既有 `MemoryWriter` 写入私有长期记忆，且返回非空规范记忆 `record_id` 后才经回复组合 seam 交付表示已记住的 `Say`。提交异常或空标识返回 `FAILED / INTERNAL_ERROR`，保留本批 pending、`retryable=False`，不交付成功承诺。
- 隔离与幂等：提交始终使用 `plans.context.identity` 的非空 `character_id/user_id`；向量证据补充角色归属，向量命中必须反查到规范记忆正本才算已提交，孤儿向量不会触发成功承诺。同一输入重投在反查到既有正本时返回同一规范 `record_id` 且不新增记忆；批次中未命中显式记忆的文本继续进入普通回复主题。业务唯一性仍停留在既有存储边界的确定性正本 ID 和查重规则内，未引入 schema 级唯一约束，因此并发 check-then-insert 的残余竞态未在本切片扩展处理；未恢复 request/mutation ledger、outbox、自动重试、重复调用合并或新 Memory Action。
- interface spec：新增内部 `ExplicitMemoryIntentSkill`、`IntentionalMemoryCommit` 与 `MemoryCommitRevision`；记忆仍是 Agent 内部状态变更，不进入 `ActionPlan`。`memory.explicit_intent.{enabled,phrases}` 从草案更新为当前配置事实。
- 验证及结果：工作目录 `server`，conda 环境 `agent`；见本切片提交验证记录。
- 未验证范围：未运行真实 LLM、生产向量库/数据库、TTS/GPU、真机；生产聊天是否切换到新门面仍由既有迁移切片负责。

### 2026-09-14 图片预处理落库与混合输入顺序（09）GREEN

- 交付行为：新增 capabilities 侧 `MediaResolver` / `ResolvedMedia` 窄端口、永久 `PermanentMediaStore`、生产 `FilesystemMediaResolver` 和显式失败的未配置实现。WebSocket Adapter 复用现有 `user_image` 的 base64/MIME 协议，在构造 Stimulus 前永久保存原始字节，以认证用户和 client message 身份生成可重复的 UUID `MediaRef`；Agent 不保存媒体且只接触该引用。CapabilityManager、AgentRuntime、Skills 构造注入 `ImagePreprocessingSkill`；Handler 解析、校验、理解后一次写入用户媒体事实与系统机器描述事实，返回两个记录 ID 的 `PreprocessedInput`，不 emit、不消费。没有真实生产者的语音仍不接 ASR。
- 永久性、顺序与失败：媒体目录无 TTL、过期或自动清理；resolver 拒绝未知、空内容、非图片 MIME、损坏元数据和路径穿越。对话事实时间按 Stage 接收 revision 排序，图片内部媒体先于机器描述；新 context 持久化使用带微秒 ISO 时间，旧链路可继续写秒级格式。`datetime.fromisoformat` 和已修订的旧展示格式化器兼容两种格式，因此 DB/context 读取保持 A/B。失败在 VLM 前退出，不消费、不阻塞后续文本，也不回滚既有事实。
- interface spec：[`capabilities/README.md`](../../项目说明/项目架构与接口（spec）/接口文档/capabilities/README.md) 已记录端口、稳定失败和未决存储策略；[`system/README.md`](../../项目说明/项目架构与接口（spec）/接口文档/system/README.md) 已记录 `capabilities.media_resolution` 装配事实。
- 验证及结果：工作目录 `server`，conda 环境 `agent`。`python -m pytest tests/agent tests/stage tests/domain tests/adapter -q` 为 **718 passed**（2 条既有依赖弃用 warning）；新增 adapter/resolver/时间格式聚焦测试为 **36 passed**。触及文件 Ruff 与 `git diff --check` 通过；08 链既有 agent/stage/domain/adapter 测试未修改且继续通过。
- 未决与未验证：授权主体已在下述审查修复中收敛为认证上传用户；仍未决定大文件分块、解析/理解超时及图片/语音端口长期复用策略，未实现 ASR。未运行真实 VLM、生产目录权限/磁盘耗尽、生产数据库、客户端/真机、GPU 或完整 Server 外部链路。

#### 2026-09-15 对抗审查修复（09）

- 授权边界：此前提案把授权主体留作未决；本轮按 Issue #68 的越权拒绝要求建立保守默认——媒体归认证上传用户所有。metadata 持久 `owner_user_id`，principal-scoped resolver 要求当前 `owner_user_id`，跨用户在读取字节和 VLM 前返回 `MEDIA_UNAUTHORIZED`。
- 准入与限制：Adapter 先解析信封并创建窄引用候选，验证所有目标 Stage 存在且 `can_accept` 后才物化图片；`max_encoded_bytes` 在 base64 解码前检查，`max_bytes` 在永久写入前检查，超限为 `MEDIA_TOO_LARGE` 且无最终目录。解码、Pillow 完整验证和文件 I/O 经 `asyncio.to_thread` 离开事件循环。
- 原子与内容：永久写入使用唯一 staging 目录，完整写入后单次目录 rename 发布；并发重放相同内容复用，冲突拒绝，残缺/损坏目录稳定为 `MEDIA_UNKNOWN`。存储与 resolver 都用 Pillow 完整解码，坏图片为 `MEDIA_UNKNOWN`，实际格式与声明 MIME 不一致为 `MEDIA_UNSUPPORTED_TYPE`。
- 验证：聚焦授权/准入/线程/原子/内容及既有 Stage 用例 `python -m pytest tests/agent/test_media_resolution.py tests/agent/test_chat_preprocessing.py tests/adapter/test_websocket_adapter.py tests/stage/test_chat_stage.py tests/stage/test_concurrent_handling.py -q` 为 **73 passed**；完整 `python -m pytest tests/agent tests/stage tests/domain tests/adapter -q` 为 **726 passed**、2 条既有依赖弃用 warning。新媒体模块全规则 Ruff、触及旧文件的 import/undefined-name Ruff 及 `git diff --check` 通过。未验证真实 VLM、生产磁盘故障/权限、跨进程崩溃注入和客户端真机。
### 2026-09-14 批次回复的开始思考信号（11a）GREEN

- 交付行为：`ChatReplyHandler` 在有可回复内容时先交付一个仅含 `StartThinking` 的首计划（ordinal 0），再进入生成并交付正式回复计划。Stage 的 `_PlanSink` 消费该计划并发出 THINKING 呈现，最后一个思考请求结束时发出 WAITING（既有 Stage 行为）。无可回复内容时不产生思考信号。
- interface spec：无新增或扩大公开 interface；复用 `StartThinking`、`ActionPlanDraft` 与 `_PlanSink` 既有消费行为。
- Red/Green：Issue #67 明确不要求 SPEC→RED→GREEN 与阶段提交；本切片记录为单次 Green 候选。
- commit 或 PR：分支 `feat/agent-11-thinking-signals`（依赖 #132 的 `chat.py`，堆叠）。
- 验证及结果：`python -m pytest tests/agent/test_chat_reply.py tests/stage/test_chat_reply_settlement.py -q` 为 6 passed；白名单回归 834 passed、2 skipped。相关文件 LSP 无报错。
- 明确不包含（留待 11b）：慢 Recall 的「先临时完整计划、再正式计划」策略未实现，需要真实的慢召回信号来源。
- 未验证范围：未运行真实 LLM/TTS/GPU、真机或生产数据库；生产聊天仍走旧 ChatStream。

### 2026-09-14 回复结算后的反思接入（13/14）GREEN

- 交付行为：`ChatReflectionHandler` 从空占位改为真实反思——以本次已消费输入与近期 `source=agent` 回复拼成依据，经反思技能沉淀长期记忆；按阈值调用共享压缩技能生成并提交上下文压缩；随后更新用户画像（`summary` + `recent_conversation`）。不交付计划、不消费输入、不产生用户可见输出。
- interface spec：无新增或扩大公开 interface；复用 `mind.write_topic_memories`、`ConversationCompactionSkill.compact`、`mind.update_user_profile_by_context`。新增内部技能 `ReflectionSkill`（`agent/skills/reflection/consolidation.py`）。
- Red/Green：Issue #67 明确不要求 SPEC→RED→GREEN 与阶段提交；本切片记录为单次 Green 候选。
- commit 或 PR：分支 `feat/agent-13-reflection`（堆叠在 MediaRef 端口提案之上，本记录所在提交）。
- 验证及结果：工作目录 `server`，conda 环境 `agent`。`python -m pytest tests/agent/test_chat_reflection.py -q` 为 2 passed；`python -m pytest tests/agent tests/stage -q` 为 249 passed；`python -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system tests/stage tests/adapter -q` 为 834 passed、2 skipped。相关文件 LSP 诊断无报错。
- 测试夹具更新：`ChatReflectionHandler` 构造改为注入（反思 + 压缩），`test_handling_preparation.py`、`test_concurrent_handling.py`、`test_chat_reply_settlement.py` 传入 no-op 替身；假 context 的 `conversation` 补 `read()`。
- 明确不包含：日期识别未接入（旧 `detect_dates_for_topic` 依赖 `ExtractedTopic`，SPEC A7 禁止新调用方依赖）；`related_memories` 暂为空（注意力链尚未接入）。
- 未验证范围：未运行真实 LLM/GPU、真机或生产数据库；生产聊天仍走旧 ChatStream。

### 2026-09-14 真实聊天链路结算与取消验收（10）GREEN

- 交付行为：新增 `tests/stage/test_chat_reply_settlement.py`，用真实 `Agent`（文本预处理 + 批次回复 + 反思 + SAY 执行）经真实 `ChatStage` 验证：(a) 文本批次经期限触发后完成「预处理→回复→执行→结算」，pending 清空且 `user`/`agent` 记录按序落库；(b) 回复执行在途时到达新内容，旧回复被取消并丢弃，新批次重新回复并最终结算。
- interface spec：无新增或改变公开接口；本切片仅测试与测试夹具（假 context 的 `conversation` 补 `read()`）。
- Red/Green：Issue #69 是验证工单，无新增运行时行为，记录为验证切片；不制造人工 Red。
- commit 或 PR：分支 `feat/agent-10-settlement-verification`（堆叠在 08c 之上，本记录所在提交）。
- 验证及结果：工作目录 `server`，conda 环境 `agent`。`python -m pytest tests/stage/test_chat_reply_settlement.py -q` 为 2 passed；`python -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system tests/stage tests/adapter -q` 为 832 passed、2 skipped。
- 与 #69 验收项对照：取消（本切片真实链路覆盖）、部分消费（由既有 `tests/stage/test_concurrent_handling.py` 的按 ID 保留用例覆盖）、晚返回丢弃（由既有 stale deadline 用例覆盖）。本切片新增的是真实 handler 链路上的结算与取消证据。
- 未验证范围：尚未接入生产路由（#66），未运行真实 LLM/TTS/GPU、真机或生产数据库。

### 2026-09-14 批次回复的演唱决定接入（08c-2）GREEN

- 交付行为：`ChatReplyHandler` 在批次回复中执行演唱决定——用 `TextPreprocessingSkill.extract_terms` 从本批文本提取演唱尝试；从近期对话的 `SongContent` 记录推导「最近已唱片段」作为排除集；两者传入回复生成技能用于选择片段。生成演唱草稿时取回片段歌词并写入 `source=agent` 的 `SongContent` 记录（文本为「唱了《歌》+歌词」）。`ResponseCompositionSkill.compose` 新增 `excluded_segments` 参数并回填 `ReplyDraft.lyrics`。
- interface spec：无新增或扩大公开 interface；`TextPreprocessingSkill.extract_terms`、`build_sing_plan_for_topic(excluded_segments=...)`、`capability.singing.get_segment_lyrics` 均为现有能力。
- Red/Green：Issue #67 明确不要求 SPEC→RED→GREEN 与阶段提交；本切片记录为单次 Green 候选。
- commit 或 PR：与 08c-1 同属 PR 分支 `feat/agent-08c-reply-composition`（本记录所在提交）。
- 验证及结果：工作目录 `server`，conda 环境 `agent`。`python -m pytest tests/agent/test_chat_reply.py -q` 为 4 passed；`python -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system tests/stage tests/adapter -q` 为 830 passed、2 skipped。相关文件 LSP 诊断无报错。
- 明确不包含（留待 08c-3）：仍未接入「提取/注意力选择」（旧 `extract_topics`/`plan_topic_turn` 依赖 `UnreadMessage`/`ExtractedTopic`，SPEC A7 禁止新调用方依赖）；正式检索替换候选时按刺激 ID 清理尚未实现。
- 未验证范围：未运行真实 LLM/TTS/演唱音频、GPU、真机或生产数据库；生产聊天仍走旧 ChatStream。

### 2026-09-14 到期批次回复生成与落库（08c-1）GREEN

- 交付行为：`InteractionDeadline` 批次的 `ChatReplyHandler` 从 `prepared_inputs` 组装回复话题、渲染近期历史，经回复生成技能召回记忆并生成回复草稿，按接收顺序交付一个 `ActionPlan`（有序 `Say`/`Sing` 行动），并落库对应的 `source=agent` 正式对话记录；报告按 ID 消费本批（`consumed` 等于本批 pending）。
- interface spec：无新增或扩大公开 interface；复用 `ActionPlanDraft`、`Say`、`Sing`、`PreprocessedInput` 与 `context.conversation.append`。新增内部技能 `ResponseCompositionSkill`（`agent/skills/cognitive/response_composition.py`），包装 `mind.search_memory_context_for_topic`、`mind.build_sing_plan_for_topic` 与 `conscious.generate_topic_reply_for_pipeline`；`Skills` 新增内部 `register()` 以装配需要运行时依赖的技能。
- Red/Green：Issue #67 明确不要求 SPEC→RED→GREEN 与阶段提交；本切片记录为单次 Green 候选。
- commit 或 PR：分支 `feat/agent-08c-reply-composition`（堆叠在 08b 之上，本记录所在提交）。
- 验证及结果：工作目录 `server`，conda 环境 `agent`。`python -m pytest tests/agent/test_chat_reply.py -q` 为 3 passed；`python -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system tests/stage tests/adapter -q` 为 829 passed、2 skipped（2 skip 为 world 真实网络探测）。相关文件 LSP 诊断无报错。
- 明确不包含（留待 08c-2）：本切片未接入「提取/注意力选择」——旧 `extract_topics`/`plan_topic_turn` 依赖 `UnreadMessage`/`ExtractedTopic`，而 SPEC A7 禁止新调用方依赖这些旧类型；因此本切片以「整批作为一个回复话题」生成。`sing_attempts` 暂传空、最近已唱排除与歌词记录未接入。
- 未验证范围：未运行真实 LLM/TTS/GPU、真机或生产数据库；生产聊天仍走旧 ChatStream。

### 2026-09-14 演唱行动 SING 渲染（08b）GREEN

- 交付行为：注册 `ActionKind.SING` 的真实处理器 `SingHandler`。对既定的 `Sing(song_id, segment_id, expression)` 以 `CONVERSATION` 呈现方式输出「表情 → 完整音频块（`COMPLETE_FILE`）→ 消息结束（COMPLETED）」；片段不可用或无音频时输出 FAILED 终止包并返回 `AUDIO_EMPTY`，生成异常返回 `AUDIO_GENERATION_FAILED`，超时返回 `PROVIDER_TIMEOUT`。处理器不选择歌曲或片段、不恢复 `SONG_STATE`。
- interface spec：无新增或扩大公开 interface；复用 `Sing`、`AudioChunkDraft`、`ExpressionDraft`、`MessageEndDraft`。新增内部技能 `SingingSkill`（`agent/skills/expression/singing.py`）包装 `SingingCapability.sing` 并在 executor 中调用，由 `Skills` 装配。
- Red/Green：Issue #67 明确不要求 SPEC→RED→GREEN 与阶段提交；本切片记录为单次 Green 候选。
- commit 或 PR：分支 `feat/agent-08b-sing-handler`（堆叠在 08a 之上，本记录所在提交）。
- 验证及结果：工作目录 `server`，conda 环境 `agent`（Python 3.10，pytest 9.1.1）。`python -m pytest tests/agent/test_singing.py -q` 为 5 passed；`python -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system tests/stage tests/adapter -q` 为 826 passed、2 skipped（2 skip 为 world 真实网络探测）。相关文件 LSP 诊断无报错。
- 附带更新：`test_facade_contract.py::test_execution_preflight_rejects_whole_plan` 原以「SING 未注册」制造整计划拒绝，改为使用仍未实现的 `WRITE_DIARY` 保持同一语义；`tests/agent_runtime_support.py` 的 capability_manager 增加 singing 替身；`test_compaction_skill.py` 的 `Skills` 构造补 `singing`。
- 未验证范围：未运行真实演唱音频、TTS、GPU、真机或生产数据库；歌曲/片段选择、最近已唱排除与歌词记录仍属 handle 侧（08c）；生产聊天仍走旧 ChatStream。

### 2026-09-14 文本预处理落库（08a）GREEN

- 交付行为：`TextMessage` 经 `ChatPreprocessingHandler` 提取歌曲实体关键词，并借 `plans.context.conversation.append` 落库一条 `source=user` 的正式对话记录，返回 `PreprocessedInput.conversation_entry_ids`；本次不交付计划、不消费 pending。缺少 context 时返回 `FAILED / INTERNAL_ERROR`，不静默跳过落库。图片、语音、typing、选图与触摸仍保持占位行为。
- interface spec：无新增或扩大公开 interface；复用现有 `PreprocessedInput`、`InteractionContext.conversation`（`agent/context`），SPEC 已满足，无 SPEC commit。
- 内部衔接：新增 `agent/skills/cognitive/TextPreprocessingSkill`（包装 `SongEntityLinker`），由 `Skills` 装配并注入 handler；`AgentRuntime` 传入 `agent.preprocessing` 配置。
- Red/Green：Issue #67 明确不要求 SPEC→RED→GREEN 与阶段提交；本切片不制造人工失败测试，记录为单次 Green 候选。
- commit 或 PR：分支 `feat/agent-08a-text-preprocessing`（本记录所在提交）。
- 验证及结果：工作目录 `server`，conda 环境 `agent`（Python 3.10，pytest 9.1.1）。`python -m pytest tests/agent/test_chat_preprocessing.py -q` 为 3 passed；`python -m pytest tests/agent tests/stage -q --tb=short` 为 236 passed；`python -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system tests/stage tests/adapter -q` 为 821 passed、2 skipped（2 skip 为 world 真实网络探测）。相关文件 LSP 诊断无报错。
- 未验证范围：未运行真实 LLM/VLM/TTS、真机或生产数据库；批量回复（08c）与 Sing action handler（08b）尚未实现；生产聊天仍走旧 ChatStream（#66）。
- 附带更新：`test_handling_preparation.py` 的“预处理不落库”占位断言随迁移改为“已落库且两次调用 id 不同”；`test_chat_stage.py` 的假 context 补 `conversation.append`；`test_concurrent_handling.py` 的 handler 子类注入预处理替身。
### 2026-09-14 QQ 凭据维护不变量验证（26）GREEN

- 交付行为：为 `QQMusicCredentialRefreshTask` 补充不变量测试——默认 21600 秒周期且启动立即执行；共享凭据路径按规范化去重只检查一次；无已初始化凭据时 skipped（`credential_count=0`）；多文件按文件数计数；部分失败返回 failure 并记录 `failed_characters`；`ensure_dependencies` 要求 `system_runtime` 与非空学歌任务；任务不持有 `agent_runtime`，保持纯机械。
- interface spec：无新增或改变；纯验证切片。
- Red/Green：Issue #85 为验证工单，无运行时行为变化；不制造人工 Red。
- commit 或 PR：分支 `test/world-26-qq-credential`（基于上游 `refactor/agent` 干净基座，不堆叠）。
- 验证及结果：工作目录 `server`，conda 环境 `agent`。`python -m pytest tests/world/test_world_task_learn_sing_songs.py -q` 为 58 passed；`python -m pytest tests/world -q` 为 120 passed、2 skipped。
- 未验证范围：未运行真实 QQ Music 网络刷新或生产数据库。本条记录与已堆叠 PR 的进度文档插入位置相同，合并时需按序处理。
### 2026-09-14 B 站事件同步不变量验证（27）GREEN

- 交付行为：补充 `BiliEventUpdateTask` / `BiliEventUpdater` 不变量测试——cookie 无效时 `fetch_and_update_events` 明确抛错、任务转为 failure 且不抛出；无新动态返回零计数；解析事件规范化（`event_type` 映射、`source` 默认 `bilibili`、`is_recurring`/`is_personal` 默认 False）；`updated` 只计 `add_event` 实际创建的事件（重复来源不重复计数）；缺少 `event_store` 抛错；任务不持有 `agent_runtime`，保持机械边界。
- 发现（记录，不在本切片修复）：cookie 校验之后 `fetch_and_update_events` 的抓取/解析异常被吞掉并返回零计数，任务据此报告成功。这与「失败不假报成功」不变量存在张力，建议另开缺陷切片处理。
- interface spec：无新增或改变；纯验证切片。
- Red/Green：Issue #86 为验证工单，无运行时行为变化；不制造人工 Red。
- commit 或 PR：分支 `test/world-27-bili-event-update`（基于上游 `refactor/agent` 干净基座，不堆叠）。
- 验证及结果：工作目录 `server`，conda 环境 `agent`。`python -m pytest tests/world/test_world_task_bili_event_update.py -q` 为 12 passed；`python -m pytest tests/world -q` 为 123 passed、2 skipped。
- 未验证范围：未运行真实 B 站网络抓取、VLM/LLM 或生产数据库。本条记录与已堆叠 PR 的进度文档插入位置相同，合并时需按序处理。
### 2026-09-14 过期事件清理不变量验证（28）GREEN

- 交付行为：为 `EventStore.purge_expired_events` 补充不变量测试——`end_datetime < today` 才失活、`end` 当天保留；仅 `start_datetime` 的事件保留一天缓冲；`is_recurring` / `source=user` / 仅 `date_mmdd` 的事件不清除；重复清理只计本次实际失活（幂等）；已 inactive 不计数；清理后失效 due 事件缓存。任务层保持「无 event_store 时 skipped、有 store 时返回 purged」。
- interface spec：无新增或改变；纯验证切片。
- Red/Green：Issue #87 为验证工单，无运行时行为变化；记录为验证切片，不制造人工 Red。
- commit 或 PR：分支 `test/world-28-event-cleanup`（基于上游 `refactor/agent` 干净基座，不堆叠）。
- 验证及结果：工作目录 `server`，conda 环境 `agent`。`python -m pytest tests/world/test_world_task_event_cleanup.py -q` 为 9 passed；`python -m pytest tests/world -q` 为 121 passed、2 skipped。
- 未验证范围：未运行真实外部服务或生产数据库。本条记录与已堆叠 PR 的进度文档插入位置相同，合并时需按序处理。

### 2026-09-06 门面公共入口与请求分流整理

- 交付内容：两个公共方法紧随 `__init__`；handle 入口直接登记请求，已有请求在 `_handle_existing_request` 处理后提前返回，新请求进入 `_process_request`。新处理和计划恢复共用处理权、交付及结算生命周期，原 `_handle_registered` 已删除；保留工作区已有的参数类型注解。
- SPEC 检查：facade、request-ledger、plan-emitter 的现有契约已满足，公开接口与行为不变；纯内部重构不新增 SPEC 或 RED commit，使用既有行为回归验证。
- commit：本记录所在 `codex/agent-facade-flow` 分支的 refactor 提交。
- 验证及结果：server 下运行 `D:/Anaconda/envs/lty/python.exe -X utf8 -m pytest tests/agent tests/agent_runtime -q --tb=short`，重构前 338 passed（65.62s），重构后 338 passed（46.21s）；Ruff 与 diff 检查通过。AST 确认类方法顺序为初始化、handle、realize，realize 及其他未调整方法保持原样；未修改测试。
- 未验证范围：未运行完整 Server、外部服务或生产环境验收。

### 2026-09-06 原输出恢复与可信结算补齐 GREEN

- 交付行为：可信完成或不安全失败行动的safe pending只投递原值，不重跑Handler；安全失败仍先重入Handler。恢复经过全计划准入与执行所有权，错误报告保留原效果及输出事实，失败不转换成业务完成。确认临时存储失败在最终可信结算补齐，本次仍停止新工作；首次payload保存失败保持未知，已有完整payload的尝试标记失败保留安全恢复值。
- interface spec：[输出投递契约](../../项目说明/项目架构与接口（spec）/接口文档/agent/output-delivery.md)、execution-ledger、facade、handler-routing已定稿为实现事实，项目架构及中文docstring同步。
- commit与SPEC：SPEC `a1c44e5e`、RED `1e44947c`均已作者自审；本记录所在 `codex/agent-output-recovery` 提交为GREEN，87项RED未改。`4d60a521`、`aff3bc6d`由独立测试作者修订最终资源清理预算，保留所有在途等待断言；Execution和PlanEmitter实际复现短预算抖动，Request Ledger为同形审计修订。
- 验证及结果：四个输出文件87 passed；server使用 `D:/Anaconda/envs/lty/python.exe -X utf8` 执行相关agent、agent_runtime、domain、world、system回归883 passed、2 skipped。Ruff、compileall、7份Agent SPEC UTF-8/围栏/链接和diff检查通过。包括真实临时SQLite故障、独立Python进程原音频恢复、UNKNOWN封闭、恢复等待者及重复取消清理。
- 未验证范围：两个world真实网络探测跳过；没有真实业务Handler、客户端播放、外部接收器或生产数据库验收；不表示#65业务Say已实现。


### 2026-09-06 确认输出后取消的可信结果 GREEN

- 交付行为：输出确认后协作取消不再覆盖处理器可信ActionResult；已完成项保留完成及效果，整体取消并只允许后续未开始行动继续；可信失败保留实际失败原因。UNKNOWN、未确认输出、持久故障和内容冲突仍阻断后续工作。
- SPEC与commit：既有execution-ledger与handler-routing取消结算契约已满足；PR #119独立审查新增RED `c2897f54`（2项）、`57074619`（1项），均已作者自审。本记录所在提交为最小GREEN，三项RED未改。
- 验证及结果：三个输出文件37 passed；server相关agent、agent_runtime、domain、world、system回归833 passed、2 skipped；Ruff、compileall、diff检查通过。首轮旧关闭用例20ms超时，原样定向复跑及完整复验通过。
- 未验证范围：两个world真实网络探测跳过；没有真实业务Handler、生产库或外部接收器验收。


### 2026-09-06 输出生产者与持久序列 GREEN

- 交付行为：处理器使用四种私有内容草稿，Agent绑定输出身份、从零跨行动连续编号并持久完整payload，串行等待有效回执；安全失败重入复用原槽，内容冲突及未知接收阻止后续输出与行动，已确认输出不重发。版本二序列元数据验证完整性，版本一旧库按真实输出历史保守兼容；输出错误记录不含内容和源码的安全日志。
- interface spec：[输出身份与持久序列](../../项目说明/项目架构与接口（spec）/接口文档/agent/output-delivery.md)，同步execution-ledger、facade、handler-routing及项目架构为实现事实；公开接口与私有输出协议具中文docstring。
- commit与SPEC：SPEC `11ccc9bf` / `d4d9ecc5`，RED `9bb7e059`；候选整理发现吞取消后重发UNKNOWN，追加RED `57d26032`并自审，实际失败于两次sequence=0。本记录所在 `codex/agent-output-delivery` 提交为GREEN。
- 验证及结果：server中使用 `D:/Anaconda/envs/lty/python.exe -X utf8`，相关agent、agent_runtime、domain、world、system测试 **829 passed、2 skipped**，其中34项输出用例。Ruff、compileall、Agent SPEC UTF-8/围栏/相对链接及diff检查通过；旧SQL夹具未修改。
- 未验证范围：两个world真实网络探测跳过；没有真实业务Handler、外部接收器、客户端播放或生产库验收；本地验证不表示完整#65或业务Say已经实现。

### 2026-09-06 PlanEmitter 日志源码隔离 GREEN

- 交付行为：投递失败日志从 traceback 提取文件、行号和函数名，保留角色、request、interaction、plan、ordinal、稳定错误码与异常类型；日志不传递原 traceback，不格式化源码、局部变量或原异常链。处理器捕获投递异常仍留下诊断记录，公开失败报告与消费事实保持正确。
- interface spec：[PlanEmitter](../../项目说明/项目架构与接口（spec）/接口文档/agent/plan-emitter.md) 已按实现定稿；没有新增公开接口或改变投递恢复行为。
- commit：SPEC `c6c4a8cc`、RED `5a4fc167`；GREEN 为 `codex/agent-plan-log-errors` 分支上本记录所在提交，原 RED 断言保持不变。
- 验证及结果：实现前日志用例实跑 1 failed，失败原因是输出含异常源码字面量；实现后 PlanEmitter 聚焦 45 passed。server 下 `D:/Anaconda/envs/lty/python.exe -X utf8 -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system -q --tb=short` 为 **796 passed、2 skipped**。相关 Ruff、compileall、git diff --check 与修改文档的 UTF-8、围栏、相对链接检查通过。
- 未验证范围：使用真实 utils logger、临时 SQLite 和受控协作者；两个 world 网络探测仍跳过。没有运行真实业务 Handler、外部队列、生产数据库或客户端验收。

### 2026-09-06 Execution Ledger 取消等待者事实 GREEN

- 交付行为：拥有者任务取消并完成清理后，给并发等待者发布最新完成前缀、效果与已确认输出，避免使用加入前快照；清理中返回可信结果但结算失败时保留当前效果，以 FAILED / DEPENDENCY_UNAVAILABLE 表达未完成持久化，不冒充 ALREADY_COMPLETED。相关存储错误日志使用稳定依赖错误码。
- SPEC 与 commit：Execution Ledger 既有取消、累计事实和结算失败契约已满足。初步 GREEN `94c295a3` 作者自审复现问题，RED `f0fdf077` 两项均失败；本记录所在提交为修复 GREEN，原 RED 断言未变。
- 验证及结果：40 项执行测试全部通过；完整相关命令 `D:/Anaconda/envs/lty/python.exe -X utf8 -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system -q --tb=short` 为 **795 passed、2 skipped**。相关 Ruff、compileall、diff 检查通过。
- 未验证范围：沿用执行账本切片的真实临时 SQLite 与受控协作者边界，没有新增真实外部能力、生产数据库或客户端验收；两个 world 网络探测仍跳过。

### 2026-09-06 Execution Ledger 逐行动持久恢复 GREEN

- 交付行为：公开 realize 校验完整计划身份并用角色/execution 复合主键仲裁；持久标记行动开始、可信结果及独立累计的未知/已确认输出。重投跳过已完成前缀，仅继续可信无效果且无已确认或未知输出的未完成行动；完成前缀带有输出和效果仍可继续后续安全行动。并发同执行加入同一拥有者，任务取消清理正常返回的可信结果在传播取消前持久结算。
- interface spec：[Execution Ledger](../../项目说明/项目架构与接口（spec）/接口文档/agent/execution-ledger.md)、facade、handler-routing 和架构索引已定稿为实现事实；公开 realize 文档说明持久身份、安全继续和取消语义。内部协议保留 AgentOutputSink，生产路由为空。
- commit：SPEC `25458406`、修订 `15f7b06c`，RED `c7694619`；GREEN 为 codex/agent-execution-ledger 分支上本记录所在提交。38 项新增测试未改动；日志按 RED 要求去除含字面量的源码行，保留异常类型和栈位置。
- 验证及结果：server 下 `D:/Anaconda/envs/lty/python.exe -X utf8 -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system -q --tb=short` 为 **793 passed、2 skipped**。相关 Ruff、Agent compileall、git diff --check、Agent SPEC UTF-8/围栏/本地链接检查通过。真实临时 SQLite 覆盖新 Python 进程完成和硬退出恢复、跨 Runtime 争用、数据库故障与损坏行拒绝。
- 未验证范围：两个 world 真实网络探测跳过；没有真实业务 Handler、外部能力、生产数据库或客户端验收。此记录只说明执行账本与逐行动安全继续，不表示 #65 全部完成或已进行独立 PR 审核。


### 2026-09-06 PlanEmitter 白名单错误分类 GREEN

- 交付行为：在数据库错误包装之前校验完整计划的显式类型白名单，自定义 Action 或嵌套 Tone 子类返回 INTERNAL_ERROR、无外部投递，不误报数据库不可用。接口文档精确区分累计未知接收事实与最后一次明确拒绝。
- commit 与 SPEC：现有 PlanEmitter 契约已满足；初步 GREEN `dce6f839` 自审发现错误分类，RED `dbd19ecd` 两项公开 handle 测试均失败于错误码，修复为本记录所在 GREEN 提交。
- 验证及结果：完整相关 pytest 为 **755 passed、2 skipped**，原42项新RED及两项补充RED全部通过；相关 Ruff、compileall、diff 检查以及四份 Agent 接口文档 UTF-8、围栏和本地链接校验通过。作者自审核对恢复权、取消清理、真实确认与旧测试迁移，没有剩余阻断发现。
- 未验证范围：沿用上一 PlanEmitter 完成记录的本地临时 SQLite 与受控协作者边界；未进行独立 PR 审核或真实外部依赖验收。

### 2026-09-06 PlanEmitter 持久投递与恢复 GREEN

- 交付行为：Handler 提交内部 ActionPlanDraft，由 PlanEmitter 分配稳定身份和连续 ordinal；完整计划落库后交付，记录有效回执、未知结果与明确拒绝。相同请求重投读取终态或原子领取已存计划恢复权，不重跑认知；同实例并发共享结果，恢复取消等待受控 sink 清理后释放恢复权。ack 写入失败时，最终结算能原子补齐真实确认，避免再次投递已知接收的计划。
- interface spec：plan-emitter、request-ledger、facade、handler-routing 已按实现定稿；项目架构记录 planning 与 outbox 的实际归属。内部协议及公开入口具有中文 docstring，两个业务方法和领域字段不变，生产路由仍为空。
- commit：SPEC `2194c0a9`、修订 `d7db3897`；RED `5ec6537a`、修订 `8a0f166e`；GREEN 为本记录所在提交。
- 验证及结果：完整相关 pytest 命令 `D:/Anaconda/envs/lty/python.exe -X utf8 -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system -q --tb=short` 在 server 下为 **753 passed、2 skipped**。42 项新增用例全部通过，原 Handler 测试按 Draft/真实回执身份迁移并保留行为断言。相关 Ruff、compileall、git diff --check 通过；临时 SQLite 覆盖旧库兼容、双实例和新 Python 进程恢复、持久接收器重复识别、存储错误与恢复取消。
- 未验证范围：两个 world 网络探测跳过；未验证真实业务 Handler、外部队列、生产数据库或客户端。持久 Fake 只证明可识别重复的接收器，不表示任意新连接恰好一次。此记录不表示 #64 的 ContextStore 等其他工作完成。

### 2026-09-06 Request Ledger 结算日志时点修复 GREEN

- 交付行为：移除处理器层尚未持久化时的完成日志，统一在公开 handle 确定最终报告后记录一次结算；终态提交失败只记录返回的依赖失败，不先宣称 completed。
- commit 与 SPEC：账本契约已满足；初步 GREEN `e8a6b49a` 自审发现问题，日志 RED `3129691c` 复现 3 条结算日志（其中 1 条提前 completed），GREEN `e14fb703` 修复，未改变领域或装配接口。
- 验证及结果：完整命令 `D:/Anaconda/envs/lty/python.exe -X utf8 -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system -q --tb=short` 为 **711 passed、2 skipped**；相关 Ruff、compileall 与 `git diff --check` 通过。原 44 项 Request Ledger RED 仍未修改。
- 未验证范围：沿用下述 Request Ledger 首片的验证边界，没有新增生产数据库、跨进程首次并发登记或外部服务验收。

### 2026-09-06 handle Request Ledger 持久幂等 GREEN

- 交付行为：AgentRuntime 向角色门面注入现有数据库会话工厂；Request Ledger 用角色/请求复合主键登记处理权，以版本化确定 fingerprint 检查输入，提交完整 JSON 终态后返回。相同请求恢复报告、不同内容拒绝；同实例重复等待原处理，不同实例未结算占用保守拒绝。等待者取消不取消拥有者，拥有者取消保留占用；关闭等待所有已登记调用。存储错误记录稳定身份和隐藏正文的栈信息，结算失败保留已接收计划 ID。
- interface spec：[handle 请求账本](../../项目说明/项目架构与接口（spec）/接口文档/agent/request-ledger.md)、门面和运行时接口均已定稿为当前事实；项目架构补充显式数据库注入与账本归属。公开构造和业务方法具有中文 docstring。
- commit：SPEC `cfa5858e`，RED `8f9e25c4`；GREEN `e8a6b49a`。原 44 项 RED 测试未修改，额外 11 项真实数据库损坏注入属于首次通过的补回归。
- 验证及结果：在 `server` 使用 `D:/Anaconda/envs/lty/python.exe -X utf8 -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system -q --tb=short`，**710 passed、2 skipped**。聚焦原请求用例 44 passed、补充恢复用例 11 passed；相关 Ruff、compileall、`git diff --check` 通过。
- 未验证范围：两个 world 真实网络探测跳过；没有跨进程同时首次登记争抢测试、真实业务处理器、外部能力或生产链验收。已验证临时 SQLite 的双实例争用及独立 Python 进程终态恢复。同步 SQL 调用期间的锁等待受注入引擎配置约束。此交付仅为 Request Ledger；没有实现 PlanEmitter outbox、ContextStore 或 Execution Ledger，不表示 #64 已全部解决。

### 2026-09-06 Agent 已注册路由、交付结算与在途关闭 GREEN

- 交付行为：AgentRuntime 为每角色装配两个独立空路由器；内部注册严格拒绝重复和非法键，门面通过两个业务接口调用已注册处理器。处理器获得单次受限 sink，计划/输出身份与回执校验、已确认事实、部分失败、行动顺序、协作取消及并发交互隔离均已实现。AgentRuntime 停止接受后等待在途处理器及清理，超时保留依赖供重试。
- 关闭修复：门面拥有处理器任务，调用方 Task.cancel 只向处理器转发一次，重复取消继续等待异步或同步清理，避免线程仍使用资源时提前关闭。没有修改共享 asyncio helper。
- interface spec：agent/facade.md、agent/handler-routing.md、agent_runtime/README.md 已按实现定稿；公开接口和路由协议提供中文 docstring。日志保存关联身份、稳定错误码、异常类型及栈位置，省略原异常正文和局部变量。
- commit：SPEC `4c031a4c`，RED `d870214c`，初步 GREEN `d21a2aeb`；重复调用方取消 RED `f5765cee` / GREEN `4f822f6d`；处理器实际开始前取消 RED `38322bd9`，最终 GREEN 为本记录所在提交。
- 验证及结果：原 69 项新增 RED 及原 38 项入口/兼容测试通过；补充的重复取消 RED 在初步 GREEN 上以关闭错误返回成功失败，修复后原断言保持不变并通过。另补 handle/realize 两项调度期间取消测试，先以错误消费/完成行动失败；处理器实际启动前检查令牌后通过。`D:/Anaconda/envs/lty/python.exe -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system -q --tb=short` 为 655 passed、2 skipped。相关产品代码与测试 Ruff、compileall、git diff --check 通过。`server/src` 的 get_agent 搜索仅剩方法定义，三处旧链路保持 get_character_runtime(...).conscious。
- 审核与验证范围：作者自审完成，尚未进行独立 PR 审核；本地测试使用受控内部处理器与接收器。两项真实网络探测跳过，未验证真实模型、capability、客户端、设备或生产服务器。本版生产处理器注册为空。

### 2026-09-06 Agent 空注册门面入口与旧查找迁移 GREEN

- 交付行为：`src.agent.Agent` 提供两个异步业务方法及中文 docstring，校验角色、交互、修订、参数和预取消，空注册返回 UNSUPPORTED；AgentRuntime 初始化组装每角色门面、严格查找并在关闭时停止接受。TopicReplier、SystemRuntime.agent、get_default_agent 三处旧调用改从 get_character_runtime 取得旧意识对象。
- interface spec：agent/facade.md 与 agent_runtime/README.md；SPEC `d5303223`，RED `0601a6d2`，GREEN 为本记录所在提交。
- 验证及结果：原 38 项 RED 测试保持不变，GREEN 38 passed；与 domain/world 合并 582 passed、2 skipped。5 项旧初始化回滚测试通过。门面、AgentRuntime 及新增测试 Ruff、git diff --check 通过，作者自审完成。
- 未验证范围：#63 已注册处理器路由、处理中取消、部分结算和在途关闭尚未实现；未验证真实模型、设备或生产链。额外解除暂缓运行的系统关闭测试因 CapabilityManager 测试替身缺少 _stop_lock 失败，该既有测试问题未修复。不将本轮入口 GREEN 记作 #63 完成。


### 2026-09-06 WorldClock 调度注册基线与关闭重试 GREEN

- 交付行为：通过公开 WorldClock/WorldRuntime 入口冻结九类任务注册、角色展开、配置与启用条件、本地每日时间、立即执行、同名替换、失败隔离和关闭行为；将适用的旧 world 任务测试迁至 `server/tests/world` 并恢复默认执行。WorldClock 重试关闭时只等待已请求取消的任务，不重复取消同步线程的清理等待。
- interface spec：[`world/README.md`](../../项目说明/项目架构与接口（spec）/接口文档/world/README.md)，SPEC commit `ca546227`；没有新增公开接口。
- commit 或 PR：RED `a14018e2`，旧测试整理 `07aa2a50`，GREEN 为 `codex/world-clock-baseline` 分支本记录所在提交。
- 验证及结果：原 RED 稳定复现第二次关闭错误返回成功；保持失败测试不变，`D:/Anaconda/envs/lty/python.exe -m pytest tests/world tests/domain -q` 为 544 passed、2 skipped。world 为 115 passed，domain 为 429 passed。WorldClock 和 world 测试及默认执行配置 Ruff 通过；迁移前后测试函数清单一致，未遗漏或复制测试。其他新增调度测试及恢复的旧测试属于既有行为回归，无伪造 RED。
- 未验证范围：两项真实 VCPedia/B 站探测仍跳过；未验证完整服务器、客户端或生产环境。已有任务业务测试不代表九类任务的完整业务契约已经审核；作者自审不替代独立 code review。

### 2026-09-05 Agent 深模块需求与总体设计基线

- 交付内容：确定 Agent 只保留 `handle_stimulus` 与 `realize_action_plan` 两个业务 interface，明确 Agent、stage、Adapter、world、subconscious、capabilities 和 AgentRuntime 的职责与迁移边界，并发布实现工单 #60—#89。
- 文档：上述 PRD、总体设计背景和根目录 [`CONTEXT.md`](../../../CONTEXT.md)。
- commit 或 PR：`refactor/agent` 历史提交 `8e00241d` 至 `816db81a`。
- 验证及结果：完成设计文档、领域词汇和工单之间的静态核对；该记录不表示产品实现或端到端链路已经完成。
- 未验证范围：真实聊天、玩偶、world、LLM、TTS、GPU、设备和生产环境行为。

### 2026-09-05 迁移期 `TextMessage` 最小公开入口

- 交付内容：`src.domain.agent` 已提供迁移期 `TextMessage`、`StimulusKind.TEXT_MESSAGE` 和 `StimulusSource.USER`，旧 Stimulus 与该入口暂时共用 `PersistPolicy`。
- interface spec：[`domain/README.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/README.md) 中标明的当前实现。
- commit 或 PR：PR #90，当前重放提交 `ede19abb`。
- 验证及结果：合入时的公开构造契约测试为 Green；该结果只证明迁移期入口，不证明本轮目标契约。
- 未验证范围：抽象 `Stimulus`、完整字段校验、稳定错误、移除目标包的 `PersistPolicy` 以及生产调用链迁移。

### 2026-09-05 `Stimulus / TextMessage` 领域契约实现

- 交付内容：实现不可直接构造的抽象 `Stimulus`、不可变 `TextMessage`、四种 `StimulusSource`、固定 `TEXT_MESSAGE` 判别值和稳定构造错误；目标包不再导出 `PersistPolicy`，迁移期旧 Stimulus 继续从旧路径使用自己的持久化协议。
- interface spec：[`domain/stimulus.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/stimulus.md)。
- commit 或 PR：分支 `codex/agent-01-stimulus-text-message-contract`；Red commit `31281005`。
- 验证及结果：Red 阶段聚焦测试为 39 failed、1 passed；最小实现后 `python -m pytest tests/domain/test_stimulus_text_message_contract.py -q` 与 `python -m pytest tests/domain -q` 均为 40 passed。启用临时测试收集策略前，默认 Server 回归为 477 passed、2 skipped、6 failed；失败位于 diary、preferences、proactive topic、runtime shutdown 和依赖真实数据的 Bilibili 测试，均不在本切片修改路径内。按项目负责人决定，之后只执行本切片新增契约测试；重新运行 `python -m pytest tests -q` 为 40 passed、445 skipped，跳过项不构成回归通过证据。
- 未验证范围：生产调用链迁移、真实聊天、玩偶、world、LLM、TTS、GPU、设备和生产环境行为；默认 Server 回归中的 6 个本切片外失败尚未在本切片处理。

### 2026-09-06 当前总 SPEC 的 Stimulus 领域契约实现

- 交付内容：实现当前总 SPEC 登记的全部 `StimulusKind`、15 个不可变可构造 Stimulus、7 个统一拒绝构造的占位类型，以及受控引用、动态消息、触摸频率、world/activity 事实和歌曲知识候选等领域值类型；所有构造入口保持仅限关键字、无任意 `payload`、无 `PersistPolicy`，也不校验字段间的生产场景组合。
- interface spec：[`domain/stimulus.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/stimulus.md)。
- commit 或 PR：分支 `codex/agent-01-stimulus-text-message-contract`；Red commit `f85c9e03`；Green commit `de71ae97`；审核补测与文件拆分为本记录所在收尾提交及其前一提交。
- 验证及结果：Red 阶段聚焦测试为 41 passed、92 failed，失败集中在尚未实现的登记类型、枚举、值对象和校验；Green 后聚焦测试为 133 passed。审核补充的 3 个受控引用名义隔离测试在既有实现上首次即通过，无 Red 证据；职责拆分后聚焦测试为 136 passed。`python -m ruff check src/domain/agent src/domain/stimulus.py tests/domain/test_stimulus_text_message_contract.py tests/domain/test_stimulus_registered_types_contract.py` 与 `python -m compileall -q src/domain/agent` 通过；按项目负责人要求运行 `python -m pytest tests -q` 为 136 passed、445 skipped，跳过项不构成回归通过证据。
- 未验证范围：15 个可构造类型尚未接入生产 Adapter、stage、world 或 Agent handle；受控引用读取 port、`HandleStimulusRequest.interaction.pending_stimuli`、真实数据库/媒体、聊天、通话、玩偶、LLM、TTS、GPU、设备和生产环境均不在本行为切片内。

### 2026-09-06 handle 输入 SPEC 第一版

- 交付内容：完成供评审的 handle 输入文档，定义 `HandleStimulusRequest`、Chat/Toy/World 快照、必要值类型及可变 `CancellationToken`；记录交互身份与修订号的区别、删除的状态字段、两类取消原因及首次取消语义，并同步接口索引、总体设计背景、PRD 说明和领域词汇。
- interface spec：[`domain/handle-input.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/handle-input.md)，状态为第一版、待评审且尚未实现。
- commit 或 PR：分支 `codex/agent-02-handle-input-contract`，本记录所在 SPEC 提交。
- 验证及结果：文档静态核对完成；新增 SPEC 的 UTF-8、代码围栏、九项用户结论相关词项及新增相对链接检查通过；`git diff --check` 通过。文档交付的运行时 Red/Green 不适用。
- 未验证范围：本记录只证明 SPEC 文档交付；没有新增产品代码或测试，没有实现 handle 输入类型、取消处理、Agent/stage 链路，也没有完成他人评审或远程 PR 合并。

### 2026-09-06 handle 输入 SPEC 的上下文归属修订

- 交付内容：删除输入中的 `conversation_ref`、`visible_world_ref` 和通用 `SnapshotRef`；明确 Agent 内部按角色与 interaction 管理历史对话、摘要及 Recall 工作上下文，清理临时上下文不删除长期正本，取消单次 handle 不等于结束 interaction。输入快照直接按值传递，不建立快照持久化或 ID 解析机制；world 内容通过已有强类型 Stimulus 传入。同步总体架构、设计背景、PRD、接口文档、领域词汇和验收场景。
- interface spec：[`domain/handle-input.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/handle-input.md)，修订版待评审、尚未实现。
- commit 或 PR：分支 `codex/agent-02-handle-input-contract`，本记录所在 SPEC 提交。
- 验证及结果：删除字段及导出、保留身份/修订/取消契约、文档 UTF-8、代码围栏、变更相对链接与 `git diff --check` 静态检查通过；运行时 Red/Green 不适用。
- 未验证范围：没有新增产品代码或运行时测试；Agent 工作上下文与清理、world 处理、后台反思证据生命周期均未实现或验证，本记录不代表运行时交付。

### 2026-09-06 删除独立演唱状态输出草案

- 交付内容：从 handle 输入的输出能力枚举、PRD 输出列表和总体设计中删除 `SONG_STATE`，移除 `SongPlaybackState` 草案引用；演唱使用音频及可选文字、表情输出。
- interface spec：[`domain/handle-input.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/handle-input.md)。
- commit 或 PR：分支 `codex/agent-02-handle-input-contract`，本记录所在 SPEC 提交。
- 验证及结果：三个相关契约文档的定义及引用残留检查、`git diff --check` 通过；文档修改的运行时 Red/Green 不适用。
- 未验证范围：未修改产品代码或测试，未验证运行时演唱链路。

### 2026-09-06 handle 输入领域契约 GREEN

- 交付行为：从 `src.domain.agent` 提供三种不可变交互快照、`HandleStimulusRequest`、`CancellationToken` 及已登记枚举和稳定构造错误。实现显式关键字构造、字段/集合/时间校验、pending 去重和 trigger 一致性；取消令牌保留首次原因、重复取消幂等，并通过同一对象向请求观察者发布状态。没有新增上下文快照引用、持久化或已删除的状态类型。
- interface spec：[`domain/handle-input.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/handle-input.md)；本次未扩大公开契约，只更新实现状态。
- commit 或 PR：SPEC 基线截至 `1b9d167a`；RED commit `9389c7ea`；GREEN 为分支 `codex/agent-02-handle-input-contract` 上本记录所在提交。
- 验证及结果：使用 `D:/Anaconda/envs/lty/python.exe`，工作目录 `server`。实现前重新运行 `-m pytest tests/domain/test_handle_input_contract.py -q --tb=no -rN` 为 97 failed、1 passed；实现后该文件为 98 passed，`-m pytest tests/domain -q` 为 234 passed、0 skipped，原有 136 项领域测试均通过。`-m ruff check src/domain/agent tests/domain/test_handle_input_contract.py`、`-m compileall -q src/domain/agent` 和 `git diff --check` 通过。
- 未验证范围：未运行完整 Server/客户端测试、真实设备或外部服务；未实现 Agent handle、plan sink、HandlingReport、stage 重连/结算、迟到模型结果丢弃或 Agent 工作上下文生命周期。本次 GREEN 仅证明输入领域对象及令牌契约，不代表生产链路已迁移或远程 PR 已合并。

### 2026-09-06 handle 接口文档事实化整理

- 交付内容：接口文档仅记录当前公开类型、字段、构造约束、取消状态和错误行为；移除历史删除清单、非目标、未来 Agent/stage 行为要求及尚不可调用的示例。补充可执行的请求构造示例；本轮临时测试证据已移至仓库外归档。
- interface spec：[`domain/handle-input.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/handle-input.md)，同步 domain 索引及 agent/stage 接口页。
- commit 或 PR：分支 `codex/agent-02-handle-input-contract`，本记录所在文档整理提交。
- 验证及结果：接口文档措辞、UTF-8、相对链接、实际构造示例和 `git diff --check` 检查通过；产品代码与测试未改动，文档整理的运行时 Red/Green 不适用。
- 未验证范围：本记录不表示已完成他人代码审查或新增运行时验收。

### 2026-09-06 HandlingReport 类型契约 GREEN

- 交付行为：`src.domain.agent` 提供不可变 `HandlingReport`、`HandlingRequestStatus`、`HandlingErrorCode`、`InvalidHandlingReportError` 和 `HandlingReportErrorCode`。实现全部字段显式关键字构造、身份元组校验、considered 的互斥完整划分及相对顺序、状态与错误码关联、重评时间约束；保留计划身份及显式 retryable 值。请求状态与内容消费结果分别表达。
- interface spec：[`domain/handling-report.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/handling-report.md)，已同步实现状态和可执行构造示例。
- commit 或 PR：SPEC `00ef610b`；RED `812bb249`；GREEN 为分支 `codex/agent-03-handling-report-contract` 上本记录所在提交。
- 验证及结果：使用 `D:/Anaconda/envs/lty/python.exe`，工作目录 `server`。RED 为 94 failed，全部源于公开能力尚未实现；本次保持测试不变，`-m pytest tests/domain/test_handling_report_contract.py -q` 为 94 passed，`-m pytest tests/domain -q` 为 328 passed、0 skipped，包含原有 234 项领域用例。`-m ruff check src/domain/agent tests/domain/test_handling_report_contract.py tests/conftest.py`、`-m compileall -q src/domain/agent` 和 `git diff --check` 通过。
- 未验证范围：未运行完整 Server/客户端测试、真实设备、外部服务或生产环境；本次只验证报告领域对象，未接入 Agent handle、计划 sink、stage 结算或运行时重试链路。

### 2026-09-06 HandlingReport 接口文档事实化整理

- 交付内容：报告接口页聚焦公开名称、字段含义、构造约束、稳定错误和实际测试入口；移除重复验收清单，明确构造器只校验报告内部关系。domain 索引补齐报告导出；相关 domain、agent、stage 接口页移除迁移要求和待补测试清单。
- commit 或 PR：分支 `codex/agent-03-handling-report-contract`，本记录所在文档整理提交。
- 验证及结果：公开字段和枚举与实现核对、构造示例执行、UTF-8、相对链接和 `git diff --check` 检查通过。产品代码与测试未修改；工作区没有未跟踪临时文件，RED/GREEN 证据保存在仓库外。
- 未验证范围：本次为文档整理，没有新增运行时验收或他人审核结果。

### 2026-09-06 Agent 领域公开类型中文说明

- 交付内容：为 `server/src/domain/agent` 的 55 个公开类补齐中文 docstring，为 `StimulusErrorCode` 和 `InteractionSnapshot` 两个类型别名补充源码说明；说明现有字段含义、关键构造约束、取消状态及结算关系，标明七个占位类型的构造失败行为。
- SPEC 检查：现有 `domain/stimulus.md`、`domain/handle-input.md` 和 `domain/handling-report.md` 已满足，本次仅补充源码文档。运行时 RED/GREEN 不适用；未创建 SPEC、RED 或 GREEN commit。
- 验证及结果：使用 `D:/Anaconda/envs/lty/python.exe`，在 `server` 目录运行 `-m pytest tests/domain -q` 为 328 passed；`-m ruff check src/domain/agent`、`-m compileall -q src/domain/agent` 和 `git diff --check` 通过。静态检查确认所有公开类均有自身的中文 docstring，两个别名均有中文源码说明；移除文档字符串后，八个 Python 文件的语法树与 HEAD 一致。作者已核对说明与当前实现和接口契约。
- 未验证范围：未运行完整 Server、客户端或生产链路验收；没有新增他人代码审查结果。

### 2026-09-06 Issue #61 realization SPEC 草案与现行行为核对

- 交付内容：完成 ActionPlan、Action、两个 sink/receipt、ExecutionContext、输出和执行报告的第一版待评审草案；逐项核对总设计中的用途与重复信息，记录思考提示、私密发布归属、音频异常终包、音频分块、表情恢复及活动/日程范围等风险。新增和精简建议均未标为已确认契约。
- interface spec：[`domain/realization.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/realization.md)；依据与风险见 [总 SPEC](../设计文档/Agent-handle-realize-深模块重构.md)。
- commit 或 PR：`codex/agent-04-realization-contract` 分支上的本记录所在 SPEC 草案提交。
- 验证及结果：按 `c523b2a6` 的实际代码核对聊天、触摸、语音、演唱、日记、动态和学歌入口；阅读现有音频终包测试，未运行它们。新增文档 UTF-8、代码围栏、相对链接及 `git diff --check` 静态检查通过。草案阶段 RED/GREEN 不适用。
- 未验证范围：没有产品代码或测试实现，没有接入 Agent、sink 或外部服务；没有验证真实播放、设备、生产环境或完成他人评审。远程工单未修改。

### 2026-09-06 realization SPEC 会话结论落实

- 交付内容：将 realization 文档更新为已确认、尚未实现的目标契约；增加由 stage 直接消费的 StartThinking 独立计划，明确其处理结算与业务执行的区别；以 MessageEndOutput/MESSAGE_END 替代音频结束草案，覆盖纯文字、正常音频、错误和取消终包；说明 ExecutionContext 的创建/使用位置，消除 SinkRejectedError 的措辞歧义，保留成功回执与拒绝异常两条路径。
- 顺序约定：本版保持计划、行动和输出的正常顺序，沿用客户端终止包及播放队列实现表情恢复；严格乱序检测、丢包恢复和跨连接投递去重不作为本版要求。未新增播放完成回执。
- interface spec：[`domain/realization.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/realization.md)；同步 domain 索引、核对记录及 PRD/历史总体设计的权威指向。
- commit 或 PR：`codex/agent-04-realization-contract` 分支上的本记录所在 SPEC 修订提交；没有新增 RED/GREEN commit。
- 验证及结果：本轮文档 UTF-8、代码围栏、新增相对链接、关键契约词项和 `git diff --check` 静态检查通过。文档修订的运行时 RED/GREEN 不适用。
- 未验证范围：未修改产品代码、测试或远程工单；未运行客户端播放、真实依赖或生产环境验收。

### 2026-09-06 realization 领域契约 RED / GREEN

- 交付行为：`src.domain.agent` 新增 42 个公开类型，包含七种 Action、ActionPlan、执行上下文、四种具体输出、两个 sink Protocol/回执、执行报告和值/错误枚举。实现显式关键字构造、不可变值和稳定错误、StartThinking 独立首计划、Say 音频互斥、私密发布归属、消息终止组合及部分执行结果校验。公开类型、方法和属性均有中文 docstring；AgentOutputKind 及快照测试改用 MESSAGE_END。
- interface spec：[`domain/realization.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/realization.md)；同步 handle 输入枚举文档。SPEC commit `17ee66a1` 已满足，本轮未增加接口。
- commit 或 PR：RED `aa0fd0a5`；GREEN 为 `codex/agent-04-realization-contract` 分支上本记录所在提交。
- 验证及结果：使用 `D:/Anaconda/envs/lty/python.exe`，工作目录 server。RED 的 `-m pytest tests/domain -q --tb=no -rN` 为 103 failed、326 passed，其中 101 项为新协议缺失，2 项为已确认的输出枚举更名；没有收集或导入错误。保持 RED 测试不变，GREEN 领域测试为 429 passed；Ruff、compileall 通过。静态检查确认 42 个新增公开类型及其公开方法/属性具有中文 docstring。
- 未验证范围：没有实现实际接收器、Agent 门面/执行器、stage 思考通知消费、消息终包发送、客户端播放或真实持久效果；没有运行完整 Server、客户端、外部服务或生产验收。Protocol 声明与领域值测试不构成这些运行时行为的证明。

### 2026-09-06 单次处理流程与 processing 整理

- 交付行为：门面委托 Handling.run 和 Execution.run；处理器取消与清理共用 invocation.call_handler；计划与输出按本次调用顺序交付。移除业务流程中的 ledger/outbox、历史报告复用、重复调用合并和重发恢复；失败停止，保留已确认结果，retryable=False。Ledger 源码保留并补充中文接口说明与类型提示。
- interface spec：agent/facade.md、plan-emitter.md、output-delivery.md、handler-routing.md 与领域报告说明已同步；总设计和 PRD 撤销对应恢复要求。远端 15 项相关 issue 已补充范围说明，保持开放。
- 验证：Agent/AgentRuntime 142 passed；完整 Server 687 passed、350 skipped、1 个第三方弃用警告。跳过项沿用原配置。保留单次顺序、取消、部分效果和日志测试，移除旧账本恢复测试及无引用 SQL 样例；修复捕获取消后继续发送与输出日志身份缺失。
- 提交组织：按用户要求在 codex/agent-facade-flow 分支分别提交文档、测试和代码；本轮不是 TDD 阶段拆分。
- 未验证范围：真实业务 Handler、外部服务、客户端和生产环境；已有数据库记录未清理。
