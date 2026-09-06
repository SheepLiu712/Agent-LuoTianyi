# Agent `handle_stimulus / realize_action_plan` 深模块重构总体设计背景

> 2026-09-06 计划与执行的当前目标契约见 [realization SPEC](../../项目说明/项目架构与接口（spec）/接口文档/domain/realization.md)。本轮明确 StartThinking 由 stage 直接消费、MessageEndOutput 替代音频终止输出，严格乱序/丢包恢复不属于本版交付；下文保留历史设计，不覆盖这些已确认修订。

> 状态：总体设计背景；2026-09-06 已修订为单次处理与失败停止，具体接口以接口 SPEC 为准
>
> 日期：2026-09-06
>
> 来源：[`Agent-handle-realize-深模块重构 PRD`](../需求说明（PRD）/Agent-handle-realize-深模块重构.md)
>
> 当前权威契约：[`Server 模块接口文档`](../../项目说明/项目架构与接口（spec）/接口文档/README.md)。行为切片只更新对应模块的 interface 文档；本文保留架构背景、跨切片边界和历史设计取舍。
>
> 范围：记录 Agent 对外行为方向、Agent 内部 Handler / Skill 分层、内部状态变更和事后反思的总体设计背景；不代表这些 interface 已经实现

> 2026-09-06：#63 门面与装配以 [Agent 门面 SPEC](../../项目说明/项目架构与接口（spec）/接口文档/agent/facade.md) 及 [AgentRuntime SPEC](../../项目说明/项目架构与接口（spec）/接口文档/agent_runtime/README.md) 为准。AgentRuntime 初始化直接装配 Agent，门面实现位于 facade.py；路由增量按 [Handler 路由 SPEC](../../项目说明/项目架构与接口（spec）/接口文档/agent/handler-routing.md) 建立 handlers/stimulus/router.py 与 handlers/action/router.py，生产注册集合为空。

> 当前处理决定：门面、Handling、Execution 和 emitter 不依赖 Request/Execution Ledger 或 outbox；不提供幂等重投、自动重发或进程恢复。失败记录日志并停止后续执行，retryable=False。业务存储、通知及外部长任务的独立生命周期不由本次决定取消。

## 1. Problem Statement

当前聊天、world 和后台任务能够分别调用话题提取、记忆、画像、日期、回复生成、TTS、唱歌、歌曲抓取和发布能力。调用方因此必须知道角色心智的内部步骤，`AgentRuntime` 也逐渐变成业务代理集合。增加一种刺激时，如果继续复制这种编排，每种刺激都会形成一条新的浅调用链，并可能绕过 Agent 形成第二套角色决策逻辑。当前 `world` 还同时承载外部世界、周期任务和 `WorldClock` 装配，尚未明确区分“世界事实从哪里产生”和“人格与世界的持续交互由谁协调”。

当前异步反思也由聊天 stage 持有。回复结束后，stage 侧 worker 直接调用日期识别、记忆写入、上下文压缩和用户画像更新。这些工作属于 Agent 如何沉淀经验和维护认知状态，不是 stage 的交互控制，也不是角色向外实施的 `ActionPlan`。

本设计需要同时解决两类问题：

- 对 Agent 外部，只留下少量稳定 interface，让 ChatStage、ToyStage 和 WorldStage 无需理解记忆、提示词、模型、能力和反思步骤；
- 对 Agent 内部，允许不同刺激使用完全不同的处理链，同时通过 Handler 与 Skill 层复用记忆搜索、注意力、图片阅读、语音理解等能力，并把 Agent 自有状态变更和事后反思留在 Agent 内。

当前版本不设计或实现电话、Realtime、`UserJoinedActivity`、`ActivityInterrupted`。这些未来场景不得反向扩大本版本 interface。

## 2. Solution

Agent 是一个深模块。业务调用者先通过 `AgentRuntime.get_agent(character_id)` 取得角色 Agent，随后只调用：

1. `handle_stimulus`：理解一次逻辑刺激，在运行期间把零到多个完整 `ActionPlan` 交给调用方提供的 `ActionPlanSink`，结束时返回 `HandlingReport`；
2. `realize_action_plan`：按既定语义实现一个 `ActionPlan`，通过通道无关的 `AgentOutputSink` 流式输出，并返回 `ExecutionReport`。

Agent 内部采用 Handler、Skill、上下文存储 三层协作：

- Stimulus Handler 负责某一类刺激的认知链；
- Action Handler 负责某一种强类型 Action 的实现链；
- Reflection Handler 负责已结算交互的异步认知维护；
- Skill 提供可被多个 Handler 复用的语义能力；
- `InteractionContextStore` 保存 interaction 级临时认知状态；
- Handling 和 Execution 管理本次调用的计划、行动与输出结果；
- `PlanEmitter` 隔离 Handler 与外部 plan sink，并集中保证本次计划身份、顺序和失败停止。

`ActionPlan` 只描述角色已经决定、需要由 Agent 实现并向调用方结算的外部行为或外部长任务。Agent 自有的记忆、画像、关系、歌曲知识和学会歌曲经验由内部状态变更 Skill 维护，不往返 stage。自动记忆整理、上下文压缩、用户画像更新和重要日期检查属于 Post-Interaction Reflection，同样不进入 `ActionPlan`。

## 3. User Stories

1. 作为 ChatStage，我希望只交付规范化刺激、交互快照、只执行动作计划，以便不再编排记忆检索、注意力、回复生成和能力执行。
2. 作为 ChatStage，我希望用户正在打字或正在选择图片时，Agent 能暂缓正式处理全部 pending stimuli；等待信号结束后再重新判断，以免抢在用户输入完成前回复。
3. 作为 ToyStage，我希望把去抖后的触摸或振动交给 Agent，以便高频硬件采样不会淹没角色认知。
4. 作为 world，我希望只提供箱庭事实和实现 world 侧效果，再由 WorldStage 协调人格与世界的持续交互，以便 world 不成为第二个角色心智。
5. 作为 Agent 调用者，我希望未知角色、非法刺激和过期计划明确失败，以便不能把数据错误伪装成角色已处理。
6. 作为 Agent 调用者，我希望一次 handle 可以输出多个完整计划，以便慢 Recall 期间可以先给出完整临时回应，再给出完整正式回应。
7. 作为 Agent 调用者，我希望知道一次认知是否结束以及哪些 pending stimuli 应保留，以便正确结算输入。
8. 作为计划执行者，我希望同一请求的计划严格有序，且能力失败、取消和部分成功有结构化报告。
9. 作为输出 Adapter，我希望只接收通道无关输出，以便 WebSocket 和设备协议不会泄漏进 Agent。
10. 作为角色，我希望不同用户和不同 interaction 的私有认知上下文严格隔离，以便共享 Agent 实例不会串用记忆。
11. 作为角色，我希望不同 Handler 能复用记忆搜索、注意力、事实检索和图片阅读，而不是共用一条包含大量开关的统一 pipeline。
12. 作为开发者，我希望新增刺激时只增加强类型对象和内部 Handler，以便 Agent 外部 interface 保持稳定。
13. 作为开发者，我希望模型工具调用只能使用经过注册和校验的内部 Skill，以便模型不能通过任意字符串调用系统对象。
14. 作为用户，我希望明确要求“请记住”时，Agent 先可靠写入自己的记忆再承诺成功，而不是把记忆命令交给 stage。
15. 作为用户，我希望回复发送完成后，系统异步整理记忆和画像，并检查我明确提到的重要日期；这些慢工作不阻塞首字或音频输出。
16. 作为运维者，我希望处理或投递失败时停止后续执行，保留已发生结果，并通过日志定位异常。
17. 作为隐私维护者，我希望内部状态变更和反思只携带完成工作所需的身份、版本与证据引用。
18. 作为日程执行者，我希望跨进程长任务通过持久 Action 或 scheduler 管理，以便它们不会伪装成进程内 Recall 或反思回调。
19. 作为审核者，我希望仅从本 spec 就能判断一项工作属于 handle、realize、reflection、stage、Adapter、capability 还是 world。
20. 作为多角色运行时维护者，我希望共享 capability 总是显式接收角色身份，以便全局能力实例不会保存某个角色或用户的可变状态。

## 4. 模块职责与协作

### 4.1 模块归属

| 模块 | 本设计中的含义与职责 | 明确不负责 |
| --- | --- | --- |
| `domain` | 定义强类型 Stimulus、InteractionSnapshot、ActionPlan、报告和通道无关输出，是跨模块共享的语义语言 | 模型、数据库、网络、调度实现 |
| `agent` | 对外门面；Stimulus/Action/Reflection Handler；内部 Skill 编排；interaction context、请求/执行/反思账本 | 外部协议、连接、stage 队列 |
| `subconscious` | 记忆、画像、关系、注意力、知识和角色认知状态的深实现 | 被 stage/world 直接调用 |
| `capabilities` | 图片理解、ASR、TTS、唱歌、动作、发布等可复用技术能力 | 决定角色是否行动和说什么 |
| `agent_runtime` | Agent 创建、装配、注册、查找、缓存和关闭 | 话题、记忆、画像、日期、TTS 等业务代理 |
| `stage` | 管理一种持续交互的状态机。ChatStage 管用户—人格交互，ToyStage 管设备—人格交互，WorldStage 管箱庭世界—人格交互；共同负责 pending、截止时间、取消、背压、输出路由和刺激结算 | Recall、角色语义、画像、记忆写入、反思和权威 world 状态 |
| Adapter | 校验外部协议并转换为领域对象，或把 AgentOutput 编码为外部协议 | 持续交互状态和角色决策 |
| `world` | Agent 之外的箱庭环境和事件源，处于类似聊天中“用户”的位置；维护权威 world/活动事实，执行机械环境推进、抓取和 world 侧效果，并把稳定事实交给 WorldStage | 调用 Agent、维护 Agent pending、生成角色回复或决定角色是否接纳某项知识 |
| `world_clock` | `world` 内部的通用时间驱动实现；登记每日/间隔任务并在到期时唤醒 world task | 理解“为什么到期”、构造角色语义、维护 WorldStage 状态或直接调用 Agent |
| `system` | 顶层组装、数据库、观测和生命周期 | 具体角色业务 |

### 4.2 外部 seam

```text
ChatStage / ToyStage / WorldStage
    -> AgentRuntime.get_agent(character_id)
    -> Agent.handle_stimulus(request, plan_sink)
    -> Agent.realize_action_plan(plan, execution_context, output_sink)
```

这两个 Agent 方法是业务调用者和未来 interface 测试共同使用的最高 seam。`ActionPlanSink` 和 `AgentOutputSink` 是每次调用显式传入的协作 interface，不是第三、第四个 Agent 业务方法。

### 4.3 内部处理流程

```text
stage -> Agent.handle_stimulus -> Handling.run
  -> StimulusRouter -> StimulusHandler -> PlanEmitter -> ActionPlanSink
  -> 本次 HandlingReport
stage -> Agent.realize_action_plan -> Execution.run
  -> 全部 ActionRouter 预检 -> 逐项 ActionHandler -> OutputEmitter -> AgentOutputSink
  -> 本次 ExecutionReport
```

两个流程和交付器位于 agent/processing，共用 invocation.call_handler 管理任务取消和清理等待。门面管理准入、在途登记及日志。每次调用独立处理，不读取历史报告、不合并重复调用、不恢复进程终止前的工作。投递失败记录日志并停止后续交付；已发生效果保留，retryable=False。

临时认知上下文、长期业务存储和事后反思保持各自职责，不依赖请求或执行恢复账本。

### 4.4 `WorldStage` 与定时事件

`WorldStage` 是人格与箱庭世界之间唯一的持续交互 stage，逻辑上属于 `stage`，不属于 `world` 或 Agent。目标实例作用域为 `(character_id, world_id)`；在单世界部署中可以退化为每个 character 一个长期实例。活动 ID、规划周期和歌曲任务只是该交互中的领域对象，不为每次活动重新创建一套人格交互。

```text
用户/客户端 -> ChatStage  -> Agent
箱庭 world  -> WorldStage -> Agent
```

WorldStage 负责：

- 接收 world 已规范化的 Stimulus，并维护该角色在箱庭交互中的 pending、聚合顺序和 `interaction_revision`；
- 创建 `WorldInteractionSnapshot`，调用 `handle_stimulus`，按 HandlingReport 结算 pending；
- 排队 ActionPlan，调用 `realize_action_plan`，并为无即时通道的 world 行动提供受限 output sink；
- 在新 world 事实使旧判断过期时取消旧 handle；
- 保持同一人格在日常规划、活动、新歌、动态和其他 world 事实之间的连续交互上下文。

