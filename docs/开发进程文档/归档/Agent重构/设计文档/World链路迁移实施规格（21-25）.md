# World 链路迁移实施规格（21–25）

- 状态：**实施规格，21–25 的实现依据**。提案见同目录各《…规格（提案）.md》；本文档在实现前把提案的「未决问题」定稿为可执行决定，并冻结接口。
- **裁决记录（2026-09-15）**：三个停点已由 owner 裁决——**N1 = 选项 A**（新增 world 侧结算端口，不再改动 #152）、**N2 = 选项 (a)**（给 `DiaryPlanningDue` 增加目标用户字段）、**N3 = 推荐口径**（world 报候选/抓取失败，接纳结果走结算）。
- 关联工单：[#80](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/80)（21 citywalk）、[#81](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/81)（22 VCPedia）、[#82](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/82)（23 学歌）、[#83](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/83)（24 动态互动）、[#84](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/84)（25 日记）
- 共同依赖：[#78](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/78)（19 WorldStage），已由 PR [#152](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/152) 实现。
- 范围：**21、22、23、24、25**；**不含 20**（Issue #79 带 `question`，本版取「不做」，见 §9）。
- 红线：**不新增/扩大公开领域接口**。`domain/agent` 已备齐全部事实、行动与效果类型；若某切片确需新增，按 §5 停下说明并取得 owner 裁决，不得先实现后补票。

---

## 1. 事实基座（已实现，冻结，不得在本批修改）

### 1.1 `WorldStage` 现有契约（`server/src/stage/world_stage.py`）

| 项 | 事实 |
| --- | --- |
| 取得 | `SystemRuntime.get_world_stage(character_id=None, world_id=None)`，每 `(character_id, world_id)` 唯一长期实例；`world_id` 来自 `config["world"]["world_id"]`（默认 `default`），stage 配置来自 `config["world_stage"]`，agent 来自 `agent_runtime.get_agent(character)` |
| 构造 | `WorldStage.create(character_id, world_id, agent, context_factory, config=None, timezone_name="Asia/Shanghai", on_execution_finished=None)`；上下文 `user_id=None` |
| 事实端口 | `stage.fact_sink` → `await WorldFactSink.submit(fact) -> bool` |
| 受理条件 | 必须同时满足：`state is ONLINE`、`fact.source is StimulusSource.WORLD`、`fact.user_id is None`、`character_id in fact.target_character_ids`、`fact.kind in WORLD_ACTIVITY_STIMULUS_KINDS`、`stimulus_id` 不在 pending、pending/handle 数未超上限、owner revision 不回退。任一不满足即返回 `False`（**拒绝不是异常**） |
| revision | `WorldObservation.world_revision` 单调递增；`ActivityObservation.activity_revision` 按 `activity_id`。旧 revision 直接拒收 |
| 计划执行 | 单串行 worker；`realize_action_plan(plan, context, output_sink)`；**`output_sink` 恒为 `NoChannelOutputSink`（`emit` 一律抛 `SINK_CLOSED`）** ⇒ 世界链路计划**不得包含 SAY/SING**，只能承载持久效果类行动 |
| 计划校验 | `_WorldPlanSink` 校验 `origin_request_id` / `interaction_id` / `target_character_id` / `plan_ordinal` 连续 / plan 不重复 |
| 结算 | handle 返回后校验 report 与 request 一致；按 `consumed_pending_stimulus_ids` 移除 pending，`FAILED && not retryable` 也移除触发项 |
| 执行回执 | `on_execution_finished(plan, report)` 每次计划执行结束后回调（含非 `COMPLETED`） |
| 其它 | `wait_idle()`（测试/关停）、`close()`（幂等） |

### 1.2 可受理的六类事实（`WORLD_ACTIVITY_STIMULUS_KINDS`）

| 类型 | 字段（`domain/agent/stimulus.py`、`stimulus_values.py`） | 使用切片 |
| --- | --- | --- |
| `WorldObservation` | `observation_kind: WorldObservationKind(value)`、`fact: WorldFact(fact_id, summary)`、`evidence_refs: tuple[EvidenceRef(evidence_id), ...]`、`world_revision: int` | 21 |
| `DynamicObserved` | `dynamic_id`、`target_message_id`、`target_kind: DynamicTargetKind`（`post`/`comment`）、`messages: tuple[DynamicMessage(message_id, parent_message_id, author_ref: ActorRef(actor_id, display_name), text, media_refs), ...]`、`revision: int`。约束：首条 `message_id == dynamic_id` 且无父；后续父消息必须已出现；`target_message_id` 唯一存在且与 `target_kind` 一致 | 24 |
| `DiaryPlanningDue` | `local_date: date`、`timezone: ZoneInfo`、`trigger_id: str`、**`owner_user_id: str`（本次新增，N2 已裁决）** | 25 |
| `SongKnowledgeDiscovered` | `source_ref: SourceRef(source_id)`、`external_song_id`、`revision: int`、`candidate: SongKnowledgeCandidate(song_name, uploader, singers, introduction, lyrics, lyric_keywords)`、`fetched_at: aware datetime` | 22 |
| `SongLearned` | `learning_job_id`、`song_id`、`completed_at: aware datetime` | 23 |
| `ActivityObservation` | `activity_id`、`observation: ActivityFact(fact_id, summary)`、`activity_revision` | 本批不用（属 20） |

公共字段由各具体类型显式传入：`stimulus_id`、`schema_version=1`、`occurred_at`（带时区）、`source=StimulusSource.WORLD`、`target_character_ids`、`user_id=None`、`ephemeral`。

### 1.3 行动与效果（**已定义、当前无 handler**）

| 行动（`domain/agent/action_plan.py`） | 关键约束 | 效果类别（`EffectKind`） |
| --- | --- | --- |
| `PublishDynamic(body, media_refs, visibility, owner_user_id, source: DynamicSource(source_type, source_id), allow_comment)` | `PRIVATE` 必须给 `owner_user_id` | `DYNAMIC_POST` |
| `ReplyDynamic(target: DynamicReplyTarget(dynamic_id, parent_comment_id), owner_user_id, body)` | `parent_comment_id=None` 表示回复原帖 | `DYNAMIC_COMMENT` |
| `WriteDiary(owner_user_id, local_date: date, body)` | —— | `DYNAMIC_POST` |
| `RequestSongLearning(song_id, dedup_key)` | `dedup_key` 标识同一业务请求 | `SONG_LEARNING_JOB` |

结算载体：`ActionResult(action_id, status, error_code, irreversible_effect_committed, effect_ref: EffectRef(kind, effect_id) | None)` 与 `ExecutionReport`。

### 1.4 涉及任务的现状（源码事实）

| 任务 | task_name / 时钟（生效配置） | 关键配置 | 当前 `CharacterRuntime` 用法 | 测试（均在 conftest 白名单） |
| --- | --- | --- | --- | --- |
| citywalk | `try_citywalk:{character_id}`；daily 04:00（`world.citywalk.clock_config`） | `daily_run_probability=0.1`、`world.citywalk.{amap,session,search,report,decision,llm_modules}`、`report.output_dir=data/citywalk_reports` | `publish_citywalk_dynamic(report, source_id)`、`profile.display_name`；另用 `agent_runtime.vector_store` 建服务 | `tests/world/test_world_task_citywalk.py` |
| get_new_songs | `sync_new_song_knowledge`；`world.song_knowledge` | `world.song_knowledge.crawler.llm_module` | **无** | `tests/world/test_world_task_vcpedia_new_songs.py` |
| learn_sing_songs | `learn_sing_songs:{character_id}`；daily 04:00（`world.auto_song_learner.clock_config`）+ `qq_music_credential_refresh`（interval 21600，启动即跑） | `songlearner_dir`、`songlearner_resource_dir`、`qq_credential_file`、`qq_credential_refresh_before_seconds=86400` | `publish_learned_song_dynamic(song_name, segment_description, lyrics)` | `tests/world/test_world_task_learn_sing_songs.py` |
| dynamic_interaction | `dynamic_interaction`；interval **600s**（生效配置；代码内默认 1800） | `reply_post_limit=10`、`reply_comment_limit=20`、`memory_post_limit=10`、`memory_comment_limit=20` | `capability_manager.dynamics.replier.ensure_llm()`、`generate_dynamic_reply_for_post(item)`、`generate_dynamic_reply_for_comment(item)`、`publish_dynamic_comment(...)`；记忆走 `agent_runtime.write_topic_memories(...)` | `tests/world/test_world_task_dynamics.py` |
| diary | `diary:{character_id}`；daily 00:00 | `min_daily_conversations=50`、`max_users_per_run=20` | `dynamic_context()`（`character_persona`/`speaking_style`）；发布走 `capability_manager.diary.generate_and_post_diary(...)` | `tests/world/test_world_task_diary.py` |

---

## 2. 全局实施规则

- **R1 world 不反向依赖**：21/23/24/25 删除 `from src.agent_runtime.character_runtime import CharacterRuntime` 及其实例字段；world 只经 `fact_sink` 投递事实，不 import façade／Agent 内部，不持有 stage。
- **R2 认知在 Agent**：是否回复／是否发布／生成什么内容＝handler；共享能力＝skill；装配＝`AgentRuntime`。不强制恢复 `cognitive/execution/mutation` 目录镜像或独立 `factory.py`。
- **R3 效果只经行动**：handler 不直接调用 capability／DB／runtime；一切外部效果经 `ActionPlan` → `realize_action_plan`。
- **R4 世界链路无实时输出**：`NoChannelOutputSink` 决定了世界侧表达只能是动态／日记／评论／学歌请求等持久效果，禁止 SAY/SING。
- **R5 失败语义**：单次失败停止、记录日志、保留真实部分效果；`submit` 返回 `False`（被拒）时记录并以 world 事实为准，**不重试、不降级成直接调用**；失败不冒充成功。
- **R6 去重仍归 world**：来源唯一性、每日唯一、`already learned`、pending 选择均由 world 维护；不引入 Agent Ledger／outbox／重投／进程恢复。
- **R7 切片纪律**：每切片独立工作树 + 独立分支 + 独立 PR，base `refactor/agent`，代码堆叠在 19（#152）之上；PR 正文注明「必须晚于 #152 合并」。
- **R8 工程口径**：新增测试文件必须登记进 `server/tests/conftest.py::_ACTIVE_TEST_FILES`；切片完成把**完成事实**追加到 `docs/开发进程文档/开发进度/Agent-handle-realize-深模块重构.md`；接口事实变化同步 `docs/项目说明/项目架构与接口（spec）/接口文档/`。

---

## 3. 切片实施明细

### 21 citywalk（#80）

- **world 保留**：04:00 调度、`daily_run_probability` 抽样、地图/环境/会话推进与报告生成（`citywalk` service 及其 LLM/VLM 模块）、`travel` 事件（`event_type=TRAVEL`、`source="world_citywalk"`）、报告回写字段 `diary_text`／`dynamic_content`／`dynamic_id`、散步失败不抹除已完成事实。
- **投递**：散步成功且产出报告后
  `WorldObservation(observation_kind=WorldObservationKind(value="citywalk_completed"), fact=WorldFact(fact_id=f"citywalk:{报告路径}", summary=规范化摘要), evidence_refs=(), world_revision=自增)`。
  概率未命中／服务不可用／运行错误／无报告 → **不投递**（保持 skip 语义）。
- **删除**：`CharacterRuntime` 导入与字段；`_character_display_name` 改为读配置（对齐 `DiaryTask` 的 `character_name` 做法）。
- **Agent 侧**：`handlers/stimulus/world_activity.py` 按 `observation_kind.value` 分派，citywalk 分支生成动态正文并 emit
  `PublishDynamic(body, media_refs=(), visibility=GLOBAL, owner_user_id=None, source=DynamicSource(source_type="citywalk", source_id=<报告标识>), allow_comment=True)`。
  来源身份沿用旧语义（旧 `source_id=str(output_path)`），业务去重由动态存储的来源唯一性保证。
- **结算回写**：报告 `dynamic_id`／`dynamic_content` 由 §4 的结算端口按 `EffectRef(DYNAMIC_POST, id)` 与计划内 `PublishDynamic.body` 写回。
- **测试**：`tests/world/test_world_task_citywalk.py`（概率/事件/无报告 skip/失败不抹除，且不再需要 `CharacterRuntime`）+ Agent/stage 侧（`WorldObservation` → `PublishDynamic`，含去重与发布失败不撤销散步事实）。

### 22 VCPedia 候选知识接纳（#81）

- **world 保留**：04:00 调度、模板列表拉取、反爬、页面解析、字段规范化、去重、节流与成功率统计（`world/get_new_songs/daily_new_song_fetcher.py`、`world.song_knowledge`）。
- **投递**：每个**稳定候选**一条事实（逐条，便于幂等与失败隔离）
  `SongKnowledgeDiscovered(source_ref=SourceRef(source_id="vcpedia"), external_song_id=<稳定歌曲标识>, revision=<内容修订>, candidate=SongKnowledgeCandidate(...), fetched_at=<带时区>)`。
  `candidate` 不得携带 URL/HTML/解析器对象（受控引用原则）。
- **Agent 侧**：新增 `handlers/stimulus/song_knowledge.py`（并在 `world_activity` 分派表登记）+ skill `SongKnowledgeAcceptance`：
  名称/safe name 已存在 → **跳过**；缺介绍 → **失败且不提交半份**；知识与关键词索引在**同一幂等边界**内写入，按「外部来源＋歌曲标识＋修订」幂等。
- **不自动学歌**：候选**不等于**学歌请求；如需 `RequestSongLearning` 必须由明确决策产生（本切片不产生）。
- **统计语义（N3 已裁决）**：world 结果报「候选产出数 / 抓取与规范化失败数」（`discovered`／`fetch_failed`），**不再声称** `added`（知识写入已移入 Agent）。接纳成功数由 §4 结算端口在 Agent 侧观测；「成功必须对应实际知识与关键词可查」由接纳技能的同一幂等边界保证。
- **测试**：`tests/world/test_world_task_vcpedia_new_songs.py`（候选产出/节流/失败统计）+ Agent 侧（幂等接纳、已存在跳过、缺介绍失败、关键词可查）。

### 23 学歌派发、完成事实与学会后行为（#82）

- **world 保留**：凭据检查与刷新、wishlist/pending 状态、下载/清理/分段/模型处理、工件校验、库刷新、情绪标签、通知文件、`new_song` 事件、`already learned` 去重与不重复通知。
- **投递**：**仅工件验证通过**的新学会歌曲 → 每首一条
  `SongLearned(learning_job_id=<任务标识>, song_id=<统一歌曲名/ID>, completed_at=带时区)`。
  中间进度、失败与 `already learned` 一律不投递；失败不冒充 `SongLearned`。
- **Agent 侧**：`song_learned` 分支 → 幂等记录学会经验（skill，幂等键＝角色＋歌曲＋`learning_job_id`）+ 可选
  `PublishDynamic(source=DynamicSource(source_type="song_learned", source_id=song_id))`；`already learned` 不重复通知／发布。
- **派发**：新增 `handlers/action/song_learning.py` 处理 `RequestSongLearning(song_id, dedup_key)`，由 skill 包装 singing wishlist／任务入口，`dedup_key` 幂等；**不在一次 realize 内等待完整学习**。
- **依赖**：21（同一 world 链栈，先 21 后 23）。
- **测试**：`tests/world/test_world_task_learn_sing_songs.py`（凭据不可用不启动、`learned`/`already learned`/`abandoned`/`awaiting`）+ Agent 侧（经验幂等、不重复动态、派发去重）。

### 24 动态回复与记忆、业务状态结算（#83）

- **world 保留**：600s 调度、pending 正文/评论选择与批量上限（回复 10/20，记忆 10/20）、业务状态存储（`dynamic_store` 的 reply/memory 状态列）、来源唯一性防重复。
- **投递**：每个待处理目标一条
  `DynamicObserved(dynamic_id, target_message_id, target_kind, messages=<结构化线程>, revision=<该动态单调修订>)`。
  world **不再**判断 Agent 的 LLM 可用性（`replier.ensure_llm()` 检查移入 Agent 侧），也不再生成内容。
- **Agent 侧**：handler 读结构化线程决定 reply/ignore；reply → `ReplyDynamic(target=DynamicReplyTarget(dynamic_id, parent_comment_id=…), owner_user_id=<目标作者 actor_id>, body)`；
  记忆由 skill 幂等提交，**与回复可用性解耦**（回复失败不得使记忆批次失败；旧「评论先 reply/ignore，正文/评论与记忆各自独立 pass」的语义由此保持）。
  ignore → 明确的类型化结算（见 §4）。
- **结算**：`replied`/`ignored`/`failed` 与 memory 状态只反映**实际提交或明确忽略**，不得把「计划被接受」当发布成功。
- **测试**：`tests/world/test_world_task_dynamics.py`（选择/上限/状态存储不再依赖 `CharacterRuntime`）+ Agent/stage 侧（reply→`ReplyDynamic`、ignore 结算、记忆与回复解耦、按目标与用户隔离）。

### 25 日记筛选、生成与私密发布（#84）

- **world 保留**：00:00 调度、当日每用户对话统计、`≥50` 入选、当天已有日记排除、超 20 人随机取 20、每日唯一。
- **投递**：每个入选用户一条 `DiaryPlanningDue(local_date, timezone, trigger_id, owner_user_id)`；**已裁决 N2=(a)**：`DiaryPlanningDue` 增加 `owner_user_id: str`（非空白校验）字段，目标用户由此显式传到 Agent，不再依赖 `Stimulus.user_id`（`_receive` 仍要求其为 `None`）。
- **Agent 侧**：生成正文 → `WriteDiary(owner_user_id, local_date, body)`，由 realize 发布为 private、不可评论的动态；沿用现有 source identity（`source_type="diary"`、`author=character`）与用户隔离，不建独立日记表。
- **结算**：逐用户 created/failed 来自 §4 结算端口，失败不标成 created。
- **测试**：`tests/world/test_world_task_diary.py`（阈值/上限/去重/LLM 不可用跳过）+ Agent/stage 侧（private 发布、用户隔离、当日去重）。

---

## 4. 结算与业务状态回写（N1，**已裁决：选项 A**）

问题：19 只提供了 `on_execution_finished(plan, report)` 这一个回调，且**只有产生计划时才会触发**。本批需要两类结算：

1. **执行结算**（21/23/24/25）：把 `EffectRef`、正文、失败原因写回 world 业务状态与报告；
2. **处理结算**（24）：`ignore` 这类「明确决定、无计划」的结果没有计划可依附，`HandlingReport` 也不含 `ignored` 字段（Issue #83 原文亦指出「不假定当前 HandlingReport 已经包含这些字段」）。

三个选项：

| 选项 | 做法 | 评价 |
| --- | --- | --- |
| **A（推荐）** | 新增一个**世界侧结算端口**：由 `SystemRuntime` 装配时把 `WorldStage` 的结算回调接到 world 侧的 receipt router，router 按 `source_stimulus_ids`／刺激 kind 分派给提交该事实的任务；回调同时承载 handle 结算与执行结算 | 不改 `domain`；#152 保持冻结；需在 `接口文档/stage` 记录新端口；世界侧新增 router 与注册 API |
| B | 修改 #152 的回调签名为更宽的 `on_settled(request, report, plan_ids, execution_reports)` | 接口更内聚，但要重开已评审的 #152 并复跑其验证 |
| C | 不加端口：world 只从共享存储**反向观察**效果（如按来源身份查已发布动态） | 无需新接口，但 `ignored` 无法表达，且「回写」变成轮询，弱化 #83 的明确结算要求 |

**推荐 A**：既保持 #152 冻结（符合堆叠纪律），又能一次覆盖执行结算与 `ignore`。

---

## 5. 接口裁决记录（owner 已裁决，实施时按此执行）

| 编号 | 议题 | 裁决与执行口径 |
| --- | --- | --- |
| **N1** | 世界侧结算端口 | **采纳选项 A**：`SystemRuntime` 装配 `WorldStage` 时挂 world 侧结算回调；world 侧新增 receipt router，按 `source_stimulus_ids`／刺激 kind 分派给提交事实的任务。范围：`stage` 侧新增结算回调（**不改 #152 现有成员语义**）+ world 侧 router + 注册 API；新端口登记进 `接口文档/stage/README.md`。结算需同时覆盖 handle 结果（用于 24 的 `ignored`）与执行结果（`EffectRef`／失败原因／正文） |
| **N2** | 25 的目标用户 | **采纳选项 (a)**：`DiaryPlanningDue` 增加 `owner_user_id: str`（非空白）。不改 19 的 `_receive` 受理规则（世界事实仍 `user_id is None`）。属公开领域类型**扩大**，已获批准；实现时同步 `接口文档/domain/stimulus.md` |
| **N3** | 22 的统计语义 | **采纳推荐口径**：world 报 `discovered`／`fetch_failed`，不声称 `added`；接纳结果由 N1 结算在 Agent 侧观测 |

---

## 6. 实施顺序与 PR 堆叠

```text
22 VCPedia 候选接纳（不依赖 N1/N2，先开工）
N1 世界侧结算端口（21/24/25 的共同前置，独立小 PR，堆叠在 #152 之上）
21 citywalk（叠 N1，回写报告 dynamic_id）
  └─► 23 学歌（叠 21）
24 动态互动（叠 N1，ignore 结算走 N1）
25 日记（叠 N1；含 DiaryPlanningDue 目标用户字段）
```

- 每个切片一个工作树（基线 `impl/agent-19-world-stage` 尖端）、一个分支、一个 PR。
- N1 作为独立小 PR 先行（21/24/25 都堆叠其上）；22 与 N1 可并行；23 堆叠在 21 之后。
- 全部完成后才进入 29 的删除阶段（本批不删旧入口之外的任何东西）。

---

## 7. 测试与证据

- 单切片：`server` 目录、conda 环境 `agent`：
  `conda run -n agent python -m pytest tests/domain tests/agent tests/stage tests/world -q`
- 全白名单回归：`tests/agent tests/agent_runtime tests/domain tests/world tests/system tests/stage tests/adapter -q`
- 世界任务测试文件均已登记白名单；若新增 Agent/stage 测试文件，必须同步登记。
- 证据形态：world 侧事实产出（候选/散步/学会/待处理/入选）与投递被拒的记录；Agent 侧计划与效果（动态 ID、评论、日记、学歌派发）；结算后 world 业务状态；失败隔离（单条失败不影响其它条）；去重（同来源重投不产生第二条效果）。
- 真实网络/LLM/TTS/唱歌/GPU/设备仍属人工验收，不用 Fake 宣称通过。

---

## 8. 文档同步清单（每切片完成时）

- `docs/项目说明/项目架构与接口（spec）/接口文档/stage/README.md`：结算端口（若采纳 A）。
- `docs/项目说明/项目架构与接口（spec）/接口文档/domain/realization.md`：本批落地的行动与效果（`PublishDynamic`/`ReplyDynamic`/`WriteDiary`/`RequestSongLearning` 从「已定义无 handler」变为「已有生产 handler」）。
- `docs/项目说明/项目架构与接口（spec）/接口文档/agent/README.md`：world 事实 handler 的实际行为（21–25 分支）。
- `docs/开发进程文档/开发进度/Agent-handle-realize-深模块重构.md`：完成事实（不写回实施计划）。
- 如涉及公开接口变化 → 先按 §5 停下说明。

---

## 9. 明确不做

- **20 每日规划与通用活动日程**：Issue #79 带 `question`，本版取「不做」；`DailyPlanningDue`/`ActivityDue`/`ActivityStarted`/`ActivityEnded` 保持 `_constructible=False` 占位，本规格不触碰。
- Call/Realtime、`UserJoinedActivity`、`ActivityInterrupted`、Toy 动作。
- Agent Execution Ledger／outbox／重投／跨进程恢复。
- 删除旧入口与业务代理（属 29，须 07–25 全部合入后执行）。
