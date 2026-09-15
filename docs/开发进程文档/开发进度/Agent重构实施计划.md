# Agent `handle_stimulus / realize_action_plan` 深模块重构实施计划

- 派生自：[总 SPEC](../设计文档/Agent-handle-realize-深模块重构.md)（第 6.1.4、8、9、10 节）与 [交接清单](./Agent重构交接清单.md)
- PRD：[`Agent-handle-realize-深模块重构`](../需求说明（PRD）/Agent-handle-realize-深模块重构.md)
- 工单号：GitHub [#60—#89](https://github.com/SheepLiu712/Agent-LuoTianyi/issues?q=is%3Aissue%20number%3A60..89)（本地编号 `NN` 对应 Issue `#(NN + 59)`，底稿在 `.scratch/agent-handle-realize/issues/`）
- 基线：分支 `refactor/agent`，HEAD `5baa2cf`（2026-09-13 交接文档提交）
- 总体状态：进行中

> 使用约定：规范的唯一来源是总 SPEC；工单状态与协作入口是 GitHub Issue。本文只是把**剩余工作**排成可执行批次和依赖顺序，是工作底稿，不代表已经完成、也不替代 Issue 状态。事实来自对基线源码的静态核对与 GitHub API 查询（2026-09-14），**未重新运行测试**。
>
> 本文件与[开发守则](../开发守则.md)的“进度文档只记录完成事实”约定不同：守则把未来计划归属 Issue。此处只为交接后集中排期临时收录计划；行为切片一旦交付，完成事实仍写入 [`Agent-handle-realize-深模块重构.md`](./Agent-handle-realize-深模块重构.md) 进度文档。

## 1. 当前状态快照

基线分支上的实现事实（按模块核对源码）：

### 1.1 已迁移（可继续使用，不再扩公开 interface）

| 能力 | 位置 | 说明 |
| --- | --- | --- |
| 领域公开协议（01、02） | `server/src/domain/agent/` | Stimulus / 快照 / handle 输入 / HandlingReport / ActionPlan / 输出 / 执行报告 |
| stage 领域类型 | `server/src/domain/stage/` | `lifecycle.py`（结束原因等）、`output.py`（`AgentPresentationChanged`、`CancelDelivery`、StageOutput） |
| Agent 门面与路由（04） | `server/src/agent/facade.py`、`agent/handlers/stimulus/router.py`、`agent/handlers/action/router.py` | 两个业务入口；未知键稳定失败；`START_THINKING` 不由 action handler 实现 |
| handle 核心（05） | `server/src/agent/processing/`、`agent/context/`、`agent/processing/plan_emitter.py` | 单次处理、计划身份/顺序、结算、取消清理 |
| realize 核心 + SAY（06） | `server/src/agent/processing/execution.py`、`agent/handlers/action/say.py` | 有序执行、预制音频与 TTS 两支、失败停止 |
| ChatStage 编排（07 的 stage 侧） | `server/src/stage/chat_stage.py`、`stage_manager.py`、`_models.py`、`_sinks.py`、`_config.py` | 预处理状态、有序批次、期限、取消、串行计划队列、两个 sink、终止；**生产接通仍未做，见 #66** |
| WorldClock 调度基线（03） | `server/src/world/world_runtime.py`、`world/types/` | 九类任务注册、配置调度、错误隔离、同名替换、shutdown（见 `server/tests/world`） |
| 装配 | `server/src/agent_runtime/agent_runtime.py`、`system/system_runtime.py` | `get_agent()` 已返回新门面；StageManager 已构造但生产未按用户连接调用 |

### 1.2 占位（有契约、无真实业务）

- `server/src/agent/handlers/stimulus/chat.py` 三个处理器全部占位：
  - `ChatPreprocessingHandler`：只回填文本 / 图片 / 语音的空理解结果，不落库、不调用 VLM/ASR；
  - `ChatReplyHandler`：消费整批但不做注意力选择、不生成计划；
  - `ChatReflectionHandler`：返回空维护结果，不写记忆/画像/日期、不压缩。
- `InteractionEndingHandler`（`handlers/stimulus/interaction.py`）为契约实现，非业务占位。

### 1.3 尚未实现

| 缺口 | 事实 | 对应工单 |
| --- | --- | --- |
| 生产聊天接通 | `server_main.py:169-174` 仍调 `websocket_service.try_accept_chat_event(...)` → 旧 `ChatStream`；`try_accept_stimulus_event` 与 `StageManager.connect/disconnect` 只被测试使用 | #66（07） |
| 聊天预处理 / 批量回复 | `ChatPreprocessingHandler`、`ChatReplyHandler` 仍占位 | #67/#68（08/09） |
| Sing / 日记 / 动态 / 学歌 action handler | `ActionKind` 已定义（`domain/agent/action_plan.py`），但只注册了 `SAY`；其余 resolve 失败返回 `UNSUPPORTED_ACTION` | #67/#82/#83/#84 |
| 触摸 handler 与独立表情恢复 | 无 action handler；`ActionKind` **没有**表情恢复类型；旧实现只在 `agent/reflex/` | #74（15） |
| Reflection 真实逻辑 | 新链路仅占位；压缩/画像/记忆/日期真实现仍在 `chat_session/chat_pipeline/reflection_worker.py` | #72/#73（13/14） |
| WorldStage | `server/src/stage/` 下无 `world_stage.py`；`domain/agent` 已有 `WorldInteractionSnapshot`、`WorldObservationKind`，但**无世界事实生产者** | #78（19） |
| 世界事实刺激 | `ProactivePromptDue`、`DiaryPlanningDue`、`SongKnowledgeDiscovered`、`SongLearned`、`DynamicObserved` 只有类型定义，无世界侧生产 | #76/#80—#84 |
| world 任务迁移 | `citywalk`、`diary`、`dynamic_interaction`、`learn_sing_songs` 仍 `import ...character_runtime.CharacterRuntime` 直连旧链路 | #80—#84 |

### 1.4 测试与工程现状

- 测试入口：`server/tests/`，按 `adapter / agent / agent_runtime / domain / stage / system / world` 分目录；尚无 `integration/`、`e2e/`。
- **白名单门**：`server/tests/conftest.py` 的 `_ACTIVE_TEST_FILES`（41 个文件）决定收集后哪些不跳过；**新增测试文件必须同步加入该集合**，否则被“现有 Server 测试暂由项目负责人统一处理”静默跳过。
- 标记：只注册 `real_llm`（`--run-real-llm` / `RUN_REAL_LLM_TESTS=1`）；**没有 `slow` 标记**。
- CI：`refactor/agent` 分支**无** `.github/workflows` 生效的测试 CI（历史上 #92/#96 部署过事件驱动 Agent PR 审查，已由 #108 退役为“完整行为切片 + 人工审核”）；测试本地手动运行。
- 运行环境：conda 环境 `lty`（Python 3.10），工作目录 `server`。

## 2. 迁移路线

沿用总 SPEC 9.3 的 expand—migrate—contract：

```text
01—06  expand                      已完成（Issue #60—#65 已关闭）
07     生产接通 + Stage 协调        stage 编排已落地；生产接通未做（#66 开启）
08—28  migrate                     进行中（#67—#87 开启）
29     contract                    未开始（#88）
30     accept                      未开始（#89）
```

当前 frontier：**07/08（生产接通 + 文本回复）** 与 **19（WorldStage 核心）** 是两条主干的起点，可并行。08 引入真实认知链（Recall/注意力/生成），是聊天类 09—17 的前置；19 引入 world 投递，是 20—25 的前置。26—28 的机械边界可与 19 并行。

## 3. 剩余行为切片清单

状态：`占位/未实现`＝未交付；`编排就绪`＝stage 侧完成、业务未接入；`部分`＝有机械实现但边界/回归未收口。依赖用本地编号，Issue 为真实编号。

### 3.1 聊天链路（migrate）

| 编号 | 切片 | Issue | 依赖 | 交付与关键文件 | 验证命令 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 07 | 生产接通与 Stage 协调 | [#66](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/66) | 03,05,06 | `server_main.py` 改用 `try_accept_stimulus_event` + `StageManager.connect/disconnect`；adapter 绑定 | `python -m pytest tests/stage tests/adapter -q` | 编排就绪 |
| 08 | 文本预处理落库、批量回复与 SAY/Sing | [#67](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/67) | 07 | 真实 `ChatReplyHandler`（+ 文本预处理）：检索 → 注意力 → 生成 → emit `Say`/`Sing` → 落库。文件：`agent/handlers/stimulus/chat.py`、新 `agent/skills/cognitive/*` | `python -m pytest tests/stage tests/agent -q` | 占位 |
| 09 | 图片预处理落库，保持混合输入顺序 | [#68](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/68) | 08 | 真实 `ChatPreprocessingHandler`：VLM/ASR 理解 + 按 ID 落库，返回 `PreprocessedInput` | `python -m pytest tests/stage tests/agent -q` | 占位 |
| 10 | 取消、部分消费与晚返回丢弃 | [#69](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/69) | 07,08,09 | 以真实 handler 复验 Stage 结算语义，补集成证据 | `python -m pytest tests/stage/test_concurrent_handling.py -q` | 编排就绪 |
| 11 | 慢 Recall 与多计划 | [#70](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/70) | 05,06,08 | 临时/正式完整计划、ordinal、Recall 续程、取消 | `python -m pytest tests/agent -q` | 未实现 |
| 12 | 明确记忆请求与成功承诺 | [#71](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/71) | 05,08 | `IntentionalMemoryCommit`：先写后承诺，返回实际提交结果 | `python -m pytest tests/agent -q` | 未实现 |
| 13 | Stage 触发的记忆与日期 reflection | [#72](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/72) | 05,06,08,12 | ReflectionCoordinator/Policy/Handler 调度自动记忆与日期检查 | `python -m pytest tests/agent -q` | 占位 |
| 14 | 压缩技能与画像更新接入 reflection | [#73](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/73) | 13 | 阈值/CAS 压缩、画像更新；旧 ReflectionWorker 退出 | `python -m pytest tests/agent -q` | 占位 |
| 15 | 触摸预制反应、独立表情恢复与失败丢弃 | [#74](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/74) | 05,06,07 | `TouchInteraction` handler：预制音频瞬时 SAY + **独立** normal 表情恢复计划；需先补表情恢复 action 类型与 spec | `python -m pytest tests/stage tests/agent tests/domain -q` | 未实现 |
| 16 | 首次登录欢迎到真实 handler | [#75](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/75) | 05,06,07 | 两条有序持久欢迎、预制音频、历史同步时点、登录去重 | `python -m pytest tests/stage tests/agent -q` | 未实现 |
| 17 | 登录与周期提醒 claim/空闲规则 | [#76](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/76) | 03,08,16 | 登录与 300 秒周期提醒的过滤、claim、合并/随机选择与失败释放；**归属 ChatStage**，非 WorldStage | `python -m pytest tests/stage tests/agent tests/world -q` | 未实现 |

### 3.2 World 链路（migrate）

| 编号 | 切片 | Issue | 依赖 | 交付与关键文件 | 验证命令 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 18 | ToyStage（范围待确认） | [#77](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/77) | 05,06 | 设备连接/断开、振动聚合、触摸/动作链；**Issue 带 `question` 标签，范围未定** | 待定 | 未定 |
| 19 | 长期 WorldStage 及世界事实投递 | [#78](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/78) | 03,05,06 | `(character_id, world_id)` 长期 stage：pending/revision、`WorldInteractionSnapshot`、取消、plan sink、执行 worker、受限 world sink。文件：新 `stage/world_stage.py`、`agent/handlers/stimulus/world_activity.py` | `python -m pytest tests/stage tests/world -q` | 未实现 |
| 20 | 每日规划与活动日程（范围待确认） | [#79](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/79) | 18,19 | `DailyPlanningDue`/Activity 生命周期与日程 Action；**Issue 带 `question` 标签** | `python -m pytest tests/stage tests/agent -q` | 未定 |
| 21 | citywalk 角色决策与动态发布 | [#80](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/80) | 19 | 概率/环境/报告/`travel` 留 world；路线/表达/发布经 `WorldObservation → WorldStage → handle`，发布走 `PublishDynamic`+realize。文件：`world/citywalk/task.py` | `python -m pytest tests/world/test_world_task_citywalk.py tests/stage -q` | 部分 |
| 22 | VCPedia 候选知识接纳 | [#81](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/81) | 05,19 | 抓取解析留 world；稳定候选 → `SongKnowledgeDiscovered` → 内部 `SongKnowledgeAcceptance` 幂等写知识/关键词 | `python -m pytest tests/world/test_world_task_vcpedia_new_songs.py tests/agent -q` | 部分 |
| 23 | 学歌派发、完成事实及学会后行为 | [#82](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/82) | 06,19,21,22 | 下载/模型/工件留 world/capability；验证成功 → `SongLearned` → 经验/event/通知/动态；`already learned` 不重复。文件：`world/learn_sing_songs/task.py` | `python -m pytest tests/world/test_world_task_learn_sing_songs.py tests/agent -q` | 部分 |
| 24 | 动态回复和记忆、业务状态结算 | [#83](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/83) | 05,06,19 | world 只产 `DynamicObserved`；回复 → `ReplyDynamic`+realize；记忆内部幂等；receipt 驱动状态 | `python -m pytest tests/world/test_world_task_dynamics.py tests/stage -q` | 部分 |
| 25 | 日记筛选、生成与私密发布 | [#84](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/84) | 05,06,19 | world 筛选与每日去重；每用户 `DiaryPlanningDue` → `WriteDiary`+realize 保 private dynamic | `python -m pytest tests/world/test_world_task_diary.py tests/stage -q` | 部分 |
| 26 | QQ 凭据维护不变量与证据 | [#85](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/85) | 03 | 6 小时、立即执行、路径去重、失败报告；**不产生 Stimulus、不调用 Agent** | `python -m pytest tests/world -q` | 部分 |
| 27 | B 站事实维护不变量与证据 | [#86](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/86) | 03 | Cookie/抓取/解析/EventStore upsert 留 world；不触发角色回复 | `python -m pytest tests/world -q` | 部分 |
| 28 | 过期事件清理不变量与证据 | [#87](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/87) | 03 | 00:00 失活规则、缓存一致性、保留 recurring/用户事件/无年份日期 | `python -m pytest tests/world -q` | 部分 |

### 3.3 收束与验收

| 编号 | 切片 | Issue | 依赖 | 交付 | 验证命令 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 29 | 按真实调用图清理旧业务入口与旁路 | [#88](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/88) | 07—25 | 生产切换 + 删除旧代理/旁路 + 依赖扫描通过 A6/A9 | 全量 `python -m pytest tests -q` + 依赖扫描 | 未实现 |
| 30 | 按行为不变量与架构边界验收 | [#89](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/89) | 26,27,28,29 | 从公开两接口 + 聊天/触摸/登录入口 + 可控 WorldClock 证明 A1—A9 与九类 action；更新文档 | focused → integration → 全量；真实依赖单列人工清单 | 未实现 |

> 18（ToyStage，#77）与 20（每日规划/活动日程，#79）带 `question` 标签，范围待负责人确认后才有验收基线；未确认前不进入实现。

## 3.4 GitHub Issue / PR 对应

> 直达链接：Issue `https://github.com/SheepLiu712/Agent-LuoTianyi/issues/<编号>`；PR `https://github.com/SheepLiu712/Agent-LuoTianyi/pull/<编号>`。下表编号为真实 GitHub 编号。

### 3.4.1 工单状态（2026-09-14 查询）

| 本地 | Issue | 状态 | 标签 | 标题 |
| --- | --- | --- | --- | --- |
| 01 | #60 | CLOSED | — | 固定 handle 侧强类型领域契约 |
| 02 | #61 | CLOSED | — | 固定 realization 侧强类型领域契约 |
| 03 | #62 | CLOSED | — | 冻结 WorldClock 调度与九类注册基线 |
| 04 | #63 | CLOSED | — | 扩展两接口 Agent façade 与内部路由 |
| 05 | #64 | CLOSED | — | handle、PlanEmitter 与 Stage 上下文核心 |
| 06 | #65 | CLOSED | — | 顺序 realization 与 SAY 核心 |
| 07 | #66 | OPEN | ready-for-agent | 接通生产聊天连接与 Stage，统一协调信号及生命周期 |
| 08 | #67 | OPEN | ready-for-agent | 实现文本预处理落库、批量回复与 SAY/Sing 业务 |
| 09 | #68 | OPEN | ready-for-agent | 迁移图片预处理落库，保持混合输入顺序 |
| 10 | #69 | OPEN | ready-for-agent | 验证真实聊天取消、部分消费与晚返回丢弃 |
| 11 | #70 | OPEN | ready-for-agent | 接入慢 Recall 的多计划回复策略 |
| 12 | #71 | OPEN | ready-for-agent | 迁移明确记忆请求及成功承诺边界 |
| 13 | #72 | OPEN | ready-for-agent | 实现经 Stage 触发的记忆与日期 reflection |
| 14 | #73 | OPEN | ready-for-agent | 接入现有压缩技能及画像更新到 reflection |
| 15 | #74 | OPEN | ready-for-agent | 迁移触摸预制反应、独立表情恢复与失败丢弃 |
| 16 | #75 | OPEN | ready-for-agent | 迁移首次登录欢迎到真实 handler |
| 17 | #76 | OPEN | ready-for-agent | 迁移登录与周期提醒，保持 claim 和空闲规则 |
| 18 | #77 | OPEN | question | ToyStage 范围待确认：先核实真实设备行为 |
| 19 | #78 | OPEN | ready-for-agent | 实现长期 WorldStage 及世界事实投递 |
| 20 | #79 | OPEN | question | 每日规划与通用活动日程范围待确认 |
| 21 | #80 | OPEN | ready-for-agent | 迁移 citywalk 的角色决策与动态发布 |
| 22 | #81 | OPEN | ready-for-agent | 迁移 VCPedia 候选知识接纳 |
| 23 | #82 | OPEN | ready-for-agent | 迁移学歌派发、完成事实及学会后的行为 |
| 24 | #83 | OPEN | ready-for-agent | 迁移动态回复和记忆，保留业务状态结算 |
| 25 | #84 | OPEN | ready-for-agent | 迁移日记筛选、生成与私密发布 |
| 26 | #85 | OPEN | ready-for-agent | 核对 QQ 凭据维护不变量并补缺失证据 |
| 27 | #86 | OPEN | ready-for-agent | 核对 B 站事实维护不变量并补缺失证据 |
| 28 | #87 | OPEN | ready-for-agent | 核对过期事件清理不变量并补边界证据 |
| 29 | #88 | OPEN | ready-for-agent | 按真实调用图清理旧业务入口与旁路 |
| 30 | #89 | OPEN | ready-for-agent | 按行为不变量与架构边界完成现有链路验收 |

### 3.4.2 已关闭工单对应的合并 PR

| 本地 | PR | 分支 | 标题 |
| --- | --- | --- | --- |
| 01 | #109 | `codex/agent-01-stimulus-text-message-contract` | 建立 Stimulus 类型 |
| 01 | #110 | `codex/agent-02-handle-input-contract` | 建立 handle 输入契约 |
| 01 | #111 | `codex/agent-03-handling-report-contract` | 建立 HandlingReport 类型契约 |
| 01 | #90 | `impl/agent-dm-01-handle-contract` | 交付 TextMessage 最小契约 |
| 01 | #94 | `impl/agent-dm-01-text-message-green` | 实现 TextMessage 最小契约 |
| 01 | #91 / #105 | `docs/agent-dm-01-*` | 固定 handle 刺激枚举 / Stimulus 构造错误契约 |
| 02 | #112 | `codex/agent-04-realization-contract` | 固定 realization 强类型领域契约 |
| 03 | #113 | `codex/world-clock-baseline` | 冻结 WorldClock 调度与九类注册基线 |
| 04 | #114 | `codex/agent-facade-spec` | 完成两接口门面与处理器路由 |
| 05 | #115 | `codex/agent-request-ledger` | 持久化 handle 请求身份与终态 |
| 05 | #116 | `codex/agent-plan-emitter` | 实现持久 PlanEmitter 与计划投递恢复 |
| 05 | #118 | `codex/agent-plan-log-errors` | 修复计划投递错误日志的源码泄漏 |
| 05 | #121 | `codex/agent-facade-flow` | 收敛单次处理并移除账本恢复流程 |
| 05 | #122 | `codex/agent-context` | 实现交互上下文及共享对话压缩技能 |
| 06 | #117 | `codex/agent-execution-ledger` | 持久执行账本与逐行动安全继续 |
| 06 | #119 | `codex/agent-output-delivery` | 输出生产者身份与持久连续序列 |
| 06 | #120 | `codex/agent-output-recovery` | 恢复原输出并补齐可信接收事实 |

流程类 PR：#95（堆叠 PR 审查规则，已合并到 `refactor/agent`）、#92/#96/#97—#102（事件驱动 Agent PR 审查，主要在 `master`）、#104/#108（默认分支与流程迁移，`dev`）。#108 后 PR 创建/更新不再自动触发 AI 审查。

### 3.4.3 与其它分支的重叠

- #123/#124/#125（`pr1/pr2/pr3/vcpedia-wikitext`，base **`dev`**）正在改造 VCPedia 抓取为 wikitext。它们改的是 **world 抓取/解析**（本计划切片 22 的“world 侧”部分），与 `refactor/agent` 的 Agent 接纳路径不冲突，但两边最终需要在 22 收口时对齐“候选规范化”边界。

## 3.5 各切片细化实现

### 通用约定（所有切片适用）

- **Handler 契约**：`async def handle(request: HandleStimulusRequest, plans: PlanEmitter) -> HandlingReport`。
  输出计划用 `await plans.emit(ActionPlanDraft(source_stimulus_ids=(...), actions=(Say(...), ...)))`，**一次 `emit` 一个计划**；`source_stimulus_ids ⊆ {trigger} ∪ pending`，且不得包含协调类（typing/选图/deadline/ending）。
- **计划编排 API**：`plans.context`（`InteractionContext`，含 `.user`/`.conversation`/`.recalled_memory`）、`plans.accepted_ids`、`plans.set_interruptible(bool)`；`emit` 返回 `PlanReceipt`，首个投递失败后后续 `emit` 会抛错。
- **报告约束**（`agent/processing/handling.py::_validate_handling_report`）：返回前 `report.emitted_plan_ids == tuple(plans.accepted_ids)`；`request_id`/`trigger_stimulus_id`/`basis_interaction_revision` 与请求一致；`considered` 是 pending 的**有序子集**；`consumed ∪ retained = considered` 且互斥；`FAILED` 必须带 `error_code`，否则必须为 `None`；`preprocessed_input.stimulus_id`（若有）等于 trigger。
- **依赖边界**：读画像/对话/召回、写会话与记忆一律经 `plans.context`；能力（VLM/ASR/TTS/唱歌）先包成 `agent/skills/*` 再注入 handler。Handler 不直连数据库、capability、SystemRuntime 或外部 sink。
- **新增 skill**：放到 `agent/skills/{cognitive|mutation|execution|reflection}/`（`cognitive` 尚不存在，按需创建），并在 `agent/skills/facade.py` 的 `Skills._skills` 字典注册（现有：`SpeakingSkill`、`ConversationCompactionSkill`）。没有 `SkillSet` 类型；依赖是构造注入。
- **注册 handler**：在 `agent_runtime/agent_runtime.py` 的 `StimulusRouter((...))` / `ActionRouter((...))` / `reflection_handler=` 登记；**同一 `StimulusKind` 只能注册一个 handler**，重复抛 `ValueError`。
- **新增 Action 类**：`domain/agent/realization_enums.py` 加 `ActionKind` → `action_plan.py` 定义 `Action` 子类（`action_id: str`，`kind: ClassVar[ActionKind]`）→ `domain/agent/__init__.py` 导出 → **必须**加进 `agent/processing/plan_identity.py` 的 `_types` 白名单，否则 `plans.emit` 运行时报 `unsupported plan value`。
- **Action handler 契约**：`async def realize(action, execution_context: ExecutionContext, outputs: OutputEmitter) -> ActionResult`；输出用 `await outputs.emit(TextFinalDraft|AudioChunkDraft|MessageEndDraft|ExpressionDraft)`；返回的 `ActionResult.action_id` 必须匹配且 `status is not NOT_STARTED`。`ExecutionContext` 由 Stage 创建，同一计划内所有 action 共享。
- **START_THINKING**：由 Stage 的 `_PlanSink` 消费（转 `AgentPresentationChanged(THINKING)`，最后一个思考结束时发 `WAITING`），不进 `ActionRouter`；只能作为 ordinal 0 计划的唯一 action。
- Stage 侧的等待/批次/取消/结算已实现（`stage/chat_stage.py`），切片多数是「把真实业务填进占位 handler」，不要重写编排。

### 07 生产接通与 Stage 协调（#66）

- `WebSocketAdapter`（`adapter/websocket/adapter.py`）已提供 `bind(stage, connection)` / `disconnect(stage, connection)` / `receive_event(connection, event) -> bool` / `submit_output(StageOutput) -> Future`；`_input.convert_input(event, user_id, default_character_id)` 把 WS 消息转 `domain` Stimulus。
- `StageManager`（`stage/stage_manager.py`）已提供 `connect(connection, character_id) -> ChatStage` / `disconnect(connection)` / `close()`，`__init__(*, get_agent, adapter, ...)` 注入 `AgentRuntime.get_agent`。
- 改 `server_main.py` 聊天分支：`is_chat_related_event` 时改为 `try_accept_stimulus_event`；连接建立/断开处调 `StageManager.connect/disconnect`。注意保持 ACK/鉴权/限流仍在 `user_interface`，不进入 Agent。
- 切换前先补一条 `adapter`↔`stage` 集成测试（连接、事件转刺激、输出回包、断线重连复用原 Stage），作为行为切片证据。

### 08 文本预处理落库、批量回复与 SAY/Sing（#67）

把 `ChatReplyHandler.handle` 从「消费整批、不产计划」改成真实链路，移植旧链 `IngressHelper → TopicPlanner → TopicReplier`：

1. 取批：`request.interaction.pending_stimuli`（有序）+ `request.prepared_inputs`；批次 ID 列表即 `source_stimulus_ids`。
2. 认知 skill（`skills/cognitive/`）包装旧实现：召回/注意力 = `subconscious/attention.py::AttentionPlanner.plan_topic_turn`（经 `CharacterSubconscious.plan_topic_turn`）；生成 = `MainChat.generate_response` + `agent/prompt_assembly.py::RealizationPromptAssembler.build` + `agent/response_parser.py::StructuredResponseParser.parse`；事实/唱歌可用性检索沿用 `plan_topic_turn` 的并行分支。
3. 结果转领域 action：普通句 → `Say(content=..., sound_content=..., expression=...)`（`content` 与 `sound_content` 分开保留；`sound_content` 走 `agent/text_cleaning.py::build_sound_content` 语义）；唱段 → `Sing(song_id, segment_id, expression)`；`await plans.emit(ActionPlanDraft(...))`。
4. 落库：经 `plans.context.conversation.append(...)` 写入 assistant 回复（对应旧 `ConversationService.persist_agent_replies`）；不要只依赖客户端听到。
5. 报告：`consumed = 实际答复的 id`、`retained = 其余`；抽取/等待阶段 `plans.set_interruptible(True)`，生成与 emit 前回 `False`。
6. 超时批次由 Stage 触发（`chat_stage._on_deadline` 构造 `InteractionDeadline`），`force_complete` 语义由「deadline 批次必须产出回复，除角色明确沉默」承担。
7. 测试：`tests/agent`（handler 级：计划身份、消费/保留划分、交错批次的顺序）、`tests/stage`（deadline 批次、失败不重试）。

### 09 图片预处理落库，保持混合输入顺序（#68）

把 `ChatPreprocessingHandler.handle` 从「只回填文本」改成真实预处理：

1. `ImageMessage` → 图片理解（包 `subconscious/preprocessing.py::ChatPreprocessor` 为新认知/感知 skill）；`VoiceMessage` → ASR；`TextMessage` 保持文本。
2. 同时做旧链的语义预处理（歌曲实体等线索提取）。
3. 落库：经 `plans.context.conversation.append(...)` 得到 `conversation_entry_ids`。
4. 返回 `PreprocessedInput(stimulus_id=..., text=..., conversation_entry_ids=(...))`；**不 emit 计划**（预处理 ≠ 消费）。Stage 依 `report.preprocessed_input` 标记 READY。
5. 慢图片不被后到文本越过由 Stage 的有序批次保证；本切片保证「理解结果与 stimulus_id 对齐、落库与返回一致」。
6. 测试：`tests/stage/test_concurrent_handling.py`（慢图 + 快文本顺序）+ `tests/agent`（混合 pending 的处理）。

### 10 取消、部分消费与晚返回丢弃（#69）

Stage 侧已实现，本切片以真实 handler 复验并补证据：

- `chat_stage._on_reply_finished`：只删除 `report.consumed_pending_stimulus_ids` 关联的输入与召回；未消费项回 READY 并保持接收顺序。
- `chat_stage._cancel_reply_attempts`：新内容以 `SUPERSEDED` 取消在途 handle/计划（撤销未执行计划、阻止晚到计划与输出），等清理完成再开新批次。
- `chat_stage._schedule_revision`：过期或已触发的 deadline 回调不得形成第二次回复。
- 对照旧基线 `TopicPlanner._commit_extraction_result` 的 CAS 丢弃语义，确认不是 `consume_all`。
- 测试：扩 `tests/stage/test_concurrent_handling.py`：按 ID 部分消费、晚报告不结算、取消期间的清理隔离。

### 11 慢 Recall 与多计划（#70）

在 `ChatReplyHandler` 内实现同一次 handle 的多计划：

1. 先 `emit` 一个完整临时计划 `Say("让我想想……")`（不是半成品，可独立实现）。
2. 启动 Agent 内部 deep recall（future/coroutine），`await` 完成；完成后检查 `request.cancellation` 与 `basis_interaction_revision`。
3. 未取消则 `emit` 完整正式计划（携带原 `basis_interaction_revision`）；stage-bound sink 按当前 revision 接受或拒绝。
4. Recall 完成只唤醒当前 coroutine：**不产生 `RecallCompleted` 刺激**、不递归调用公开接口、不进入 stage。
5. 测试：`tests/agent`（多计划 ordinal、迟到结果丢弃、取消）。

### 12 明确记忆请求与成功承诺（#71）

新增 mutation skill `IntentionalMemoryCommit`，包 `subconscious/memory/memory_write.py::MemoryWriter` 的写入路径，幂等并返回实际提交 revision：

- 在认知 skill 里判定「请记住」意图 → 先 `await` 提交成功，再 `emit` 表示「已记住」的 `Say`。
- 提交失败：返回 `FAILED`（带稳定 `error_code`）、保留刺激、`retryable=False`，不得先承诺成功。
- 与 Reflection 区分：由当前刺激直接触发且后续承诺依赖写入结果的，在本次 handle 内完成；自动总结等事后维护才走 13/14。
- 测试：`tests/agent`（先写后承诺、失败保留、幂等）。

### 13 Stage 触发的记忆与日期 reflection（#72）

把 `ChatReflectionHandler`（已作为 `reflection_handler`，`purpose=REFLECT`）从空实现补成真实反思，移植 `ReflectionWorker` 前两步：

- `subconscious/date_processor.py::DateDetector.detect` / `process_detected_date`：置信度 ≥0.9 直接写 Event；<0.5 丢弃；中间生成**确认话题**——该话题作为新刺激由 Stage 再次 `handle`，**不递归调用**。
- 自动记忆写入：`MemoryWriter.process_interaction`（携带 attention 的 memory_hits）。
- 触发时机 Stage 已定：`chat_stage._finish_attempt` 在回复及其计划结算后，用本次 consumed 发起 `HandlePurpose.REFLECT`；失败只记日志，不回滚已发回复。
- 测试：`tests/agent`（REFLECT 路由、日期三档、失败不回滚）。

### 14 压缩技能与画像更新接入 reflection（#73）

同一 reflection handler 的后两步，移植 `ReflectionWorker._compress_context_and_update_profile`：

- `ConversationCompactionSkill.compact`（`agent/skills/conversation/compaction.py`，已存在）按上下文阈值压缩；依据固定快照、校验适用范围，不覆盖期间新增内容（CAS）。
- 画像：`subconscious/memory/user_profile_updater.py`（旧入口 `update_user_profile_by_context`）。
- 经 `plans.context` 类型化接口提交；完成后删除 stage 侧旧 `ReflectionWorker` 生产调用。
- 测试：`tests/agent`（阈值触发、并发新增不覆盖、无压缩时不更新）。

### 15 触摸预制反应、独立表情恢复与失败丢弃（#74）

1. 新建 touch handler，注册到 `StimulusKind.TOUCH_INTERACTION`；**先从 `ChatPreprocessingHandler` 的注册里移除该 kind**（否则重复注册 `ValueError`）。
2. 复用旧 `agent/reflex/touch.py` 的 `TouchFastReplyBuilder`（`should_use_fast_path`、`_pick_audio_file`、`_expression_for`、`_load_voice_to_expression`）与 `CharacterReflex.try_handle`，包成 skill：概率 1.0、从 `touch_voice_dir` 随机选受支持音频、映射表情。
3. `emit` 计划 1：`Say(prepared_audio_ref=...)`，`delivery=EPHEMERAL_REACTION`（瞬时、不写会话、不显示聊天气泡）。
4. `emit` 计划 2（独立）：表情恢复 action。`ActionKind` 目前**没有**恢复类型 → 新增 Action 类 + `ActionKind` + `plan_identity._types` 白名单 + action handler，输出 `ExpressionDraft(ChangeExpression(expression_id="normal"), delivery=EPHEMERAL_REACTION)`；`ExpressionOutput` 适配层已存在（`adapter/websocket/_protocol.py`），无需新输出类型。
5. 执行顺序：Stage 先完成 SAY 的投递与消息结束标志，再执行恢复计划；SAY 不隐含恢复。
6. 失败：快速资源缺失/读取失败/未命中 → `FAILED` + 日志，丢弃本次触摸；**不转普通话题、不调 LLM 兜底、不重试**。
7. 测试：`tests/stage`（瞬时投递、计划和顺序）、`tests/agent`（失败丢弃）、`tests/domain`（新 action 契约）。

### 16 首次登录欢迎到真实 handler（#75）

> **归属（owner 反馈）**：首次登录的**反馈是 Agent 的行为**，Stage 只负责编排 Agent、不实现具体行为。Stage 只做「何时触发」（就绪判定与计时）并投递登录事实；欢迎的内容、条数、顺序、表情与落库都由 Agent handler 决定，Stage 不感知。

- 连接建立、ChatStage 就绪后再触发登录刺激（避免与历史消息拉取混在一起）；Stage 只做就绪判定与计时，不决定问候内容。
- 首登（`elapsed_from_last_login is None`）：**Agent 侧首次登录 handler** `emit` 两条有序 `Say(prepared_audio_ref=..., expression="normal", delivery=CONVERSATION)`，并用 `plans.context.conversation.append(...)` 持久化欢迎语；每条都是 final package。读写都在 Agent 侧完成，Stage 不参与。
- 迁移自 `chat_session/dependency/proactive_topic_maker.py` 的 FIRST_LOGIN 分支；`RETURN_LOGIN`（久别问候）保持关闭，不因迁移复活。
- 测试：`tests/agent`（两条有序、持久化、文案来自 manifest）+ `tests/stage`（触发时点；Stage 侧不含欢迎行为分支）。

### 17 登录与周期提醒 claim/空闲规则（#76）

> **归属（owner 反馈）**：Stage 只做编排——唤醒扫描、候选过滤、claim/释放、构造强类型刺激（`ProactivePromptDue`）后交给 Agent；提醒内容与表达由 Agent handler 决定，Stage 不实现具体行为。

- `world/clock` 每 300 秒只做唤醒扫描（`world/proactive_topic_task.py`），不再直接调 `ProactiveTopicMaker` / `TopicReplier`。
- ChatStage 拥有活跃流与空闲阈值（默认 30 秒）：扫描到期 event，过滤其它角色与 personal 用户、排除已按 `(event_id, user_id, character_id, trigger_key)` 通知的记录；每个候选随机取一，原子 claim 后构造 `ProactivePromptDue` → `handle`。
- claim 后入队失败/取消要释放 claim；成功 claim 保证当天首登路径与周期检查不并发重复提醒。
- 测试：`tests/stage`（空闲过滤、claim/释放、并发去重）+ `tests/world`（扫描只唤醒）。

### 18 ToyStage（#77，范围待确认）

- Issue 带 `question`：先核实真实设备行为与输出能力（连接/断开、振动聚合、动作），再决定是否本轮交付。
- 若纳入：新增 device/touch 行为族 handler + `ToyStage`，Adapter 负责去抖与聚合，原始采样不进 Handler；表里不预写实现细节。

### 19 长期 WorldStage 及世界事实投递（#78）

新建 `stage/world_stage.py`，作用域 `(character_id, world_id)`：

- 维护 `interaction_id`/`interaction_revision`、pending、`WorldInteractionSnapshot`、handle 取消、plan sink、串行 execution worker、受限 world output sink（无即时通道时明确拒绝或 `NoChannelOutputSink`）。
- world 侧经窄投递 seam 提交强类型事实；新增 `agent/handlers/stimulus/world_activity.py` 处理 `WorldObservation` 等（歌曲等专门事实归其行为族）。Handler 只看到 domain snapshot/引用，不取得 EventStore/WorldRuntime/world task。
- `SystemRuntime` 显式装配 WorldStage registry 与 `get_agent`（不经 service locator）；`world_runtime`/`world_clock` 只负责事实与唤醒，不 import façade 或 Agent 内部；权威 world/activity/schedule revision 留在 owner，Action 提交点由 owner Adapter 校验。
- memory/context 只存带来源/版本/TTL 的受控证据，不成为 world 镜像。
- 测试：`tests/stage`（scope 复用/隔离、事实顺序、旧 revision、无输出支持、关闭）+ `tests/world`。
- 2026-09-15 review 收口：新事实不自动废弃未取消的旧 handle plan；pending 与 handle 同受 `max_stimuli` 限制，ingress/AgentRuntime 共享 handler 登记 kind；非重试 `FAILED` trigger 终态移出 pending；world revision 与同 activity revision 禁止倒退，不同 activity ID 视为切换；execution 非完成记录 plan/error 并经窄 callback 交付 receipt，不重试。

### 20 每日规划与活动日程（#79，范围待确认）

- Issue 带 `question`：每日规划与通用活动的范围未定，先确认再开工。
- 若纳入：处理 `DailyPlanningDue` 与 Activity 生命周期；`CreateSchedule`/`CancelSchedule` 经 realization 写入持久 scheduler，活动迁移/动作走 Motion 类 action；需新增 `handlers/action/scheduling.py`、`motion.py` 与对应 spec；scheduler 到期产生 `ActivityDue` 再经 WorldStage。

### 21 citywalk 角色决策与动态发布（#80）

改造 `world/citywalk/task.py`：

- 留在 world：概率抽样（`daily_run_probability`）、地图/环境推进、报告、写 `travel` event、动态正文/ID 回写；动态发布失败不抹掉已完成散步。
- 改为投递：需要角色选择路线、表达或发布的部分 → `WorldObservation`；经 WorldStage → handle → 发布用 `PublishDynamic` Action + realize。
- 删除 `from src.agent_runtime.character_runtime import CharacterRuntime`。
- 测试：`tests/world/test_world_task_citywalk.py`（概率、event、失败不抹除）+ `tests/stage`（WorldObservation 链路）。

### 22 VCPedia 候选知识接纳（#81）

改造 `world/get_new_songs/task.py`：

- 留 world：抓取、反爬、页面解析、规范化、去重、成功率统计（注意与 `dev` 上 #123—#125 的 wikitext 改造对齐）。
- 投递：每个稳定候选 → `SongKnowledgeDiscovered` → WorldStage → handle 决定是否接纳；接纳由内部 `SongKnowledgeAcceptance` skill 幂等写知识与关键词索引。
- 发现歌曲**不自动**加入学歌任务。
- 测试：`tests/world/test_world_task_vcpedia_new_songs.py` + `tests/agent`（幂等接纳）。

### 23 学歌派发、完成事实及学会后行为（#82）

改造 `world/learn_sing_songs/task.py`：

- 留 world/capability：凭据检查、下载、清理、模型处理、工件校验、库刷新、情绪标签生成、wishlist 状态。
- 投递：验证成功才 → `SongLearned` → WorldStage → handle 记录学会经验（`LearnedSongExperienceCommit`），并可发 `PublishDynamic`；`already learned` 不重复通知/发布。
- `RequestSongLearning` 作为 Action，经 realize 派发到可恢复的持久学歌任务（新增 `handlers/action/song_learning.py`），不在一次 realize 内同步等完整学习。
- 测试：`tests/world/test_world_task_learn_sing_songs.py` + `tests/agent`（经验幂等、不重复）。

### 24 动态回复和记忆、业务状态结算（#83）

改造 `world/dynamic_interaction/task.py`：

- world 只选取/规范化待处理正文与评论为 `DynamicObserved` 投 WorldStage。
- handle 决定 reply/ignore → `ReplyDynamic` Action + realize；记忆由内部 skill 幂等提交（与回复 LLM 可用性解耦）。
- 执行 receipt 回写 replied/ignored/failed 与 memory 状态；不再直连 `CharacterRuntime`。
- 测试：`tests/world/test_world_task_dynamics.py` + `tests/stage`。

### 25 日记筛选、生成与私密发布（#84）

改造 `world/diary/task.py`：

- 留 world：当日每用户对话统计、≥50 条且当天未发才入选、超 20 人随机取 20、每日去重。
- 投递：为每个入选用户产生 `DiaryPlanningDue` → WorldStage → handle 决定内容 → `WriteDiary` Action + realize，保持 private dynamic、source identity 与用户隔离。
- 测试：`tests/world/test_world_task_diary.py` + `tests/stage`（private、去重）。

### 26 / 27 / 28 机械边界收口（#85 / #86 / #87）

三者都不进 WorldStage、不产生 Stimulus、不调用 Agent，补边界回归：

- 26 `qq_music_credential_refresh`：6 小时、启动立即执行、凭据路径去重、部分失败返回 failure + 角色列表。
- 27 `bili_event_update`：Cookie 刷新、抓取、图片/文本解析、EventStore upsert 与计数；无新动态为 0；cookie 无效明确失败。
- 28 `purge_expired_events`：有 end 时 `end_date < today`、只有 start 保留一天缓冲；保留 recurring、`source=user`、只有 `date_mmdd` 的事件；提交后失效 due-event cache。
- 测试：`tests/world` 对应任务测试。

### 29 按真实调用图清理旧业务入口与旁路（#88）

1. 生产切换：`server_main.py:169-174` 由 `try_accept_chat_event` 改为 `try_accept_stimulus_event`，并在连接建立/断开处调用 `StageManager.connect(connection, character_id)` / `disconnect(connection)`（含 07 的未完成部分）。
2. 删除旧入口：`try_accept_chat_event`、`ChatStream`、`IngressHelper`、`TopicPlanner`、`TopicReplier`、`ReflectionWorker`、`agent/reflex`。
3. 删除 `AgentRuntime` 的 `preprocess_chat_event/extract_topic/plan_topic_turn/realize_topic_plan/write_topic_memories/detect_dates_for_topic/update_user_profile_by_context/try_handle_reflex` 与 `get_character_runtime` 生产业务使用。
4. 清理 world 直连（21—25）与外部对 `agent.main_chat` 内部响应类型的依赖；`UnreadMessage`/`ExtractedTopic`/`AttentionPlan`/`OneSentenceChat`/`SongSegmentChat` 不再是外部依赖。
5. 依赖扫描证明 A6/A9：外部→`domain`/façade 单向；无 Handler→capability/DB/runtime；无 Skill→Handler/stage/report 反依赖；无空包/薄转发冒充迁移。
6. 验证：删除后所有已迁移流程测试仍绿 + 全量 `python -m pytest tests -q`；记录收集数/通过/跳过/失败。

### 30 按行为不变量与架构边界验收（#89）

- 从公开两接口、聊天/触摸/登录入口、WorldStage 与可控 WorldClock 补齐集成/少量 e2e 证据，逐项覆盖 A1—A9 与 SPEC 8.3—8.6。
- 逐项触发九类 clock action，区分纯机械（26/27/28）与认知链（21—25），核对外部效果、去重与失败隔离；`ensure_holidays()` 不误计。
- request/execution/reflection 重投不得产生重复回复、记忆、动态、日记、日程、事件或学歌任务。
- 真实网络/LLM/TTS/唱歌/GPU/设备单列人工验收，不用 Fake 宣称通过；更新架构、interface、SPEC 状态与进度。

## 4. 推荐执行批次与并行边界

```text
批次 A（主干起点，可并行）
  ├─ 07 生产接通 ──► 08 文本回复 ──► 09 多模态 ──► 10 结算复验 ──► 11 慢 Recall ──► 12 显式记忆
  │                                                          └─► 13 反思 ──► 14 压缩/画像
  └─ 19 WorldStage 核心 ──► 20 活动/日程（#79 待确认）
                          ├─► 21 citywalk ──► 23 学歌（并 22）
                          ├─► 22 VCPedia 候选知识
                          ├─► 24 动态互动
                          └─► 25 日记
批次 B（与 A 并行）
  ├─ 15 触摸 ──► 16 首次登录 ──► 17 主动提醒（17 依赖 08、16）
  └─ 26 / 27 / 28 机械边界收口（只依赖 03）

批次 C（全部迁移完成后串行）
  29 contract ──► 30 accept
```

规则：

- 每张工单独立一个行为切片分支 + 一个聚焦 PR，base 为 `refactor/agent`；需要先立 Red seam 时按[堆叠 PR 审查规则](./堆叠PR审查规则.md)使用父子堆叠。
- 不得在迁移工单里顺便实现 blocker，也不得提前删除仍有调用者的旧入口（删除只在 29）。
- 进入 29 前，07—25 必须全部合入 `refactor/agent`。
- 18（#77）与 20（#79）需先解除 `question` 标签、明确范围后再排期。

## 5. 生产切换与删除清单（29 的执行前提）

按序完成，否则不能宣称架构收束：

1. 聊天入口：`server_main.py` 改调 `websocket_service.try_accept_stimulus_event`，并在连接建立/断开时调用 `StageManager.connect/disconnect`（07）。
2. 删除旧入口：`try_accept_chat_event`、`ChatStream`、`IngressHelper`、`TopicPlanner`、`TopicReplier`、`ReflectionWorker`、`agent/reflex`。
3. 删除业务代理：`AgentRuntime.preprocess_chat_event/extract_topic/plan_topic_turn/realize_topic_plan/write_topic_memories/detect_dates_for_topic/update_user_profile_by_context/try_handle_reflex`；`get_character_runtime` 的生产业务使用。
4. 清理 world 直连：`world/citywalk`、`diary`、`dynamic_interaction`、`learn_sing_songs` 的 `CharacterRuntime` 导入与调用。
5. 内部类型外泄清理：`UnreadMessage`、`ExtractedTopic`、`AttentionPlan`、`OneSentenceChat`、`SongSegmentChat` 不再被外部依赖。
6. 依赖扫描证明 A1—A9（外部→`domain`/façade 单向；无 Handler→capability/DB/runtime；无 Skill→Handler/stage/report 反依赖）。

## 6. 验收与证据

- 硬门槛：总 SPEC 8.1 的 A1—A9 全部满足，任一未满足即只是中间状态。
- 功能链：8.3 聊天（含 typing/选图/deadline/旧 revision/部分消费）、8.4 触摸、8.5 登录、8.6 九类 clock action（逐项核对机械 vs 认知边界）。
- 证据形态（8.7）：依赖扫描、从两接口观察零/单/多计划与取消、从聊天入口观察全部信号、从触摸/登录入口观察音频与去重、可控时钟触发九类 action；真实网络/LLM/TTS/唱歌/GPU/设备单独人工验收并明确列出。
- 不得以占位返回值、类型测试或跳过项冒充已迁移；跳过项不能写成“通过”。

## 7. 工程注意事项

1. **测试白名单**：新增测试文件必须加入 `server/tests/conftest.py` 的 `_ACTIVE_TEST_FILES`，否则被静默跳过。
2. **无测试 CI**：本分支测试本地手动运行；命令约定在 `server` 目录、conda 环境 `lty`：
   - 单模块：`python -m pytest tests/stage -q`
   - Agent/运行时：`python -m pytest tests/agent tests/agent_runtime -q --tb=short`
   - 领域契约：`python -m pytest tests/domain -q`
   - 白名单回归集：`python -m pytest tests/agent tests/agent_runtime tests/domain tests/world tests/system tests/stage tests/adapter -q`
3. **标记**：只有 `real_llm`；用 `--run-real-llm` / `RUN_REAL_LLM_TESTS=1` 开启。不要引入未注册的 `slow` 标记。
4. **PR 规模**：普通手写代码建议 ≤500 行；超过必须说明拆分理由。
5. **文档同步**：interface 变化同步 `docs/项目说明/项目架构与接口（spec）/接口文档/`；架构边界变化同步 `项目架构.md`；行为切片完成后把**完成事实**追加到 [`Agent-handle-realize-深模块重构.md`](./Agent-handle-realize-深模块重构.md)，而不是写回本计划。
6. **不扩大范围**：Call/Realtime、`UserJoinedActivity`、`ActivityInterrupted` 不在本轮；不得顺手新增 Stimulus/Action/public interface。
7. **GitHub 协作**：工单在 #60—#89；PR base 为 `refactor/agent`；Red→Green 可用父子堆叠（#95 规则）；PR 创建/更新不再自动触发 AI 审查，最终由人工审核。