WorldStage 不拥有权威 world/活动数据，也不解释抓取结果；权威事实仍由 world 持有。world 不直接调用 Agent，而是把稳定事实投递给 WorldStage。

定时分为两类：

| 定时类别 | 定义和语义所有者 | 时间驱动 | 到期后的路径 |
| --- | --- | --- | --- |
| world 领域定时 | world 定义“每日规划”“活动到期”“抓取新歌”等事实为什么产生 | `world_clock` 只负责到时唤醒 | `WorldClock -> world task -> 强类型 Stimulus -> WorldStage -> Agent` |
| stage 交互定时 | WorldStage 定义何时聚合完 pending 或根据新事实重新判断 | WorldStage 自有 deadline/scheduler；不注册为 world 领域事件 | `WorldStage deadline -> InteractionDeadline -> handle_stimulus` |

Agent 通过 `CreateSchedule` 创建的持久未来安排由 scheduler/world 保存。构造 `future_stimulus` 的外部调用方必须显式选择强类型变体并填写语义 `source`；到期投递者原样保留该值，不因 scheduler 或 `world_clock` 执行了最后一跳而改写。`ProactivePromptDue` 和 `InteractionDeadline` 不能直接作为 `future_stimulus` 保存，必须由拥有目标 interaction、pending/claim 和输出路由的 stage 在收到到期事实后构造。`world_clock` 可以作为底层唤醒器，但不得直接构造角色回复或调用 Agent。

## 5. Agent 暴露给外部的行为

### 5.1 `AgentRuntime`

`AgentRuntime.get_agent(character_id: str) -> Agent` 返回稳定 Agent 门面：

- 相同角色在同一运行时中返回同一个已装配实例；
- 未知角色明确抛出稳定的角色不存在错误，不回退到默认角色；
- 业务调用方通过依赖注入获得 `AgentRuntime`，不新增全局 service locator；
- `AgentRuntime` 的关闭流程负责停止 Agent 接收新工作，并让已接受的内部异步工作完成或可靠保留；
- `get_character_runtime` 和现有业务代理只作为迁移对象，不能被新调用方使用。

### 5.2 handle_stimulus

输入以 [handle 契约](../../项目说明/项目架构与接口（spec）/接口文档/domain/handle-input.md) 为准；输出以 [HandlingReport](../../项目说明/项目架构与接口（spec）/接口文档/domain/handling-report.md) 为准。

门面检查类型、目标角色和接受状态后调用 Handling.run；先检查取消，再按触发刺激选择处理器。处理器交付零到多个完整计划，报告按 ID 保留消费结果及已接收计划。失败停止本次后续交付，不要求 stage 重投。source 由调用方提供，Agent 决定会话和记忆的业务持久化；交互快照不要求保存到数据库。

### 5.3 realize_action_plan

计划、行动、上下文、输出和报告以 [realization 契约](../../项目说明/项目架构与接口（spec）/接口文档/domain/realization.md) 为准。

门面校验角色和交互身份后调用 Execution.run；检查修订、取消及全部路由后顺序执行行动，输出序号在本次执行中跨行动从零连续递增。失败停止后续行动，保留已返回的效果和已完成结果，剩余行动 NOT_STARTED。StartThinking 由 stage 消费，MessageEndOutput 保持正常发送位置，接收确认不表示播放完成。

### 5.4 错误和生命周期

完整顺序和错误映射见 [门面契约](../../项目说明/项目架构与接口（spec）/接口文档/agent/facade.md)。两类报告 retryable=False；标识用于关联本次调用，不表示持久去重保障。ALREADY_ACCEPTED 和 ALREADY_COMPLETED 保留为领域值，不要求 Agent 保存历史或重发。

任务取消等待处理器清理后传播；shutdown 有界等待在途调用，超时保留依赖供后续关闭。进程终止后不恢复未完成调用。

## 6. Agent 内部的行为

### 6.1 内部层级

Agent 内部固定采用“Façade → Handler → Skill / Store”的依赖方向：

```text
Agent façade
  -> 请求校验、单次处理、取消、统一观测
  -> Handler Router
  -> 某个 Handler 选择自己的处理链
  -> 共享 Skill 完成语义能力或 Agent 自有状态变更
  -> PlanEmitter 统一构造并提交计划
  -> façade 构造公开 report 并记录结算事实
```

Façade 负责所有 Handler 都必须遵守的契约。Handler 不重复实现 plan ID、ordinal、sink 校验、公开报告一致性和单次失败停止。Skill 不知道 stage，也不生成外部协议对象。

#### 6.1.1 目标目录与所有权

目标目录按“稳定职责和依赖方向”组织，不按每个 Stimulus/Action 枚举机械拆类。以下是 contract 阶段必须收束到的包边界；迁移阶段只在首次承载真实代码时创建目录或文件，不提交空包骨架：

```text
server/src/
├─ domain/agent/                    # 跨模块公开协议；stage/world/Adapter 可依赖
│  ├─ stimulus.py                   # Stimulus、InteractionSnapshot、HandleRequest
│  ├─ planning.py                   # ActionPlan、ActionPlanSink/Receipt
│  ├─ execution.py                  # Action、ExecutionContext、AgentOutput、OutputSink
│  └─ reports.py                    # HandlingReport、ExecutionReport、稳定错误
├─ agent/
│  ├─ __init__.py                   # 只导出 Agent façade 的公开类型；不重导出内部构造
│  ├─ facade.py                     # 两个业务接口、校验、取消、观测与结算编排
│  ├─ handlers/
│  │  ├─ stimulus/                  # handle 侧行为族
│  │  │  ├─ router.py
│  │  │  ├─ conversation.py         # 文字/图片/非 Realtime 语音正式回合
│  │  │  ├─ coordination.py         # typing、图片选择、deadline 等协调信号
│  │  │  ├─ touch.py                # 触摸快速反应与普通回复回退
│  │  │  ├─ device.py               # Toy 振动、连接/断开等设备事实
│  │  │  ├─ proactive.py            # 登录、提醒、动态、日记等主动输入
│  │  │  ├─ world_activity.py       # world 观察、规划、活动生命周期
│  │  │  └─ song_knowledge.py       # 候选歌曲知识与学会事实
│  │  ├─ action/                    # realize 侧 ActionKind 实现
│  │  │  ├─ router.py
│  │  │  ├─ communication.py        # Say/Sing 及其音频、表情输出
│  │  │  ├─ publishing.py           # 动态、回复、日记
│  │  │  ├─ scheduling.py           # 日程与活动迁移
│  │  │  ├─ motion.py               # 设备/世界动作
│  │  │  └─ song_learning.py        # 持久学歌任务派发
│  │  └─ reflection/                # 只消费 ReflectionJob 的事后处理族
│  │     ├─ memory.py
│  │     ├─ context_compaction.py
│  │     ├─ user_profile.py
│  │     └─ important_dates.py
│  ├─ skills/
│  │  ├─ contracts.py               # 强类型 SkillSet/Skill 输入输出协议
│  │  ├─ cognitive/                 # Recall、Attention、图片/语音理解、内容生成
│  │  ├─ mutation/                  # Agent 自有记忆、知识、经验、状态提交
│  │  ├─ execution/                 # TTS、唱歌、发布、日程、动作等实现能力
│  │  ├─ reflection/                # 压缩、画像、日期、自动记忆维护能力
│  │  └─ adapters/                  # 对 subconscious/capabilities 的私有适配
│  ├─ context/
│  │  ├─ models.py                  # 临时认知上下文和值对象
│  │  ├─ scoped_context.py          # Handler 可见的 interaction-scoped accessor
│  │  ├─ store.py                   # InteractionContextStore 协议
│  │  └─ in_memory_store.py         # 若首版确有该实现；可替换为持久 Adapter
│  ├─ processing/
│  │  ├─ plan_emitter.py                 # PlanEmitter
│  │  ├─ handling.py                # 单次刺激处理
│  │  ├─ execution.py               # 单次计划执行
│  │  ├─ invocation.py              # 取消与清理等待
│  │  ├─ output_emitter.py          # 输出交付
│  │  ├─ output_drafts.py           # 输出草稿
│  │  └─ plan_identity.py           # 计划身份及值校验
│  └─ reflection/
│     ├─ coordinator.py             # settlement notice、可靠 job 调度
│     ├─ policy.py                  # 是否需要反思及步骤选择
│     ├─ jobs.py                    # Agent 内部 job/result 强类型
│     └─ scheduler.py               # shutdown/恢复/重试生命周期
├─ subconscious/                    # 既有角色认知机制；由 Skill adapter 包装
└─ capabilities/                    # 既有技术能力；不作为 Agent 外部业务接口
```

目录表示最终所有权，不要求每个叶文件都保留一个类。若一个行为只有很薄的转发，必须并入同族 Handler/Skill；只有出现独立状态、不变量或替换轴时才继续拆文件。`domain/agent/` 是推荐目标位置；expand 工单可以先在现有 `domain` 文件内增加同等公开协议，待协议稳定后再机械归档，不能为了目录整齐阻塞首个 tracer bullet。

| 包 | 拥有的知识 | 不拥有的知识 |
| --- | --- | --- |
| `domain/agent` | 两个公开调用所需的强类型输入、计划、输出、报告、receipt 和稳定错误 | Handler、Skill、数据库、供应商、提示词、模型会话 |
| `agent/handlers` | 某类刺激或 Action 应走哪条完整流程、何时调用哪些 Skill、如何形成 draft/result | stage 队列、外部 sink 实现、底层供应商协议、跨请求 ID 分配 |
| `agent/skills` | 可复用的角色语义能力及其强类型输入输出；把 subconscious/capability 细节藏在 adapter 后 | 完整刺激编排、pending settlement、公开 plan/report |
| `agent/context` | 当前 interaction 的临时认知工作集、检索证据引用、关注点、未完成意图与内部 context revision | stage pending/deadline/连接、长期用户画像、权威 world 状态、数据库 session |
| `agent/processing` | 单次处理、顺序交付、取消清理和结果报告 | 角色内容决策、反思条件判断 |
| `agent/reflection` | settlement 后的策略、可靠 job、重试与退出；调用 reflection Handler/Skill | 用户可见 ActionPlan/AgentOutput、stage worker |
| `subconscious` / `capabilities` | 既有认知机制与技术实现 | 刺激流程、Agent 公开协议、stage settlement |

#### 6.1.2 依赖原则

允许的主依赖方向为：

```text
Adapter / ChatStage / ToyStage / WorldStage
  -> domain.agent
  -> agent façade

agent façade
  -> handlers + context + processing + reflection coordinator
handlers.stimulus
  -> skills.cognitive / skills.mutation + context + planning
handlers.action
  -> skills.execution + processing output emitter
handlers.reflection
  -> skills.reflection
skills.adapters
  -> subconscious / capabilities / narrow infrastructure ports
SystemRuntime
  -> agent.factory -> concrete adapters
```

必须同时遵守以下限制：

1. `agent/__init__.py` 只导出 façade 对外所需的 `Agent` 类型；AgentRuntime 初始化时直接装配 Agent；不建立独立 factory 模块。外部模块不得从 `agent.handlers`、`agent.skills`、`agent.context`、`agent.processing`、`agent.ledgers` 或 `agent.reflection` 导入任何对象。
2. stage/world/Adapter 只通过 `domain.agent` 构造协议对象并调用两个业务接口；`domain` 不反向依赖 `agent`、`stage`、`world`、`subconscious` 或 `capabilities`。
3. Handler 只能依赖同层内部协议、scoped context、PlanEmitter 和按职责分组的 Skill；不得直接依赖 `CapabilityManager`、数据库、供应商 SDK、SystemRuntime 或外部 sink。
4. Skill 不依赖 Handler、stage、PlanEmitter、ledger 或公开 report；认知、mutation、execution、reflection 四类 Skill 不相互偷渡副作用。确需组合时由上层 Handler 编排，或由一个拥有完整语义的不透明 Skill 在内部组合。
5. `capabilities` 继续表示 TTS、图片理解、唱歌、动态等技术能力；`agent/skills` 表示“角色为什么、以何种语义使用能力”。二者不是一对一目录镜像。Skill adapter 可调用多个 capability/subconscious 对象，一个 capability 也可被多个 Skill adapter 以不同强类型契约复用。
6. 不建立 `execute(skill_name: str, payload: dict)`、全局 Skill registry 或通用 `CALL_CAPABILITY`。`SkillSet` 是构造时注入的强类型聚合；仅把某个旧 manager 包一层同名代理不算完成迁移。
7. `agent/context` 只存 interaction-scoped 临时工作集；长期记忆、用户画像、歌曲知识仍由 subconscious/相应存储拥有，权威 pending 与 revision 仍由 stage 拥有。检索到的长期记忆在 context 中只保存带来源、版本和 TTL 的证据引用或受控快照。
8. 同一包内避免循环 import；共享值对象向 `domain.agent` 或拥有它的内部低层包下沉，不创建无所有权的 `common.py`/`utils.py`。AgentRuntime 负责角色实例装配和生命周期，不承载角色行为决策；系统级对象生命周期仍由 `SystemRuntime.initialize()/shutdown()` 负责。

#### 6.1.3 Handler 与 Skill 的拆分判据

- 新增一种刺激时，先判断它属于现有行为族还是确有新的不变量；只有后者才新增 Handler 文件。Router 做精确注册和未知类型失败，不做内容决策。
- Handler 的测试价值来自“给定强类型上下文产生何种内部决定/计划”，Skill 的测试价值来自“同一语义能力能否在多个流程复用”；只转发一个方法且不隐藏复杂度的层必须合并。
- `TouchInteraction` 由专门的 `TouchInteractionHandler` 负责快速反射与普通回复回退，不再归入包含 typing/deadline 的宽泛协调 Handler；它可复用 attention/response Skill，但 `agent/reflex` 不作为第二棵永久目录保留。
- `ToyVibration`、`DeviceConnected`、`DeviceDisconnected` 由 device 行为族处理；原始采样/去抖仍在 Adapter，不能为了复用触摸把设备协议塞进 touch Handler。
- Reflection Handler 与 Stimulus/Action Handler 并列为内部入口族，但只有 ReflectionCoordinator 可以创建和投递 `ReflectionJob`。

#### 6.1.4 渐进迁移路线

迁移遵循 expand—migrate—contract，不进行一次性重命名或全目录搬家：

| 阶段 | 对应工单 | 目录/依赖动作 | 完成信号 |
| --- | --- | --- | --- |
| 1. 公开协议 expand | 01、02 | 在 `domain` 中增加强类型协议；可先沿用现有文件，稳定后归入 `domain/agent` | 新旧实现都能依赖协议，但没有 Agent 内部类型进入协议 |
| 2. façade 骨架 | 04 | 建立 `agent/facade.py` 及 `handlers/stimulus/router.py`、`handlers/action/router.py`，AgentRuntime 初始化时装配 | `get_agent` 只返回两接口 façade；旧兼容入口继续取得旧意识对象；既有调用点仅调整取对象的位置 |
| 3. 两个核心纵切 | 05、06 | 建立 `context/`、`processing/`，以及首个 stimulus/action Handler 和对应 Skill | 公开入口完成单次处理和失败停止；processing/context 不被外部 import |
| 4. 认知与状态 Skill | 08、09、11、12 | 将 `main_chat.py`、`prompt_assembly.py`、`response_parser.py` 中的认知生成逐步收进 `skills/cognitive`；图片/语音走 typed adapter；显式记忆走 `skills/mutation` | stage 不再调用预处理/Recall/记忆业务代理，检索证据只进入 scoped context |
| 5. Reflection | 13、14 | 建立 `reflection/`、`handlers/reflection`、`skills/reflection`，迁走 stage ReflectionWorker | settlement 只通知 coordinator；压缩/画像/日期/自动记忆不暴露给 stage |
| 6. 可观察链路迁移 | 07—25 | 按聊天、触摸、主动发言、Toy、WorldStage、歌曲/动态/日记逐链切换；`response_realizer.py` 的语义决定进入 cognitive Skill，TTS/唱歌/媒体实现进入 action Handler + execution Skill | 每条链从两个 façade 接口通过，旧链对该行为无生产调用者 |
| 7. contract 收束 | 29 | 删除 `agent/reflex`、旧 `LuoTianyiAgent`/AgentRuntime 业务代理、外部 `agent.main_chat` 类型依赖和 capability 旁路；清理临时 adapter | A1—A9 的 import/调用扫描通过，不存在永久双轨 |
| 8. 集成验收 | 30 | 只从公开入口复验全部行为和九类 clock 链 | 架构、黑盒行为、持久结果与失败语义同时通过 |

现有文件的目标归属遵循下表，不要求在第一个 PR 中机械移动：

| 当前实现 | 目标归属与迁移约束 |
| --- | --- |
| `agent/luotianyi_agent.py` | 行为由 façade、stimulus Handler 和 cognitive Skill 吸收；所有调用方迁完后删除旧类，不保留第三个业务入口 |
| `agent/main_chat.py`、`prompt_assembly.py`、`response_parser.py` | 角色内容理解/生成进入 `skills/cognitive`；跨模块所需的输出协议改用 `domain.agent`，不继续从 `agent.main_chat` 导入内部响应类 |
| `agent/response_realizer.py` | “说什么/如何分段”的语义选择进入 cognitive Skill；已决定的 TTS、唱歌、预制音频、表情和输出顺序进入 action Handler + `skills/execution` |
| `agent/reflex/*` | 在工单 15 迁入 `handlers/stimulus/touch.py` 及复用 Skill；工单 29 删除旧包与导出 |
| `agent/affection_manager.py` | 角色状态读取/变更分别进入 cognitive 或 mutation Skill；若只是 subconscious 的技术实现，由私有 adapter 包装，不留 façade 旁的通用 manager |
| `agent/text_cleaning.py` | 移入实际拥有该规范化不变量的 cognitive/execution Skill 内部；不得演化为无边界 utils 包 |
| `capabilities/CapabilityManager` | 迁移期间可作为装配用技术容器，但 Handler 不得依赖；逐项被 typed Skill adapter 取代直接业务调用后，再决定是否保留为纯基础设施聚合 |
| `agent_runtime` 业务代理与 `CharacterRuntime` | `SystemRuntime` 只保留生命周期、registry 和 façade 获取；工单 29 删除认知/表达/记忆代理及生产使用 |

### 6.2 PlanEmitter

接口见 [计划交付契约](../../项目说明/项目架构与接口（spec）/接口文档/agent/plan-emitter.md)。Handler 提交完整草稿，emitter 绑定本次身份及连续序号并交付；成功确认后才发送下一份，首次失败后停止发送，结束时关闭。状态只保存在本次内存中。

### 6.3 Handler

Handler 是 Agent 内部“针对一类输入采取哪条流程”的模块。它的 interface 只对 Agent 内部可见。

| Handler 族 | 含义 | 处理刺激 | 典型内部链 |
| --- | --- | --- | --- |
| `ConversationTurnHandler` | 对已提交的文字、图片或非 Realtime 语音形成正式认知与回应；Chat 聚合期限到达时基于全部 pending 强制完成同一流程 | `TextMessage`、`ImageMessage`、`VoiceMessage`、Chat 中的 `InteractionDeadline` | 预处理/多模态理解 → Recall → Attention → 内容生成 → 计划 |
| `InteractionCoordinationHandler` | 根据非内容协调信号决定继续等待还是重评全部 pending | `UserTyping`、`ImageSelectionOpened/Closed` | 等待策略 → completed report（保留 pending）或要求 stage 在新 revision 重评 |
| `TouchInteractionHandler` | 处理 Chat/Toy 的低延迟触摸反应及普通回复回退 | `TouchInteraction` | 快速候选/Attention → 瞬时计划；失败或未命中时复用普通内容 Skill |
| `DeviceInteractionHandler` | 处理已由 Adapter 去抖/聚合的设备连接、断开与振动事实 | `ToyVibration`、`DeviceConnected`、`DeviceDisconnected` | 设备事实 → 可选 Attention/短内容 → 表达或动作计划 |
| `ProactiveContentHandler` | 处理主动提醒、动态和日记规划 | `ProactivePromptDue`、`DynamicObserved`、`DiaryPlanningDue` | Recall/事实 → 是否表达 → 内容生成 → 计划 |
| `ActivityHandler` | 处理 world 事实、每日规划和已实现的活动生命周期 | `WorldObservation`、`DailyPlanningDue`、`ActivityDue/Started/Observation/Ended` | world 事实 → 状态/日程 Recall → 决策 → 活动/日程计划 |
| `SongKnowledgeHandler` | 决定是否接纳候选歌曲知识、是否申请学歌，以及如何理解已学会事实 | `SongKnowledgeDiscovered`、`SongLearned` | 核验证据 → Agent 内部知识/经验变更 → 可选学歌或表达计划 |

每个已注册 `StimulusKind` 由一个明确的行为族 Handler 接受；Handler 可以读取 InteractionSnapshot 决定具体行为，但 Router 不预先注册 `StimulusKind + InteractionKind` 的笛卡尔积。当前确实不支持的场景由 Handler 返回稳定 `UNSUPPORTED_*` 结果。按行为族组织，而不是为每个枚举或每个组合建立浅转发类，也不建立带几十个可空开关的统一 pipeline。

Handler 可以：

- 调用该阶段允许的认知 Skill；
- 通过 scoped context accessor 读写 interaction 临时认知状态；
- 通过幂等内部状态变更 Skill 修改 Agent 自有记忆/知识；
- 把完整 `ActionPlanDraft` 依次交给 PlanEmitter；
- 返回内部 `HandlerDecision`，分别说明 considered/consumed/retained pending IDs、下一次重评时间和反思证据。

Handler 不可以：

- 直接调用数据库、SystemRuntime、stage、外部连接或 plan sink；
- 直接调用 TTS、发布、日程、world task 或设备输出；
- 自己创建后台 task 绕过 ReflectionCoordinator 或持久 scheduler；
- 自己分配公开 ID 或构造公开报告；
- 在未知刺激时回退到通用 LLM 猜测处理。

每种 ActionKind 恰好由一个 Action Handler 实现。它调用 execution Skill，产生 AgentOutput 或提交明确副作用，并返回内部 ActionResult。跨 Action 顺序、取消和停止规则由 realizer 统一控制。

Reflection Handler 只消费内部 `ReflectionJob`。它不能产生 ActionPlan、AgentOutput、HandlingReport，也不能递归调用 `handle_stimulus`。

### 6.4 Skill

Skill 是多个 Handler 可复用的 Agent 内部语义能力。Skill 比底层 capability 更接近角色任务，但不决定完整刺激流程。

| Skill 类别 | 第一版 Skill | 含义与主要使用者 |
| --- | --- | --- |
| 认知读取 | `MemoryRecall`、`AttentionSelection`、`FactLookup`、`ImageReading`、`SpeechUnderstanding`、`ResponseComposition` | 为多个 Stimulus Handler 提供记忆检索、注意力选择、事实、图片、语音和内容生成，不提交外部副作用 |
| 临时上下文 | `InteractionContextRead/Update` | 给对话、协调信号和活动 Handler 提供 interaction 隔离的临时认知状态 |
| Agent 自有状态变更 | `IntentionalMemoryCommit`、`SongKnowledgeAcceptance`、`LearnedSongExperienceCommit`、`CharacterStateUpdate` | 在 handle 内幂等修改角色自己的记忆、知识或状态；不经过 stage/ActionPlan |
| Action 实现 | `SpeechSynthesis`、`Singing`、`Expression`、`Motion`、`Publishing`、`Scheduling`、`ActivityTransition`、`SongLearningDispatch` | 只被对应 Action Handler 使用，把已经决定的 Action 变成输出或外部效果 |
| 事后反思 | `TurnMemoryConsolidation`、`ContextCompaction`、`UserProfileUpdate`、`ImportantDateReview` | 只被 Reflection Handler 使用，维护长期认知数据，不产生用户可见输出 |

Skill 设计规则：

- interface 使用强类型语义输入输出，不暴露供应商请求、数据库 session 或任意字典；
- 一个 Skill 隐藏完整可复用行为，不为每个底层方法再建一层同名转发；
- Handler 通过构造时注入的 SkillSet 获得依赖，不使用全局查找；
- 同一 Skill 可内部组合 subconscious、capability 和外部 Adapter，但角色身份、用户作用域、证据和期望 revision 必须显式；
- 认知读取 Skill 不提交长期或外部副作用；
- Agent 自有状态变更 Skill 只修改 Agent 所有的数据，必须幂等并返回目标存储签发的已提交 revision；
- Action 实现 Skill 只实现已决定语义，不能重新决定回复内容；
- Reflection Skill 可以维护长期认知数据，但不产生用户可见输出；
- 模型可见 tool schema 只来自 allowlist；参数先验证为强类型 Skill input；未知工具明确失败；
- 只有存在生产与测试实现或真实替换需求时才增加 port，不能为单一实现堆叠纯转发层。

### 6.5 不同刺激如何共享 Skill

不同 Handler 不要求经过统一固定 pipeline：

- Text 可以使用 `MemoryRecall → AttentionSelection → ResponseComposition`；
- Image 可以先使用 `ImageReading`，再复用相同 Recall、Attention 和内容生成；
- Touch 可以只使用低延迟注意力规则和短内容生成，不必进行深 Recall；
- UserTyping/ImageSelection 主要使用等待策略和 InteractionContext，不必调用内容模型；
- DynamicObserved 可以复用 ImageReading、FactLookup 和 MemoryRecall，但使用自己的发布语义 Handler；
- DailyPlanningDue 可以复用记忆和注意力，却输出日程和活动 Action；
- DiaryPlanningDue 可以复用记忆与事实，但使用日记内容策略；
- SongKnowledgeDiscovered 可以使用事实核验和 Agent 自有状态变更，不需要聊天回复链。

共享的是 Skill interface 和语义，不是强迫所有刺激依次经过相同步骤。

### 6.6 InteractionContextStore 与单次调用状态

#### `InteractionContextStore`

2026-09-06 输入契约修订：对话工作上下文归 Agent 内部所有，按 `(character_id, interaction_id)` 隔离，统一组织当前使用的历史对话、摘要及 Recall 结果，并管理保留、压缩和清理。清理临时上下文不删除会话或长期记忆正本；一次 handle 取消也不等于 interaction 结束。下表保留已有临时认知字段的设计背景，不是完整上下文 schema，也不要求向 stage 暴露内部访问器。输入快照删除对话/world 内容引用，不建立通用 `SnapshotRef` 或快照持久化/解析服务。

façade 先按角色和 interaction 创建 scoped accessor，Handler 不接触全局 store：

```python
class ScopedInteractionContext(Protocol):
    async def read(self) -> InteractionCognitiveContext:
        ...

    async def compare_and_set(
        self,
        expected_context_revision: int,
        update: InteractionContextUpdate,
    ) -> InteractionCognitiveContext:
        ...
```

| 上下文字段 | 类型 | 含义 | 约束 |
| --- | --- | --- | --- |
| `scope` | `InteractionScope` | `(character_id, interaction_id)` 隔离键 | 不以 user_id 单独作为 key |
| `context_revision` | `int` | Agent 内部临时认知上下文的修订 | 单调递增；写入使用 compare-and-set；不得与 stage 的 interaction revision 混用 |
| `attention_focus` | `Optional[AttentionFocus]` | interaction 内当前关注对象 | 只保存受控语义引用 |
| `pending_clarifications` | `tuple[PendingClarification, ...]` | 适合在当前 interaction 后续刺激中考虑的待澄清项 | 与长期关系层待澄清区分；有 TTL |
| `unfinished_intents` | `tuple[InteractionIntent, ...]` | 当前 interaction 尚未结束的认知意图 | interaction 结束或过期时清理 |
| `expires_at` | `datetime` | 临时上下文自动失效时间 | 带时区；不得无限保存原始内容 |

stage 的 pending、deadline 和连接状态不写入这里；它们始终以 InteractionSnapshot 为准。用户画像、关系、长期记忆和歌曲知识由 subconscious 的长期存储负责。

#### 单次调用状态

Handling 保存本次已接收计划标识；Execution 保存本次行动结果、输出序号和接收标志。调用结束后不把这些状态保存为重投依据。

agent/ledgers 源码仍保留，但当前业务流程不创建或调用它。已有数据库记录未被本次调整删除。

### 6.7 Agent 自有状态变更与歌曲链路

#### 为什么四类名称不能一概作为 Action

| 原名称 | 本设计归属 | 原因与结算语义 |
| --- | --- | --- |
| `RecordIntentionalMemory` | 内部 `IntentionalMemoryCommit` Skill | “记住这件事”修改 Agent 自己的长期记忆。Handler 必须等待幂等提交或可靠内部命令被接受，成功后才可 emit 表示已记住的 Say；失败则保留刺激并返回失败报告，retryable=False |
| `UpsertSongKnowledge` | 内部 `SongKnowledgeAcceptance` Skill | 候选资料是否成为角色知识是 Agent 内部认知决定，不应让 stage 执行数据库动作 |
| `RecordLearnedSong` | 内部 `LearnedSongExperienceCommit` Skill | 技术任务完成后，角色如何记录“我学会了”属于 Agent 经验/记忆，不是外部角色行动 |
| `RequestSongLearning` | `ActionPlan + realize` | 学歌会启动可恢复、跨进程、有凭证/资源/工件生命周期的外部长任务，通过 realize 提交，任务持久状态由所属任务模块管理 |

内部状态变更不等于 Reflection。由当前刺激直接触发、且后续承诺依赖写入结果的变更在当前 handle 内完成；自动总结、画像、日期检查等事后维护仍由 Reflection 异步执行。两者都不经过 stage，但时序不同。内部变更返回实际提交结果，后续承诺与反思据此判断，不要求写入请求恢复账本。

#### 抓取、模型处理与 Stimulus 边界

```text
world crawler / parser
  -> 抓取、反爬处理、结构解析、规范化、去重、证据封装
  -> SongKnowledgeDiscovered
  -> SongKnowledgeHandler
       -> SongKnowledgeAcceptance（Agent 内部状态）
       -> 可选 RequestSongLearning Action
  -> realize -> 持久 world/capability 学歌任务
  -> 工件生成、验证、媒体库刷新
  -> SongLearned
  -> SongKnowledgeHandler
       -> LearnedSongExperienceCommit（Agent 内部状态）
       -> 可选 Say/Sing/PublishDynamic Action
```

边界按“模型在做什么”而不是“是否用了 LLM”划分：

- 抓页面、反爬、解析字段、清洗歌词、下载/生成/校验工件等机械处理在 world/capability 外部长任务中；为了结构化页面或工件而调用模型，也仍在 Agent 外；
- 决定资料是否可信、与角色已有知识是否冲突、这首歌对角色意味着什么、是否想学或如何表达，属于 Agent 的 Handler/Skill；
- 外部流程不得先直接写入 Agent 的 Song Knowledge 再补刺激。它只产生候选或完成事实；Agent 接纳后才写自己的知识/经验；
- `SongLearned` 只在技术工件已经验证可用后产生。任务的中间进度和模型中间结果不是 Stimulus，留在任务内部 ledger/日志；
- 学歌任务失败由对应 execution/task 记录；只有失败事实确实需要角色认知时，未来才能增加专门强类型 Stimulus，不能复用 `SongLearned` 表示失败。

### 6.8 慢 Recall

慢 Recall 是当前 handle 内部的异步等待：

1. Handler 可以启动 deep recall；
2. 必要时先形成完整临时计划，经 PlanEmitter 发射；
3. handle coroutine 继续等待内部结果；
4. 结果返回后检查 cancellation；
5. 未取消时形成新的完整计划并携带原 `basis_interaction_revision`；stage-bound plan sink 再根据当前 revision 接受或拒绝；
6. 最后返回 HandlingReport。

Recall future、callback 和结果不转换为 `RecallCompleted` Stimulus，不进入 stage，不递归调用公开 Agent interface。

### 6.9 Post-Interaction Reflection

#### `ReflectionCoordinator` 与 `ReflectionHandler`

`ReflectionCoordinator` 负责“在什么结算时点检查反思条件、是否已调度、如何重试和排序”；`ReflectionPolicy` 负责“当前 Agent 自有状态是否满足某项反思条件”；`ReflectionHandler` 负责“对一份已固定证据执行已选定的反思 Skill”。三者不合并为 Action Handler，也不暴露给 stage。

Reflection 的目标证据来源是实际处理报告和业务存储，不依赖请求或执行账本。设计流程是：

```text
Agent façade 完成 handle，或 realizer 形成新的可结算执行事实
    -> 发出内部 settlement notice
    -> ReflectionCoordinator 接收实际处理与执行结果
    -> ReflectionPolicy 查询对话长度、画像策略、日期证据等 Agent 自有状态
    -> 无满足条件的 step：只记录 policy 已检查
    -> 有满足条件的 step：构造一次幂等 ReflectionJob
```

| settlement 情况 | Coordinator 取得的事实 | Policy 如何决定 |
| --- | --- | --- |
| `COMPLETED` 且消费了内容、没有计划 | 处理报告中的 consumed pending 和已确认内部变更 | 按证据种类判断记忆、日期等步骤；协调信号本身通常不产生反思 |
| `COMPLETED` 且发出计划 | 等相关 plan 有最终 ExecutionReport 后读取实际输出和效果 | 只反思真实完成内容，不把 `NOT_STARTED` Action 当成事实 |
| `CANCELLED` / `FAILED` | 查询取消/失败前是否已有 consumed 内容、可见输出或不可逆效果 | 只有真实发生内容满足某项 policy 时才创建 job |
| pending 全部 retained | 没有完成式内容证据 | 不创建本轮完成式反思；等待以后 settlement |

上下文压缩的条件是 Conversation Context Store 中的消息/token 数量或策略估算超过阈值，不是请求结束本身。一次内容 settlement 只是安全的检查时点：`ReflectionPolicy` 读取固定 context revision，超过阈值才把 `ContextCompaction` 加入 allowed kinds；未超过就跳过。画像更新、重要日期检查和自动记忆整理同样由各自 policy 根据证据决定。

```python
class ReflectionHandler(Protocol):
    async def handle(self, job: ReflectionJob) -> ReflectionReport:
        ...
```

| `ReflectionJob` 字段 | 类型 | 含义 | 约束 |
| --- | --- | --- | --- |
| `reflection_job_id` | `str` | 一次结算事实的稳定内部任务身份 | 重投不变化 |
| `schema_version` | `int` | job 结构版本 | 不兼容版本明确失败 |
| `character_id` | `str` | 被维护认知状态的角色 | 不能为空 |
| `user_id` | `Optional[str]` | 相关关系/画像用户 | 无用户活动为空；不能回退默认用户 |
| `interaction_id` | `str` | 证据所属 interaction | 与实际交互一致 |
| `origin_request_id` | `str` | 触发结算的 handle 请求 | 与处理请求一致 |
| `source_stimulus_ids` | `tuple[str, ...]` | 允许作为反思证据的刺激 | 只含实际 consumed 的内容，以及 ReflectionPolicy 明确允许的非内容事实；不能把所有 considered/retained 刺激自动当成证据 |
| `completed_effects` | `tuple[SettledEffect, ...]` | 实际完成的 plan/action/output 摘要 | 不把 NOT_STARTED 行动当成事实 |
| `allowed_kinds` | `frozenset[ReflectionKind]` | 本 job 允许执行的反思步骤 | 最小权限；Handler 不自行扩大 |
| `idempotency_key` | `str` | job 接受和 step 去重键 | 同一结算事实稳定 |
| `attempt` | `int` | 当前投递次数 | 正整数；不参与语义判断 |
| `created_at` | `datetime` | job 首次创建时间 | 带时区 |

2026-09-06 修订删除了上述 job 草案中的 `evidence_snapshot_ref: SnapshotRef`。反思确实需要的证据及其保留期限应由 Agent 内部反思契约定义，不依赖交互输入快照存储；本次不另造证据引用类型或承诺后台反思已具备证据恢复能力。

| `ReflectionReport` 字段 | 类型 | 含义 | 约束 |
| --- | --- | --- | --- |
| `reflection_job_id` | `str` | 被报告的内部 job | 与输入一致 |
| `step_results` | `tuple[ReflectionStepResult, ...]` | 每个允许步骤的真实结果 | 包含 completed/skipped/failed 与稳定原因 |
| `retryable` | `bool` | 未完成步骤是否可用同一 job 安全重试 | 已完成 step 不重复提交 |

| `ReflectionStepResult` 字段 | 类型 | 含义 | 约束 |
| --- | --- | --- | --- |
| `kind` | `ReflectionKind` | 被执行或跳过的反思步骤 | 必须来自 job 的 allowed kinds |
| `status` | `ReflectionStepStatus` | `COMPLETED`、`SKIPPED` 或 `FAILED` | 只能报告真实状态 |
| `error_code` | `Optional[ReflectionErrorCode]` | 稳定失败或跳过原因 | 不包含异常堆栈或敏感内容 |
| `committed_revision` | `Optional[int]` | 成功写入后由目标存储返回的专有修订 | 只在实际写入且该存储提供 revision 时填写；不解释成全局 StateVersion |

Reflection Handler 第一版可组织：自动对话/事件记忆整理、上下文压缩、用户画像更新、重要日期/生日/纪念日检查，以及必要的内部关系/注意力摘要更新。它不能产生 ActionPlan、AgentOutput 或新 Stimulus，也不能递归 handle。

#### 执行和可靠性

- 交互路径只等待 ReflectionCoordinator 可靠接受或记录待提交，不等待具体反思 Skill 完成；
- 已接受 job 使用至少一次投递，各 reflection step 自己幂等；
- 同一 `(reflection_job_id, reflection_kind)` 最多成功提交一次；
- 关系相关 job 按 `(character_id, user_id)` 有序；无用户活动按 `(character_id, interaction_id)` 有序；不同 key 可以并行；
- 需要 user 的画像和日期 Skill 在 `user_id` 为空时明确跳过；
- 队列容量有界。容量满或持久接受失败必须记录稳定事件与重试状态，不能静默丢弃，也不能把已成功回复改报为失败；
- shutdown 停止接受新 job 后，已接受 job 必须完成、超时后可靠保留，或让 shutdown 明确失败以供重试；
- 管理与观测界面可以查看积压、失败和重试，但不增加 Agent 业务方法。

ImportantDateReview 只能把用户明确表达且字段充分的日期标成 confirmed。模型推测或歧义结果只能成为按 `(character_id, user_id)` 隔离、带 TTL 的内部 `PendingClarification`，不能直接写成已确认纪念日。Reflection 不得从后台直接向通道发问；后续合适的 Stimulus Handler 可读取待澄清项并决定是否形成追问计划。普通反思完成本身不产生 Stimulus。

自动记忆整理必须依据 evidence key 识别同一事实是否已经由 `IntentionalMemoryCommit`、`SongKnowledgeAcceptance` 或 `LearnedSongExperienceCommit` 写入，避免生成语义重复记录。

### 6.10 行为边界总表

| 工作 | 归属 | 含义与原因 |
| --- | --- | --- |
| 搜索记忆、阅读图片、选择注意力 | handle 内认知 Skill | 为当前决定提供只读信息 |
| 用户明确要求记住、接纳歌曲知识、记录学会经验 | handle 内 Agent 自有状态变更 Skill | 修改 Agent 自己的数据；写入结果可能是当前承诺前置条件，但无需 stage 实现 |
| 说话、唱歌、动作、发布、日记、日程、活动迁移 | ActionPlan + realize | 已决定且需要输出、外部效果或调用方结算 |
| 启动跨进程学歌任务 | `RequestSongLearning` Action | 需要持久调度、恢复、资源生命周期和 execution 结算 |
| 自动提取本轮长期记忆 | Reflection | 是 Agent 的事后认知维护 |
| 压缩上下文、更新画像、检查纪念日 | Reflection | 不应暴露给 stage，也不是角色外部行动 |
| 慢 Recall | 当前 handle 内 future | 仍属于本次认知，不是事后任务 |
| 抓取网页、机械模型处理、下载/验证学歌工件 | world/capability 长任务 | 外部技术过程，不是角色心智 |
| 规范化候选知识或已验证学歌结果 | 新 Stimulus | 外部事实已经具备让角色认知的稳定边界 |

## 7. Implementation Decisions

1. Agent 对外业务 interface 固定为 `handle_stimulus` 和 `realize_action_plan`；生命周期只由 AgentRuntime 管理。
2. 两个方法使用完整类型提示，参数固定命名为 `request / plan_sink` 与 `plan / execution_context / output_sink`。
3. Agent 内部包含 Façade、Handler、Skill、InteractionContextStore、Handling、Execution 和 ReflectionCoordinator/Handler；第 6.1 节给出的目录是最终所有权边界，但只在承载真实实现时创建，不以空包或薄转发满足架构。
4. Handler 按行为族组织；不同刺激可以走完全不同链路，只共享适用 Skill。
5. PlanEmitter 是 Handler 的内部协作者，集中分配计划身份、ordinal、顺序交付并委托外部 ActionPlanSink。
6. InteractionSnapshot 当前只包含 Chat、Toy、World 三种强类型变体；不建立统一 BaseStage。
7. `WorldStage` 是每个 `(character_id, world_id)` 的长期人格—箱庭交互 stage；所有需要角色认知的 world 事实都经过它，不使用 one-shot runner 绕开连续上下文。
8. `world` 是外部环境和事实所有者；`world_clock` 只是时间驱动。world 领域定时由 clock 唤醒 world task 后形成 Stimulus，stage 交互定时由 WorldStage 自己管理。
9. HandlingReport 的 `request_status` 只描述调用完成/取消/失败；pending 是否消费只由 considered/consumed/retained ID 集合表达，`reconsider_at` 与 request status 独立。
10. 不使用含义不明的全局 StateVersion：stage 使用 `interaction_revision`，world/activity/schedule 使用各自 revision，拥有状态的模块负责权威校验。
11. 打断权在 stage；Agent 只通过 cancellation 协作停止。PlanEmitter 不读取 stage 状态，stage-bound plan sink 校验 `basis_interaction_revision`。
12. `UserTyping`、`ImageSelectionOpened`、`ImageSelectionClosed` 是协调刺激：其 request 可以完成，同时 consumed pending 为空、retained 包含全部待处理内容。
13. `UserJoinedActivity`、`ActivityInterrupted`、Call/Realtime 刺激和 `CallInteractionSnapshot` 不在当前版本。
14. `ChangeExpression` 只保留为 `Say`/`Sing` 内嵌值对象；没有独立 Action。`Say` 和 `Sing` 都可以同时产生表情输出。
15. `HAPTIC` 和 `PerformHaptic` 不存在；当前触摸反馈继续使用音频、文字和表情。
16. Agent 自有的记忆、知识、经验和状态变更不进入 ActionPlan；`RecordIntentionalMemory`、`UpsertSongKnowledge`、`RecordLearnedSong` 改为内部强类型状态变更 Skill。
17. `RequestSongLearning` 保留为 Action，因为它启动外部、持久、可恢复的长任务，经 realize 提交并报告本次结果。
18. 抓取、机械模型处理和工件生成/校验留在 world/capability；稳定候选或完成事实经 WorldStage 触发 Stimulus。角色意义判断留在 Agent。
19. 自动记忆整理、上下文压缩、用户画像更新和重要日期检查由 Agent 内部 Reflection 完成，不是 ActionPlan。
20. façade 的 settlement notice 使 ReflectionCoordinator 检查条件；ReflectionPolicy 根据上下文长度和证据等 Agent 自有状态选择步骤；处理报告提供实际结果，不以请求结束直接决定反思条件。
21. provider 工具调用只能落到只读 Skill、Agent 自有状态变更 Skill 或强类型 Action，不能使用通用 `CALL_CAPABILITY`。
22. `SystemRuntime` 负责系统依赖组装；AgentRuntime 初始化时显式装配角色 Agent 及其内部协作者和 Handler registry，不得新增全局查找。
23. 本 spec 是目标 interface；当前实现文档仍描述事实，未实现前不能把目标方法写成已可调用。
24. 实现采用 expand—migrate—contract：先增加新协议和 façade，再按可观察链路迁移，所有生产调用方完成后统一删除旧入口；小 PR 不等于允许永久双轨。
25. 本地 Markdown 工单已完成粒度与 blocker 评审，并一对一发布为 GitHub Issue；本地文件继续作为可版本化底稿，Issue 是开发协作与状态跟踪入口。
26. `agent/handlers` 按 stimulus、action、reflection 三类内部入口分组；stimulus/action 再按行为族拆分，不为每个枚举建立一层同名转发类。
27. `agent/skills` 是 Agent 私有的强类型语义能力层，既有 `capabilities` 是技术实现层；Handler 只依赖 Skill，不能直接依赖 `CapabilityManager`，两者不做一对一镜像。
28. `agent/context` 只保存 interaction-scoped 临时认知工作集和有来源/版本/TTL 的检索证据；stage pending、连接、长期记忆/画像和权威 world 状态不得迁入。
29. 两个 façade 的跨模块协议归 `domain` 所有；Agent 包根只导出 façade 类型，内部包不公开重导出；AgentRuntime 初始化负责角色依赖与 Handler registry 的显式装配，不建立独立 factory。
30. 目录迁移必须按第 6.1.4 节渐进执行：先协议和 façade，后逐链迁移，最后统一删除 `agent/reflex`、旧 AgentRuntime/CharacterRuntime 业务代理和外部 `agent.main_chat` 类型依赖；不得永久双轨。
31. `StimulusSource` 只包含 `USER / DEVICE / WORLD / STAGE` 四种当前已定义的语义来源；外部调用方选择强类型 Stimulus 并显式填写 source，Agent 不推断或改写；scheduler 和 `world_clock` 只是时间驱动与投递机制，也不得覆盖已有 source。
32. 目标 Stimulus interface 不包含 `PersistPolicy`；会话记录和长期记忆候选由 Agent 内部结合刺激、interaction、隐私设置和业务存储判断。构造器只校验字段自身与变体结构，不维护 `kind / source / ephemeral` 组合矩阵；没有可复现问题和先行 SPEC 修订时，不得把理论组合列为审核阻塞项。

## 8. 验收标准

本节定义重构完成时必须同时满足的结果，不等于测试文件拆分方案。验收比较的是公开 interface、外部可观察输出、持久结果、时序、去重和失败语义；不要求保留当前 `TopicPlanner`、`TopicReplier`、`ReflectionWorker`、world task 或 `CharacterRuntime` 的内部类形状。任何一项未满足，都只能称为迁移中的中间状态，不能称为架构重构完成。

当前行为基线来自 2026-09-04 工作区中的 `chat_session/chat_pipeline`、`agent/reflex`、`ProactiveTopicMaker`、`WorldRuntime`、`WorldClock`、各 world task 和 `server/config/config.json`。如果实现前这些行为已经另行修改，应先更新本节并评审，不能让测试从届时实现反推验收标准。

### 8.1 架构收束硬门槛

| 编号 | 验收要求 | 可检查的完成状态 |
| --- | --- | --- |
| A1 | Agent 业务 interface 收束 | 通过 `AgentRuntime.get_agent(character_id)` 得到的 Agent 只暴露 `handle_stimulus(request, plan_sink)` 与 `realize_action_plan(plan, execution_context, output_sink)` 两个业务方法；生命周期方法不承载角色业务。`ActionPlanSink` 和 `AgentOutputSink` 是调用方传入的协作 interface，不算额外 Agent 业务入口 |
| A2 | Agent 内部不泄漏 | Handler、Skill、PlanEmitter、InteractionContextStore、Handling、Execution、ReflectionCoordinator/Handler、Recall 结果、提示词、模型会话、subconscious、capability 实例及 Agent 自有存储都不从 Agent 包公开导出，也不出现在外部参数、返回值或 callback 中 |
| A3 | 角色认知只有一条入口 | 聊天、触摸、主动发言和 world 事实中，只要步骤涉及角色理解、记忆检索、注意力、是否回应、说什么、唱什么、是否接纳知识或如何记录经验，就必须由相应 stage 构造强类型 request 并调用 `handle_stimulus`；外部模块不得继续调用 AgentRuntime 业务代理、`CharacterRuntime`、subconscious、提示词或模型模块 |
| A4 | 角色行动只有一条实现入口 | `ActionPlan` 中的说话、唱歌、表情、动作、发布、日记、日程、活动迁移和学歌请求只由 `realize_action_plan` 实现并结算；stage/world/system 不得直接调用 TTS、singing、dynamics、diary 等角色 capability 来实现计划。handle 返回零计划时不需要空调用 realize |
| A5 | 外部职责仍留在外部 | 协议校验、消息 ACK、pending/deadline、连接、通道立即停止、world 抓取、凭据刷新、机械模型处理、权威 world 状态和数据库维护仍由 Adapter/stage/world/system 拥有；它们可以不调用 Agent，但一旦需要与 Agent 交互，只能使用 A1 的两个方法 |
| A6 | 迁移双轨已经删除 | `AgentRuntime.preprocess_chat_event/extract_topic/plan_topic_turn/realize_topic_plan/write_topic_memories/detect_dates_for_topic/update_user_profile_by_context/try_handle_reflex`、`get_character_runtime` 业务使用，以及 world 为角色理解、表达或 Agent 自有状态而直接调用 `CharacterRuntime`/capability 的路径都已从目标调用方移除；机械长任务只能依赖专用技术 seam；不存在“新 façade + 旧业务代理”永久并行 |
| A7 | 外部只能依赖公开领域协议 | stage 与 world 只依赖公开的强类型 Stimulus、InteractionSnapshot、ActionPlan、ExecutionContext、两个 sink/receipt 和两个 report；不得依赖 `UnreadMessage`、`ExtractedTopic`、`AttentionPlan`、`OneSentenceChat`、`SongSegmentChat` 等 Agent 内部迁移类型 |
| A8 | 内部异步维护归 Agent | 日期检查、记忆整理、上下文压缩和用户画像更新由 Agent 内部 settlement/Reflection 链调度；stage 不持有 Reflection worker，也不调用这些具体步骤。它们不进入 ActionPlan，不因后台失败改写已经完成的用户输出 |
| A9 | 包所有权与依赖方向收束 | 最终代码符合 6.1 的目录所有权：外部只依赖 `domain.agent` 与 Agent façade；`agent/__init__.py` 不导出内部对象；Handler 通过强类型 Skill/context/processing 协作且不直接依赖 capability/数据库/SystemRuntime；Skill 不反向依赖 Handler/stage/report；旧 `agent/reflex`、外部 `agent.main_chat` 类型依赖和无生产必要的过渡 adapter 已删除 |

最终依赖扫描必须能证明：在 `server/src/agent` 与装配代码之外，角色认知调用方只能取得 Agent façade 和公开领域对象；world/capability 的机械任务只能取得为其技术过程定义的窄依赖，不能借此读取 Agent 内部状态或生成角色表达。每个仍存在的旧入口要么已删除，要么没有生产调用者且不再作为公开 interface 导出。仅把旧调用包进另一个同名转发层不满足 A1—A9。

### 8.2 功能兼容总则

- 重构不以“架构更干净”为由改变当前用户可观察行为。相同的有效输入、时钟条件、角色配置和外部依赖结果，应得到等价的文字、音频、表情、动态、日记、事件、歌曲资源和持久状态；随机行为以相同概率、候选集合和去重规则验收，不要求固定抽中同一项；
- 当前的等待、超时、合并、过期结果丢弃、触摸合流、主动消息去重、world task 跳过/失败和后续周期继续运行语义必须保留；
- 允许替换内部对象和队列，但不允许丢失当前链路中的副作用，也不允许因迁移重复回复、重复发布、重复创建日程、重复记忆或重复学歌；
- 本节中的“目标链路”表示最终模块协作路径。纯机械 world 任务不会因为由 `WorldClock` 唤醒就自动成为 Stimulus；只有形成了需要角色感知或决定的稳定事实时，才经 stage 进入 Agent。

### 8.3 聊天流验收

所有当前聊天输入统一经过 `外部消息 -> Adapter -> ChatStage -> Agent.handle_stimulus`；产生计划时再经过 `Agent.realize_action_plan -> AgentOutputSink -> Adapter -> 当前聊天通道`。必须保持下列行为：

| 当前输入或条件 | 必须保持的行为 | 目标 settlement / 输出 |
| --- | --- | --- |
| `USER_MESSAGE` / `USER_TEXT` | Adapter 校验非空文本、长度和目标角色，按 `client_msg_id` 去重并在 stage 容量不足时明确拒绝；有效文本加入该 interaction 的 pending，并重置普通聚合期限。Agent 在 handle 内部判断并保证需要的会话/记忆证据最多持久化一次 | `TextMessage` 进入 ChatSnapshot；正式判断后按 ID 消费实际处理的消息，回复由 `Say`/`Sing` 计划实现 |
| `USER_IMAGE` | Adapter 继续校验 Base64、MIME、大小和目标角色；图片消息进入 pending。图片读取、图文理解、持久化判断和歌曲/日期等语义预处理移入 Agent 内部 Skill，不再由 stage 调 AgentRuntime 预处理代理或选择持久化策略 | `ImageMessage` 进入 ChatSnapshot；handle 可与其他 pending 文字一起处理，图片内容不以本地任意路径泄漏，需要的持久化事实按稳定 stimulus/client ID 最多提交一次 |
| 普通新内容到达 | 每条新文字或图片都重新设置普通聚合期限。当前配置未覆盖 `listen_timer.timeout`，因此基线默认值为 1 秒；实现仍应读取 stage 配置，不把 1 秒写死在 Agent | 新内容使 `interaction_revision` 递增；旧结果若已基于不同 pending 集合则不能提交 |
| `USER_TYPING(text_length > 0)` | 信号不加入内容 pending，也不得形成会话记录或记忆证据。只有存在 pending 或正在判断时才把期限延长到 10 秒并唤醒状态机；没有 pending 且没有 handle 时不产生回复 | request 可以 `COMPLETED`，consumed 为空，considered 全部 retained，`reconsider_at` 为延长期限；不持久化是 Agent 当前内部判断的可观察结果，不是调用方传入策略 |
| `USER_TYPING(text_length == 0)` | 信号不加入内容 pending，也不得形成会话记录或记忆证据；移除输入扩展期限并立即唤醒判断。WebSocket 入口仍要求 `text_length` 是非负整数，缺失、布尔值或负数不能被当作合法清空信号 | request 完成但不消费信号本身；现有 pending 立即进入正式重评 |
| `USER_IMAGE_SELECTING` | 信号不加入内容 pending，也不得形成会话记录或记忆证据；存在 pending 或正在判断时把期限延长到 60 秒。若旧判断正在运行，其尚未提交结果失效，原 pending 保留 | `ImageSelectionOpened` 完成，consumed 为空，全部 considered 保留到图片选择期限 |
| `USER_IMAGE_SELECTING_CANCEL` | 信号不伪造图片，也不得形成会话记录或记忆证据。存在 pending 或正在判断时结束 60 秒扩展并恢复普通聚合期限；没有 pending 且没有 handle 时清除期限。若随后真有图片，仍由独立 `ImageMessage` 到达 | `ImageSelectionClosed` 完成，consumed 为空，pending retained，`reconsider_at` 为普通期限；不是无条件立即回复 |
| 普通聚合期限到达 | 不能因为话语看似不完整而无限等待。stage 产生 `InteractionDeadline`，handle 必须基于当时全部 pending 进行强制正式判断；除角色按明确语义选择沉默或出现结构化失败外，应形成可实现回复 | deadline trigger 与内容消费分开报告；全部处理时 consumed 精确等于 snapshot pending、retained 为空 |
| 判断期间出现新内容或延长等待的协调信号 | 当前判断结果不得越过新事实提交。stage 更新 pending/等待状态和 revision，取消旧 handle；旧模型/Recall 结果和旧 report 不得清空新队列，所有仍有效内容基于新 snapshot 重新思考 | plan sink 拒绝旧 revision；stage 按 ID 结算，不能 `consume_all`；新判断使用更新后的快照，不作为旧请求的投递恢复 |
| 一次判断只完成部分 pending | 已完成内容可以形成 topic/计划；尚未完成内容继续保留并恢复普通期限，后续与新内容一起重新判断 | consumed 与 retained 分列，不用 request status 表示部分消费 |
| 回复实现完成 | 普通回复按计划顺序进入全局 speaking/output 队列；Agent 内部按稳定 execution/action 事实完成所需的对话持久化，文字、TTS/预制音频、唱歌和表情的外部顺序与当前一致。完成事实再异步触发日期检查、消息记忆、必要的上下文压缩和画像更新 | 用户可见输出不等待 Reflection；ChatStage 只记录投递/结算事实，不选择 Agent 的会话或记忆策略；Reflection 失败不会撤销已发送回复 |

这里的“重新思考”特指：旧判断尚未形成可接受结算时，新的 pending 集合或延长等待信号使旧结果作废，再基于新 revision 的完整 snapshot 判断。它不是把同一条旧回复先发送再撤回，也不是 `ReflectionHandler` 递归调用公开 handle。

### 8.4 触摸回复验收

触摸仍是 Chat/Toy stage 可提交的 `TouchInteraction`，但所有角色反射逻辑收进 Agent 内部的 `TouchInteractionHandler` 和触摸相关 Skill；不得保留 `AgentRuntime.try_handle_reflex` 或 Ingress 直接发送 `ChatResponse` 的旁路。

| 当前分支 | 必须保持的行为 | 目标链路 |
| --- | --- | --- |
| 快速反射命中 | 当前角色配置概率为 1.0；从该角色 `touch_voice_dir` 的受支持音频中随机选择，读取对应表情映射，立即播放；不显示聊天气泡、不写会话记录。非 `normal` 表情在反应结束后恢复 `normal` | `TouchInteraction -> handle -> Say(prepared_audio_ref, delivery=EPHEMERAL_REACTION, expression) -> realize -> AUDIO/EXPRESSION` |
| 快速资源缺失、读取失败或概率未命中 | 不吞掉触摸，转入普通角色回复链 | `TouchInteraction -> handle` 内改走内容生成 Skill，再输出普通 `Say` 计划 |
| 多次快速触摸排队 | 尚未开始处理时，新触摸更新同一个待处理触摸；已有触摸正在处理时，后续触摸被忽略，不能无限堆积 | 合并/忽略规则由 stage 的触摸 pending 策略维护，Agent 不暴露触摸队列 |
| 触摸输入内容 | 当前 `touchArea/touch_area` 与点击频率继续被校验、归一化为角色可理解的身体区域、动作、强度/频率事实；供应商原始字段不进入 Handler | Adapter 产生强类型 `TouchInteraction`；Agent 只看领域字段 |

快速反射仍然必须经过两个 Agent interface：handle 决定选用哪段反射和表情，realize 才输出预制音频及表情。它可以绕过慢聊天内容生成，但不能绕过 Agent façade。

### 8.5 登录后主动发言验收

登录认证完成时先记录 `elapsed_from_last_login`；对应 `(user_id, character_id)` 的 ChatStage 建立后再处理登录刺激，避免欢迎消息与历史消息拉取混在一起。目标链路统一为 `登录事实 -> ChatStage -> ProactivePromptDue -> handle -> ActionPlan -> realize -> Chat AgentOutputSink`。

| 当前登录情形 | 必须保持的行为 |
| --- | --- |
| 首次登录，`elapsed_from_last_login is None` | 等待约 1 秒让客户端完成历史消息拉取；按配置顺序发送并持久化两条首次欢迎文字，使用各自预制音频，表情为 `normal`，每条都是 final package。迁移后以 `Say(prepared_audio_ref, delivery=CONVERSATION)` 表达，不允许 stage 直接读音频并构造响应 |
| 距上次登录达到 5 天及以上 | 当前明确不派发 `RETURN_LOGIN` 主动话题，不能在重构时擅自恢复久别问候 |
| 非首次登录且这是当天第一次登录 | 查询该角色当前到期的 event；过滤其他角色和不属于当前用户的 personal event，并排除已经按 `(event_id, user_id, character_id, trigger_key)` 通知的记录。只把 holiday、travel、new_song、birthday、anniversary 转成登录话题，合并本次成功 claim 的内容后提交一次正式回复链 |
| 当天已经登录过 | 不派发登录主动话题 |
| claim 后入队失败或被取消 | 释放 notification claim，使后续登录或周期检查仍可重试；成功 claim 防止登录路径与周期检查并发重复提醒 |

登录主动发言的内容选择、角色化表达、记忆检索和声音实现都属于 Agent；ChatStage 只保存登录 pending、历史同步时点、通知 claim 与输出路由。

### 8.6 `WorldClock` 当前注册链路验收

`WorldRuntime._register_clock_actions()` 会把每个 `WorldTask.clock_config` 注册为 daily 或 interval action。当前配置下共九类任务；带 `:{character_id}` 的任务按启用角色分别注册，B 站任务还受角色 UID 配置约束。daily 时间使用服务器本地时钟；interval 的 `run_immediately=true` 表示 `WorldClock.start()` 后先执行一次再等待间隔。

| 当前 clock action | 当前调度 | 当前必须保持的动作与结果 | 收束后的目标链路 |
| --- | --- | --- | --- |
| `try_citywalk:{character_id}` | 每日 04:00；每个启用角色；当前 `daily_run_probability=0.1` | 先按配置概率抽样；未命中、citywalk 不可用、运行错误或无报告时跳过。成功时完成 citywalk 环境流程并产出报告，写入该角色 `travel` event，尝试发布 citywalk 动态并把动态正文/ID 回写报告；动态发布失败不抹掉已完成 citywalk | 概率、地图/环境推进和报告属于 world；需要角色选择路线、表达或发布时，以稳定 `WorldObservation` 进入 WorldStage 和 `handle_stimulus`，发布通过 `PublishDynamic`/`WriteDiary` 等计划及 realize 完成。world task 不再直接取 `CharacterRuntime` |
| `sync_new_song_knowledge` | 每日 04:00；全局一份 | 拉取 VCPedia 模板歌曲列表，按歌曲名/safe name 跳过已有项；抓取并规范化资料，缺少介绍视为失败；成功项写 Song 知识和歌曲名/歌词关键词索引，各歌曲间当前等待 0.8 秒，最后报告 added/failed | 抓取、反爬、页面解析和候选规范化留在 world；每个稳定候选形成 `SongKnowledgeDiscovered`，经 WorldStage/handle 后由 Agent 内部 `SongKnowledgeAcceptance` 写入同等可查询知识和索引。world 不直接写 Agent 知识，也不因发现歌曲自动把所有歌曲加入学歌任务 |
| `learn_sing_songs:{character_id}` | 每日 04:00；有 singing manager 的每个启用角色 | 先检查/刷新 QQ 音乐凭据；失败则本轮不启动。扫描 wishlist pending，已有有效工件的歌曲标为已学但不重复通知；其余运行下载、清理、分段、模型处理和工件校验，维护 learned/already learned/abandoned/awaiting。出现新 learned 时写通知文件和 `new_song` event，刷新唱歌库、生成情绪标签，并为每首新歌尝试发布一次动态 | 扫描、下载、模型处理、重试状态、工件校验、库刷新和标签生成是 world/capability 长任务；只有验证完成才形成 `SongLearned`，经 WorldStage/handle 后由 Agent 内部记录学会经验，并通过 `PublishDynamic` 等 Action/realize 保持事件、通知和动态效果；不得对 already learned 重复通知或发布 |
| `qq_music_credential_refresh` | 每 21600 秒；启动时立即执行；仅在存在学歌任务时注册 | 对各学歌任务实际使用的凭据文件按规范化路径去重并检查/刷新；没有已初始化凭据时 skipped；任一角色失败时返回 failure 和角色列表；全部可用时返回成功计数 | 纯机械 world 基础设施维护，不产生 Stimulus、不调用 Agent；结果只影响之后学歌任务能否运行 |
| `bili_event_update:{character_id}` | 每 21600 秒；启动时立即执行；按已配置 UID 的角色注册 | 检查并刷新 B 站 cookie，拉取尚未处理的官方动态；有图片且 VLM 可用时用 VLM，否则用 LLM/规则解析为事件；规范化 event type/source/recurrence/personal 后 add/upsert 到 EventStore，并报告 raw/parsed/updated 计数。无新动态为零计数，cookie 无效明确失败 | 抓取、图片解析和 EventStore 更新是 world 事实维护，不直接触发角色回复，也不调用 Agent；这些 event 以后达到提醒条件时，才由主动提醒链形成 `ProactivePromptDue` |
| `proactive_topic_check` | 每 300 秒；启动时不立即执行 | 遍历当前活跃聊天流；只有空闲至少 30 秒的流才检查提醒。按角色查询 due event，过滤 personal 用户和已通知项；每个流从候选中随机选一项，原子 claim 后加入强制主动话题；入队失败/取消释放 claim，成功后同一触发键不重复派发 | clock 只唤醒提醒扫描；ChatStage 拥有活跃/空闲和通知 claim，构造 `ProactivePromptDue` 调 handle；Agent 决定表达并由 realize 输出。world task 不再调用 `ProactiveTopicMaker`/`TopicReplier` |
| `dynamic_interaction` | 每 600 秒；启动时不立即执行；当前为默认角色一份 | 回复 LLM 可用时，每轮最多处理 10 条待回复动态正文和 20 条待回复评论：正文生成并发布评论，评论先决定 reply/ignore，再更新 replied/ignored/failed；无论回复 LLM 是否可用，另各取最多 10/20 条待记忆正文/评论，写入或忽略 Agent 记忆，更新 memory 状态并记录观测事件 | world 只选择和规范化 pending dynamic/comment 为 `DynamicObserved`；WorldStage 调 handle。回复决定形成 `ReplyDynamic` 并经 realize，记忆在 Agent 内部幂等提交；执行 receipt 再驱动原记录的 replied/ignored/failed 与 memory 状态，不能直接调用 `CharacterRuntime` 或 AgentRuntime 记忆代理 |
| `diary:{character_id}` | 每日 00:00；每个启用角色 | 按服务器当日统计该角色每个用户的 Conversation；至少 50 条且当天尚无已发布 diary 动态才入选，超过 20 人时随机取 20 人。收集角色 persona/style 和用户材料，逐个生成并以 private Agent dynamic 发布，不建立独立日记表；逐用户统计 created/failed。LLM capability 不可用时整轮 skipped | 用户筛选、阈值、每日去重和上限属于 world；为每个入选用户产生 `DiaryPlanningDue`，经 WorldStage/handle 决定日记内容，再由 `WriteDiary`/realize 保持 private dynamic、source identity 和一次性发布语义；world 不直接取得 diary capability |
| `purge_expired_events` | 每日 00:00；全局一份 | 把已过期、非 recurring、非 `source=user` 的 active event 标成 inactive：有 end 时 `end_date < today`，只有 start 时保留一天缓冲后过期；只有 `date_mmdd` 的事件不清理。提交后失效 due-event cache，并返回 purged 数 | 纯 EventStore 维护，不产生 Stimulus、不调用 Agent；必须保留 recurring、用户个人事件和无年份日期的规则 |

上述清单只覆盖实际注册到 `WorldClock` 的 action。`WorldRuntime` 启动时异步执行的 `ensure_holidays()` 不是 clock action，不混入本表；若未来把它注册进 clock，必须先更新本节。

所有 clock action 还必须共同满足：

- 单个 action 抛错只记录该次失败，不终止其他 action 或自己的后续周期；
- 同名注册按 `WorldClock` 当前语义替换旧注册，不产生两个并行循环；
- `run_immediately` 只影响 interval action 首次执行，不改变后续间隔；
- shutdown 停止新一轮并取消/等待已拥有任务，不能把仍未停止的同步任务静默当作关闭成功；
- 迁移验收时从实际 `WorldRuntime.tasks` 和生效配置重新导出注册列表，与本表逐项核对；新增、删除或改变调度/效果必须先修改 spec，不能作为本重构的顺便变化。

### 8.7 验收证据要求

后续测试专题需要为 A1—A9 和四类功能链分别选择 interface 级、跨模块集成或少量端到端证据。本轮先锁定以下最低证据形态，不锁定测试文件名、Fake 结构或 PR 切片：

- 一份生产调用图或自动依赖扫描，证明没有 Agent 内部类型、AgentRuntime 业务代理、`CharacterRuntime` 或绕过 realize 的角色表达 capability 外部生产调用；
- 从公开两个 interface 观察零计划、单计划、多计划、取消、旧 revision 拒绝、部分执行和失败停止；
- 从聊天入口观察 8.3 的所有信号、普通超时和重新思考，不通过私有 Handler 测试替代；
- 从触摸与登录入口观察预制音频、表情、持久化/非持久化、合并与通知去重；
- 从可控时钟逐项触发 8.6 的九类 action，核对外部效果以及纯机械/角色认知边界；
- 对仍需真实网络、LLM、TTS、唱歌模型或设备的部分单独记录人工/环境验收，不能用 Fake 通过宣称真实依赖已验证。

## 9. 工单执行与测试约定

本节与第 10 节把第 8 节验收结果拆成可交给独立开发者或 AI 的 tracer-bullet 工单。工单是实现顺序和交付边界，不改变第 5—8 节的 interface 与行为。每张工单必须在一个新的上下文窗口内可理解、可验证并形成一个聚焦 PR；如果实际实现明显超过单个上下文或约 500 行手写代码，执行者必须先提出进一步拆分，不能自行扩大。

### 9.1 不确定时的判断顺序

执行任何工单时，按以下优先级判断：

1. **本 SPEC 是规范来源。** 工单标题、摘要或当前代码与 SPEC 冲突时，以 SPEC 为准；不得自行增加第三个 Agent 业务接口、任意 payload、Stimulus/Action kind 或未定义 fallback；
2. **当前生产行为是兼容基线。** 只有 SPEC 没有规定实现细节时，才查看开始工单时分支上的生产代码、生效配置、已有测试和持久数据约束。当前行为用于补足细节，不能推翻 SPEC 已明确的边界；
3. **开发守则决定开发方式。** 遵守 spec-first、从公开 interface 观察、TDD、隔离外部依赖、小 PR、进度同步和真实环境证据规则；
4. 如果三者仍不能唯一确定行为，或实现要求扩大公开 interface，执行者停止该工单，记录具体缺口并先提交 SPEC 修订评审，不能靠猜测继续。

工单开始时还必须以最新目标分支重新确认依赖工单已经合入，或存在本节允许的、父层已获批准的堆叠交付链。文件中的 blocker 表示“未完成就不能安全开始”的真实阻塞边，不表示建议阅读顺序。

### 9.2 每张实现工单的交付格式

- 一个工单对应一个目标分支上的小 PR，只交付 `What to build` 中的一条纵向行为或明确标记的 expand/contract 步骤；
- 先从 SPEC 指定的公开 interface 写一个会因目标行为缺失而失败的测试，记录 Red 命令和失败原因，再写最小实现并记录 Green；既有实现使新回归测试首次即通过时，必须写“补回归测试、无 Red 证据”，不能破坏代码制造失败；
- 测试归属由观察 seam 决定：单模块行为进入对应模块测试，跨模块真实连接进入 integration，只有必须从外部协议入口才能证明时才使用少量 e2e；只在供应商、网络、时钟、文件系统和数据库等最外层 seam 使用 Fake；
- PR 必须更新本功能开发进度，说明对应 SPEC 条款、明确不包含内容、实际测试命令与结果、未验证的网络/LLM/TTS/GPU/设备/生产风险；
- 不允许在迁移工单中提前删除仍有调用者的旧入口。旧路径的最终删除只在 29 号 contract 工单进行；
- 不允许因 blocker 尚未完成而在本工单内顺便实现 blocker。除 9.2.1 定义的、父层已获批准且可追溯的合法堆叠链外，应等待或从共同目标分支取得已合并结果。

#### 9.2.1 本重构的堆叠 PR 规则

本重构的最终集成分支固定为 `refactor/agent`，但“每个 PR 的直接 base 都必须是 `refactor/agent`”不是要求。为了让 Red seam 在实现前独立评审，可以使用一层或多层堆叠 PR：

```text
refactor/agent
  └─ 根 PR：已确认的 Red seam 或当前完整候选
       └─ 子 PR：相对父 PR 的最小 Green 或下一门禁增量
```

- 根 PR 的 base 必须是 `refactor/agent`；子 PR 的 base 可以是同仓库直接父 PR 的 head 分支，但父链必须无环且最终回到该根 PR；
- 每一层必须明确关联同一工单或具有已记录 blocker 关系的工单，并在 PR 正文写出父 PR、根 PR、最终集成分支和本层只增加的内容；
- 子 PR 以父 PR 为 fixed point 做流程、黑盒、Standards 和 Spec 审查，通过后只 squash merge 到父分支；不得把子 PR 误合入 `dev`、`master` 或绕过父层直接落地；
- 父 PR 吸收子 PR 后不再是原来的 Red-only 候选。作者必须更新 PR 标题、正文、本功能进度和验证结果，并把父 PR 的新 head 作为完整 Green 候选重新审核；任何旧 head 批准都不能直接授权最终合并；
- 只有根 PR 对 `refactor/agent` 的完整 diff、提交顺序、相关离线测试和两轴审查全部通过后，根 PR 才能转为最终可合并状态并 squash merge。

Draft/Ready 只表达作者是否请求审核：Red-only 门禁保持 Draft；子 PR 完成自检后由作者转 Ready；审核者使用 Approve/Request changes 表达结论。子 PR 被批准或合入父分支都不表示功能已进入 `refactor/agent`。

自动和人工黑盒审查默认只运行工单 focused tests、受影响模块离线回归和必要静态检查。真实学歌流水线、B 站实时抓取以及 `slow/live/external/real_llm` 测试默认跳过并逐项记录为未验证；不能为了全量统计启动长耗时外部过程，也不能把跳过写成通过。

### 9.3 Expand–migrate–contract

本重构是 wide refactor，采用以下顺序保持每个中间 PR 可运行：

```text
01—06  expand：增加强类型协议、façade、handle/realize 内核
07—28  migrate：按可观察链路迁移调用方，并保护纯机械 world task
29      contract：所有迁移完成后删除旧业务入口和旁路
30      accept：从公开入口做集成验收并同步最终文档
```

expand 阶段允许目标 interface 与旧实现暂时并存，但新调用方不得使用旧入口；migrate 阶段必须按输入/任务种类保证单一路径，不能让同一刺激被新旧链重复处理；contract 阶段不得保留无生产调用者的兼容转发。

## 10. 工单拆分与依赖

下面的 Markdown 底稿位于 `.scratch/agent-handle-realize/issues/`。每个文件都包含来源优先级、范围、验收、验证、明确不包含和交接要求，并记录对应 GitHub Issue。用户已确认粒度与 blocker，30 个工单已一对一发布为 [#60](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/60) 至 [#89](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/89)：本地编号 `NN` 对应 Issue `#(NN + 59)`，Issue 正文中的 Blocked by 使用真实 Issue 编号。所有 Issue 均已应用 `ready-for-agent` 标签，并在正文中保留同名状态，供开发协作和自动化筛选使用。

| 工单 | Blocked by | 独立交付结果 |
| --- | --- | --- |
| [01 handle 输入与结算领域契约](../../../.scratch/agent-handle-realize/issues/01-handle-domain-contract.md) | 无 | expand：Stimulus、InteractionSnapshot、request、HandlingReport 的完整强类型协议 |
| [02 计划与 realization 领域契约](../../../.scratch/agent-handle-realize/issues/02-realization-domain-contract.md) | 01 | expand：ActionPlan、两个 sink/receipt、Action、ExecutionContext、AgentOutput、ExecutionReport 的完整强类型协议 |
| [03 冻结 WorldClock 基线](../../../.scratch/agent-handle-realize/issues/03-freeze-world-clock-baseline.md) | 无 | 九类注册、配置调度、错误隔离、同名替换与 shutdown 的回归证据 |
| [04 两接口 Agent façade 与路由](../../../.scratch/agent-handle-realize/issues/04-agent-facade-and-routing.md) | 01、02 | `get_agent` 返回仅暴露两个业务方法的 façade，建立唯一 Handler 路由和稳定失败面 |
| [05 handle 请求核心](../../../.scratch/agent-handle-realize/issues/05-handle-request-core.md) | 04 | 单次处理、PlanEmitter、InteractionContextStore 和逐 ID report |
| [06 realization 执行核心](../../../.scratch/agent-handle-realize/issues/06-realization-execution-core.md) | 04 | 有序执行、Say/预制音频/表情输出和失败停止 |
| [07 Chat 协调信号桥](../../../.scratch/agent-handle-realize/issues/07-chat-coordination-stage-bridge.md) | 05、06 | ChatStage 新 façade 桥及 typing/image-selection open/close 等待结算 |
| [08 文字聊天与超时](../../../.scratch/agent-handle-realize/issues/08-chat-text-and-timeout.md) | 07 | 文本从 Adapter 到 Agent 输出的完整链、普通聚合期限、强制 timeout 和 Say/Sing |
| [09 图片与非 Realtime 语音](../../../.scratch/agent-handle-realize/issues/09-chat-multimodal-input.md) | 08 | Image/Voice 的受控媒体、内部理解 Skill 和混合 pending |
| [10 聊天失效与部分结算](../../../.scratch/agent-handle-realize/issues/10-chat-invalidation-and-settlement.md) | 07、08、09 | 旧判断取消、迟到 plan/report 拒绝、重新思考和逐 ID 部分消费 |
| [11 慢 Recall 与多个计划](../../../.scratch/agent-handle-realize/issues/11-slow-recall-and-multi-plan.md) | 05、06、08、10 | 临时/正式完整计划、ordinal、Recall 续程、取消和请求恢复 |
| [12 显式记忆](../../../.scratch/agent-handle-realize/issues/12-intentional-memory.md) | 05、08 | IntentionalMemoryCommit 先写后承诺、实际提交结果和失败报告 |
| [13 settlement 反思](../../../.scratch/agent-handle-realize/issues/13-reflection-settlement-and-memory.md) | 05、06、08、12 | Coordinator/Policy/Handler 可靠调度自动记忆和重要日期检查 |
| [14 压缩与画像反思](../../../.scratch/agent-handle-realize/issues/14-reflection-compaction-and-profile.md) | 13 | 上下文阈值/CAS、画像更新和 ChatStage ReflectionWorker 退出 |
| [15 触摸反应](../../../.scratch/agent-handle-realize/issues/15-touch-reaction.md) | 05、06、07 | 快速预制音频/表情、瞬时非持久输出、失败回退和触摸合流 |
| [16 首次登录欢迎](../../../.scratch/agent-handle-realize/issues/16-first-login-proactive.md) | 05、06、07 | 两条有序持久欢迎、预制音频、历史同步时点和登录去重 |
| [17 到期事件主动提醒](../../../.scratch/agent-handle-realize/issues/17-due-event-proactive.md) | 03、08、16 | 当天登录与 300 秒周期提醒的过滤、claim、合并/随机选择及失败释放 |
| [18 ToyStage](../../../.scratch/agent-handle-realize/issues/18-toy-stage.md) | 05、06 | 设备连接/断开、聚合振动、Touch 与 PerformMotion 的完整 Toy 链 |
| [19 WorldStage 核心](../../../.scratch/agent-handle-realize/issues/19-world-stage-core.md) | 03、05、06 | 长期人格—箱庭 interaction、world 事实投递、pending/revision 和输出路由 |
| [20 世界活动与日程](../../../.scratch/agent-handle-realize/issues/20-world-activity-planning.md) | 18、19 | DailyPlanning/Activity 生命周期及 Schedule/Transition/Motion Action |
| [21 citywalk](../../../.scratch/agent-handle-realize/issues/21-citywalk-chain.md) | 19 | 04:00/概率、环境报告、travel event 与经 Agent 的动态发布 |
| [22 VCPedia 候选知识](../../../.scratch/agent-handle-realize/issues/22-song-knowledge-discovery.md) | 05、19 | 抓取候选 Stimulus、Agent 接纳、知识/关键词索引幂等写入 |
| [23 学歌生命周期](../../../.scratch/agent-handle-realize/issues/23-song-learning-lifecycle.md) | 06、19、21、22 | RequestSongLearning、机械任务、SongLearned、经验/event/通知/动态结算 |
| [24 动态互动](../../../.scratch/agent-handle-realize/issues/24-dynamic-interaction.md) | 05、06、19 | DynamicObserved、reply/ignore、ReplyDynamic 和内部记忆状态 |
| [25 日记](../../../.scratch/agent-handle-realize/issues/25-diary.md) | 05、06、19 | 00:00 筛选、DiaryPlanningDue、WriteDiary 与 private dynamic 去重 |
| [26 QQ 凭据刷新](../../../.scratch/agent-handle-realize/issues/26-qq-credential-refresh.md) | 03 | 6 小时立即运行、凭据路径去重和纯机械边界回归 |
| [27 B 站事件同步](../../../.scratch/agent-handle-realize/issues/27-bili-event-update.md) | 03 | 6 小时立即运行、抓取/模型解析/EventStore upsert 和纯 world 边界 |
| [28 过期事件清理](../../../.scratch/agent-handle-realize/issues/28-expired-event-cleanup.md) | 03 | 00:00 失活规则、缓存一致性和纯 EventStore 边界 |
| [29 删除旧入口与旁路](../../../.scratch/agent-handle-realize/issues/29-contract-old-agent-paths.md) | 07—25 全部迁移工单 | contract：删除旧代理、内部类型外泄、直接 capability 路径并通过依赖扫描 |
| [30 集成验收](../../../.scratch/agent-handle-realize/issues/30-integrated-acceptance.md) | 26、27、28、29 | 从公开入口证明 A1—A9、全部用户链路和九类 clock action，更新最终文档 |

可立即开始的 frontier 只有 01 和 03。02 必须等待 01；04 必须等待 01/02；05 与 06 在 04 完成后可以并行。进入迁移阶段后，Chat、Toy、World 和三个纯机械 world task 可以沿各自 blocker 并行，但所有结果必须合入同一功能集成分支后再开始 29。

## 11. Out of Scope

- 本轮不实现 Agent façade、Handler、Skill、上下文存储、ReflectionCoordinator 或领域类型；
- 不修改产品代码、测试、客户端、WebSocket 或设备协议；
- 不设计或实现 Call、Realtime、通话打断、`CallInteractionSnapshot` 和原 5.5 相邻接口；
- 不实现 `UserJoinedActivity`、`ActivityInterrupted`，也不为尚不存在的事件预留处理链；
- 不一次迁移聊天、world 和玩偶调用方；
- 不建立 BaseStage、通用 base 模块或任意 capability 调用协议；
- 不保证旧 `LuoTianyiAgent`、ReflectionWorker 或 AgentRuntime 业务代理继续作为目标 interface；
- 不在没有真实替换需求的位置预建 port；
- 本轮只完成 SPEC、可版本化工单底稿及 GitHub Issue 维护，不执行工单、不写测试或产品实现；
- 不把本地静态设计视为真实模型、设备或生产环境验收。

## 12. Further Notes

### 12.1 设计优先级

发生冲突时依次遵守：用户在本轮确认的设计约束、本 interface spec、对应 PRD、项目架构和当前兼容实现。当前代码只能证明迁移起点，不能反向扩大目标 interface。

相较 PRD 中“长期记忆和画像写入统一进入 ActionPlan”的宽泛表述，本 spec 作出更窄约定：Agent 自有数据写入留在 Agent 内；只有需要输出或外部生命周期结算的行动进入 ActionPlan。自动的事后认知维护由内部 Reflection 完成。

### 12.2 当前实现与目标设计的已知差异

当前聊天域已有 `USER_TYPING`、`USER_IMAGE_SELECTING`、`USER_IMAGE_SELECTING_CANCEL`：非空打字延长等待，空输入唤醒重评；打开图片选择延长等待，取消选择恢复普通等待；这些信号也会使正在进行的旧话题判断失效。本 spec 将该行为提升为强类型协调刺激，但没有声称目标 Agent interface 已实现。

当前 `WorldRuntime` 同时创建 world task、持有 `WorldClock` 并向 task 派发系统依赖；`WorldClock` 直接定时调用 task。目标设计保留这种实现作为迁移起点，但在语义上拆分为：world 定义和产生外部事实，world_clock 只负责到期唤醒，WorldStage 负责人格与箱庭的持续交互及 pending 结算。

当前歌曲抓取任务会在 world 任务内部抓取并直接写 Song 数据，当前学歌任务也会直接记录事件、刷新媒体库、打标签和发布动态。目标设计要求逐步拆成“机械外部过程 → 稳定 Stimulus → Agent 接纳/决策 → 内部状态或 Action”，但本轮不实施迁移。

### 12.3 评审必须能直接回答

1. world、world_clock 和 WorldStage 分别拥有什么状态，哪一层可以调用 Agent？
2. world 领域定时和 WorldStage 交互定时为什么走不同路径？
3. `plan_sink` 是什么类型，为什么 Handler 不直接持有它？
4. PlanEmitter 如何把 draft 变成稳定计划，为什么它只检查 cancellation、不读取 stage 当前 revision？
5. InteractionContextStore 保存什么，为什么不能保存 stage pending 或长期画像？
6. 处理或投递失败后，哪些结果保留，哪些后续行动停止？为什么不能依靠重投恢复？
7. 上下文过长时，settlement notice、ReflectionPolicy、业务存储和 ReflectionHandler 各自做什么？
8. `UserTyping` 被处理完成但 pending 全部保留时，HandlingReport 如何表达？
9. `InteractionDeadline` 被处理完成并消费全部 snapshot pending 时，为什么仍按 ID 结算而不是 `consume_all`？
10. `interaction_revision`、`activity_revision`、`schedule_revision` 分别由谁拥有和校验？
11. 打断的决定、即时通道控制、Agent 协作取消和迟到计划拒绝分别发生在哪里？
12. 每个 Stimulus 和 Action 的含义、字段类型与字段用途是否能仅从表格读出？
13. 为什么 `ChangeExpression` 不是独立 Action，而 `Say`/`Sing` 仍能同时改变表情？
14. 为什么当前触摸反馈不需要 `HAPTIC` 输出？
15. 为什么三类记忆/知识写入留在 Agent 内，而 `RequestSongLearning` 仍要经过 realize？
16. 哪些抓取/模型过程在 Agent 外，哪一刻才形成 `SongKnowledgeDiscovered` 或 `SongLearned`？
17. 当前版本明确不设计哪些 Call/Realtime/活动事件？
18. 01—30 的粒度是否都能在一个新上下文和一个聚焦 PR 中完成，哪些仍需拆分或合并？
19. 每条 Blocked by 是否真正在接口、行为或共享实现上阻止后续工单，而不是仅表示推荐顺序？
20. 01/03 的初始 frontier 以及 Chat、Toy、World、纯机械 world task 的并行边界是否符合团队协作方式？
21. 外部调用方怎样通过强类型变体提供 `kind` 并显式填写 `source`，scheduler 和 `world_clock` 为什么只负责触发/投递且不得覆盖来源？
22. 为什么目标 Stimulus interface 不包含 `PersistPolicy`，Agent 怎样在内部做幂等持久化判断，reviewer 又为什么不能要求没有真实失败依据的跨字段组合矩阵？

如果必须阅读内部实现才能回答这些问题，本 spec 仍不够清楚，不能进入后续测试与工单讨论。
