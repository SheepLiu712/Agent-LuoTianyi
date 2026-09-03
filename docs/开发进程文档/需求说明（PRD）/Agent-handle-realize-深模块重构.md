# Agent `handle_stimulus / realize_action_plan` 深模块重构 PRD

> 状态：待评审
>
> 日期：2026-09-03
>
> 范围：`server` 内部 Agent 的长期稳定职责、调用场景与两个公开 interface
>
> 本文细化并替代旧版 Agent `plan / act` PRD。服务端总体架构中的 `Stimulus`、多角色、记忆正本和外部协议兼容方向保持不变。

## 1. 背景

Agent 是项目中负责角色理解、选择、表达和行动的核心模块。未来虽然会增加电话、玩偶和箱庭世界，但这些变化不应迫使调用方理解潜意识、提示词、模型、记忆或能力执行的内部步骤。

当前实现已经存在以下问题：

- stage 分别调用预处理、话题提取、回复规划、回复实现、语音和唱歌；
- world 任务直接取得 CharacterRuntime、潜意识、数据库或具体能力；
- `UnreadMessage`、`ExtractedTopic`、`OneSentenceChat` 等内部类型泄漏给调用方；
- 交互计时、认知决策、能力执行和持久化副作用混在同一流水线；
- Agent 是每角色一个共享实例，但当前接口没有明确不同用户、通话和 world 活动的状态作用域。

本次重构要把 Agent 固定为一个深模块。外部只需要知道如何把一次逻辑刺激交给 Agent，以及如何执行 Agent 已经生成的行动计划。

## 2. 目标

1. Agent 对外只提供两个业务 interface：

   ```python
   await agent.handle_stimulus(request, action_plan_sink)
   await agent.realize_action_plan(plan, execution_context, output_sink)
   ```

2. Agent 内部组合 `subconscious`（潜意识）与 `capabilities`（能力），调用方不能绕过 Agent 自行编排。
3. 聊天、电话、玩偶和角色自主活动可以使用不同的 stage 实现和状态机，但都通过同一组 Agent interface 处理角色认知，并遵守共同的计划接收与结算约定。
4. “回想起什么记忆”及“回想已经完成”都保留为 Agent 内部过程，不伪装成新的 Stimulus，也不要求 stage 回灌 Agent。
5. Agent 可以安全处理不同用户、不同通话、不同设备和角色自身活动的上下文，不在 Agent 实例字段中保存一个简单的 `user_id -> context` 字典。
6. 支持当前聊天和可预见的扩展：每日活动规划、活动中接受刺激、电话、玩偶、主动话题、日记和动态。
7. 一次刺激处理期间可以依次产生零到多个完整、可审计、可重试的 ActionPlan；执行过程可流式输出、取消并报告部分失败。
8. 新刺激和新行动可以通过增加内部处理器和强类型领域对象扩展，不增加新的 Agent 公开方法。
9. Realtime 电话把连续媒体传输和角色认知分开：CallStage 管理媒体流与通话生命周期，Agent 内部控制决定角色回复内容的 Realtime turn。
10. 采用小 PR 逐条迁移调用路径；重构完成时，所有需要角色理解、选择、表达或记忆的调用方都只经过 Agent 门面。

## 3. 非目标

本 PRD 不要求：

- 立即实现电话、玩偶或完整箱庭；
- 在单个 PR 中一次性迁移所有旧聊天和 world 路径；
- 修改现有客户端协议；
- 把每个音频帧、传感器采样或供应商事件包装成 Stimulus 交给 Agent；
- 让聊天、电话、玩偶和角色自主活动继承同一个 `BaseStage` 或共用同一套状态机；
- 提前创建通用 `base` 模块；
- 在本 PR 中编写产品代码或测试；
- 允许 Agent 负责连接、重连、音频设备、GPU 队列等基础设施生命周期。

“不在单个 PR 中迁移”只是 PR 切片约束，不是最终架构允许永久双轨。迁移结束前可以暂时保留未迁移调用方；每迁移一条路径，就必须删除该调用方对 Agent 内部类型、AgentRuntime 业务代理、subconscious、capabilities 或数据库的直接依赖。全部目标路径迁移并删除旧入口后，本重构才算完成。

## 4. 核心术语

### 4.1 逻辑刺激（Stimulus）

一次对角色有意义的输入，例如完整文字消息、完整语音消息、一次有效触摸、通话开始、活动开始或计划时间到达。

原始音频帧和高频传感器采样不是逻辑刺激。它们必须先由 Adapter 或 stage 聚合、去抖和校验。

### 4.2 交互（Interaction）

一段具有共同上下文和生命周期的持续过程，例如一次聊天流、一通电话、一次玩偶会话或角色自主规划和执行的一段 world 活动。每段交互有独立的 `interaction_id`；它可以关联某个用户，也可以只属于角色自身。

### 4.3 stage

负责一类 Interaction 的流程管理角色。`ChatStage`、`CallStage`、`ToyStage` 和 `CharacterActivityStage` 可以拥有不同的实例作用域、状态机、上下文、超时、媒体和恢复规则；`stage` 不是要求它们共用一个类的名称。

### 4.4 Realtime 媒体输入（Realtime Media Ingress）

电话等实时交互中的连续音频帧输入。它属于交互传输，不是 Stimulus；CallStage 通过供应商无关的窄 interface 把音频送入 Realtime Adapter，而不理解 Qwen 等供应商协议。

### 4.5 认知处理过程（Handling Process）

从 `handle_stimulus` 开始处理一个或一组 pending stimuli，到它返回最终 `HandlingReport` 为止的过程。这个过程可以等待 Agent 内部的 Recall、模型或只读能力，并在运行期间依次产生零到多个 ActionPlan。

认知处理过程尚未结束，不表示某个 ActionPlan 只完成了一半。每个已经输出的 ActionPlan 都必须能够独立实现。

### 4.6 处理报告（HandlingReport）

`handle_stimulus` 结束时返回的结果，说明本次认知处理是已经完成、需要等待外部条件、被取消还是失败。ActionPlan 不放在这个返回值里，而是在处理期间通过 `ActionPlanSink` 输出。

### 4.7 行动计划（ActionPlan）

Agent 对“准备做什么”的不可变描述。一个计划可以包含说话、唱歌、改变状态、写记忆、发布动态或创建日程等多个有序行动。

一句“让我想想……”和稍后得到的正式回复是两个各自完整的 ActionPlan；不能建立一个“尚未说完、以后继续填写”的可变计划。

### 4.8 行动实现（Realization）

把计划转成真实结果的过程，例如 TTS、音频分片、唱歌、数据库写入、发布动态和创建日程。实现不能擅自改变计划的语义。

### 4.9 回想（Recall）

Agent 根据当前刺激和上下文检索出相关记忆的内部认知过程。回想结果只参与当前决策或进入 Agent 自己的交互认知上下文，不返回给 stage。

`RecallCompleted` 不是逻辑刺激。Recall 的完成以 Agent 内部 future、回调或普通返回值表示，由仍在运行的 `handle_stimulus` 继续使用。

## 5. 目标架构

```text
外部协议 / device / world / system
                 |
              Adapter
                 |
         强类型逻辑 Stimulus
                 |
      对应的 stage / one-shot runner
  Chat / Call / Toy / CharacterActivity
 排队、pending、截止时间、打断、重连、背压
                 |
      agent_runtime.get_agent(character_id)
                 |
       Agent.handle_stimulus(request, sink)
                 |
      +----------+-----------+
      |                      |
 Agent 本体              subconscious
 注意力、决策、         记忆、画像、关系、
 角色化内容、计划       知识、认知上下文、状态
      |                      |
      +----------+-----------+
                 |
       capabilities（只读感知）
                 |
        +--------+---------+
        |                  |
 sink.emit              return
 0..N 个完整            HandlingReport
 ActionPlan             CONSUMED / DEFERRED /
        |               CANCELLED / FAILED
        v                  |
  stage 计划队列           stage 结算刺激
        |
 Agent.realize_action_plan(..., output_sink)
        |
 capabilities（执行）
        |
 输出、写入、发布、日程、设备动作
        |
 stage -> Adapter -> 外部通道
```

### 5.1 Agent 本体

Agent 本体是公开外壳和认知编排者，负责：

- 根据刺激和上下文决定等待、忽略还是行动；
- 在内部选择与调用潜意识和只读能力；
- 在电话等实时场景中，通过内部 `RealtimeTurnPort` 使用当前交互的认知会话，不把供应商回复交给 stage 解释；
- 在一次认知处理过程中生成零到多个结构化、角色化且可独立执行的行动计划；
- 在内部等待 Recall 等异步结果并继续当前处理，不把内部完成事件回灌给公开 interface；
- 保证计划执行时不被重新解释；
- 将内部错误转成稳定、可观测的处理或执行结果。

现有 MainChat、prompt assembly、response parser 和 response realizer 可以作为内部实现继续存在，但不能再成为 stage 的依赖。

### 5.2 subconscious

潜意识负责：

- 语义预处理、话题归纳和注意力候选；
- 长期记忆、用户画像、关系、日期、歌曲知识和角色状态；
- 按 `interaction_id` 管理 Agent 私有的短期认知上下文；
- 向 Agent 本体提供当前决策需要的事实；
- 执行计划中已经明确的记忆、画像和角色状态写入。

### 5.3 capabilities

能力负责“怎么完成已经决定的事情”，包括：

- 供 `handle_stimulus` 使用的只读感知能力，例如图片理解、ASR、歌曲可用性和事实查询；
- 供 `realize_action_plan` 使用的执行能力，例如 TTS、唱歌、Live2D、设备动作、动态发布、日记发布和日程写入。

能力不决定角色是否行动、内容说什么或为什么写入记忆。

### 5.4 AgentRuntime

`AgentRuntime` 只负责创建、装配、查找、缓存和关闭角色 Agent：

```python
agent = agent_runtime.get_agent(character_id)
```

未知角色明确失败。AgentRuntime 不再增加 `extract_topic`、`write_memory`、`tts_say` 等业务代理方法。

### 5.5 stage 家族

stage 是交互流程管理职责，不是单例、统一类或统一状态机。目标实现至少允许：

| 实现角色 | 实例作用域 | 自己负责的特殊规则 |
|---|---|---|
| `ChatStage` | 每个 `(character_id, user_id)` 一份 | 消息聚合、2 秒等待、聊天重连和用户对话上下文 |
| `CallStage` | 每个 `call_id` 一份 | 连续音频、VAD 控制信号、实时打断、播放 ACK 和电话重连 |
| `ToyStage` | 每个设备交互或连续接触过程一份 | 振动去抖、设备在线状态和硬件输出限制 |
| `CharacterActivityStage` | 每个 `(character_id, activity_id)` 或角色规划周期一份 | 无用户的角色上下文、活动状态、日程和跨进程恢复 |

一个没有持续状态的 world 刺激不必创建长期 stage 对象，可以由只完成一次协调的 runner 调用同一组 Agent interface。暂不建立 `BaseStage`；只有多个真实实现出现相同协调代码时，才提取很小的公共 runner。

每个 stage 实现都负责交互流程，而不是角色心智：

- 按交互排序和保存 pending stimuli；
- 维护截止时间、播放、打断、取消、重连和背压；
- 调用 Agent 两个 interface；
- 向 `handle_stimulus` 提供只负责接收计划的 `ActionPlanSink`；
- 按计划输出顺序排队执行，并预留、提交或释放刺激；
- 转发通道无关输出并保存实际对话记录。

stage 不读取 Recall、不修改 ActionPlan，也不直接调用角色能力。共同的是调用 Agent、接收计划和结算结果的约定；排队、上下文、超时、媒体、取消和恢复策略可以不同。

### 5.6 Realtime 会话的两个内部 seam

电话需要持续向同一个供应商会话发送音频，同时又必须保证供应商模型的语义回复仍属于 Agent 的认知过程。同一个 Realtime Adapter 会话因此对不同调用方提供两个窄 interface：

```python
class RealtimeMediaIngress(Protocol):
    async def append_audio(self, frame: AudioFrame) -> None: ...
    async def close_input(self) -> None: ...


class RealtimeTurnPort(Protocol):
    async def configure(self, session_ref: RealtimeSessionRef, context: RealtimeContext) -> None: ...
    def respond(self, session_ref: RealtimeSessionRef, turn_id: str) -> AsyncIterator[RealtimeTurnEvent]: ...
    async def submit_tool_result(self, session_ref: RealtimeSessionRef, call_id: str, result: str) -> None: ...
    async def cancel_response(self, session_ref: RealtimeSessionRef) -> None: ...
```

- CallStage 只得到 `RealtimeMediaIngress`，负责音频顺序、背压、连接关闭和实时控制；
- Agent 只在内部使用注入的 `RealtimeTurnPort`，负责上下文、工具、回复语义和把完整语义片段转换成 ActionPlan；
- 两个 interface 由同一个生产 Realtime Adapter 和一个测试 Fake Adapter 实现，通过供应商无关的 `RealtimeSessionRef` 关联；
- Realtime Adapter 建立会话时绑定 CallStage 的控制事件接收器，只回送 `speech_started`、输入缓冲状态和断线等供应商无关事实；最终用户回合由 Call Adapter 规范化为携带 `turn_id` 及可用转写或媒体引用的 `VoiceUtteranceFinal`；
- `SystemRuntime` 显式创建和注入依赖，不能让 stage 或 Agent 从全局位置查找供应商会话；
- Qwen 原生事件和 WebSocket 都不能进入 Agent 公开 interface。

`RealtimeMediaIngress` 和 `RealtimeTurnPort` 是 Realtime Adapter 的 interface，后者还是 Agent 的内部 seam；它们不是新增的 Agent 业务方法。若目标供应商不能把媒体输入、turn 归属和响应控制映射到这组语义，必须先调整 Realtime Adapter 或重新评审 Agent interface，不能让 CallStage 直接接管角色回复。

`RealtimeTurnPort.respond` 本身不能向客户端通道发送任何内容。handle 只有在得到一个完整、不可变的语义动作后才能 emit ActionPlan。若供应商把语义生成和音频生成强绑定，Adapter 要么把音频暂存为供应商无关的 `PreparedMediaRef`，由计划在 realization 阶段输出；要么把供应商配置为只返回结构化语义，再由普通 TTS 实现。若两者都做不到，就说明该供应商能力不能在不破坏两个 Agent interface 的前提下接入，必须先重新评审，而不能让音频在 handle 期间绕过计划直接发给用户。

## 6. 需要覆盖的刺激场景

### 6.1 当前场景

| 场景 | 输入给 Agent 的逻辑刺激 | Agent 行为 |
|---|---|---|
| 文字聊天 | `TextMessage` | 理解上下文，等待更多输入或生成回复计划 |
| 图片消息 | `ImageMessage` | 内部调用图片理解，结合文字和记忆决定行动 |
| 完整语音消息 | `VoiceUtteranceFinal` | 使用已有转写或内部 ASR，决定回复 |
| Live2D 触摸 | `TouchInteraction` | 快速忽略或生成短句、表情、动作计划 |
| 登录问候、提醒 | `ProactivePromptDue` | 根据用户和角色状态决定是否主动表达 |
| 新动态、评论 | `DynamicObserved` | 决定是否回复及回复内容 |
| 日记时间到达 | `DiaryPlanningDue` | 决定是否写日记、写什么以及是否发布 |
| citywalk 事件 | `WorldObservation` | 决定角色表达、记忆和后续行动 |
| 发现歌曲知识 | `SongKnowledgeDiscovered` | 决定是否接纳或更新歌曲知识，是否加入待学列表 |
| 学会新歌 | `SongLearned` | 记录角色经历，决定是否告知、发动态、演唱或在后续日记中使用 |

### 6.2 每日活动规划

world clock 在需要规划一天活动时产生 `DailyPlanningDue`：

1. Agent 读取日期、角色状态、已有日程、world 条件和长期计划；
2. Agent 生成一个包含多个 `CreateSchedule` 的 ActionPlan；
3. `realize_action_plan` 将日程写入 scheduler；
4. 每个日程到期时，scheduler 生成新的 `ActivityDue` 刺激；
5. Agent 再决定开始、调整、跳过或替换活动。

日程不是 Agent 实例中的 Python timer，必须是可恢复、可去重的持久调度记录。

### 6.3 活动中接受刺激

活动期间可能收到：

- `ActivityStarted`；
- `ActivityObservation`；
- `UserJoinedActivity`；
- `ActivityInterrupted`；
- `ActivityEnded`；
- 普通聊天、电话或玩偶刺激。

这些刺激可以改变：

- 当前注意力和短期认知上下文；
- 角色状态和活动状态；
- 是否暂停、继续或改变活动；
- 是否形成长期记忆；
- 是否产生说话、动态、日记或新日程。

临时注意力可以在 `handle_stimulus` 内部更新；长期记忆、角色状态和 world 状态必须进入 ActionPlan，由 `realize_action_plan` 幂等提交。

### 6.4 电话

电话至少需要以下逻辑刺激：

| 刺激 | stage 立即负责 | Agent 负责 |
|---|---|---|
| `CallStarted` | 建立通话、音频和取消上下文 | 决定是否问候及问候内容 |
| `UserSpeechStarted` | 立即停止正在播放的回复 | 理解“被打断”，更新注意力和后续策略 |
| `VoiceUtteranceFinal` | 聚合音频并提供最终语音或转写 | 理解完整话语并生成计划 |
| `UserSpeechEnded` | 结束收音阶段、推进通话状态 | 在没有完整话语时决定等待或处理 |
| `CallEnded` | 立即关闭传输和音频资源 | 更新内部上下文，决定是否写记忆；不能再向已关闭通道输出 |

原始音频帧不包装成 Stimulus，也不通过 `handle_stimulus` 逐帧传递。Call Adapter 解析 `/call_ws` 音频包，CallStage 负责序号、背压、断线和生命周期，再通过 `RealtimeMediaIngress` 把帧交给 Realtime Adapter。停止播放也不能等待 Agent 或 LLM 决策。

Realtime Adapter 产生的事件按职责分流：

- `speech_started` 等需要立即控制播放的信号先交给 CallStage，同时可以转换为 `UserSpeechStarted` Stimulus 供 Agent 理解“被打断”；
- ASR 完成后形成 `VoiceUtteranceFinal`；
- 决定角色说什么的回复流、Function Call 和工具结果只通过 Agent 内部的 `RealtimeTurnPort` 使用，CallStage 不解析其角色语义；
- Agent 把供应商输出整理成完整的 ActionPlan，再由正常 realization 和 `AgentOutputSink` 输出。

```text
/call_ws 音频帧
-> Call Adapter
-> CallStage
-> RealtimeMediaIngress
-> Qwen Realtime Adapter
   ├─ speech_started -> CallStage 立即打断 + UserSpeechStarted
   └─ VoiceUtteranceFinal -> Agent.handle_stimulus
                              -> 内部 RealtimeTurnPort
                              -> ActionPlan
                              -> realize_action_plan
                              -> CallAgentOutputSink
                              -> Call Adapter -> /call_ws
```

现有《v0.4.0 电话功能详细设计》中“普通通话回复不进入 Agent”的设计早于本 PRD，与这里确认的长期结构冲突。目标架构以本 PRD 为准：

- CallStage 继续负责原始音频流、实时取消、通话状态和重连，并通过窄媒体 interface 使用 Realtime Adapter；
- Realtime provider 可以同时承担转写、感知和模型生成，但决定角色说什么的 turn 必须由 Agent 内部控制和消费，不能形成第二条独立的角色决策路径；
- 只要模型调用决定角色说什么、是否回应或采取什么行动，它在架构上就属于 `handle_stimulus` 的内部实现，即使同一个供应商会话的音频输入由 CallStage 转发；
- 电话协议和供应商事件仍不得泄漏到 Agent interface。

开始电话实现前，应单独修订电话详细设计和 interface spec；本 PRD 不同时修改那份大范围设计文档。

### 6.5 玩偶

玩偶至少需要：

- `ToyVibration`：包含经过 Adapter 去抖后的强度、持续时间、模式和可用位置信息；
- `VoiceUtteranceFinal`：一条完整语音消息；
- `DeviceConnected` / `DeviceDisconnected`：只在它们具有角色可感知语义时交给 Agent。

高频振动采样、音频分片、蓝牙状态和硬件错误由 Adapter/stage 处理。只有一次有角色含义的事件才成为 Stimulus。

### 6.6 歌曲知识和学歌

VCPedia 抓取与学歌流水线都需要区分“运行数据”和“角色知识”：

| 数据 | 所有者 |
|---|---|
| 抓取游标、原始页面缓存、下载文件、任务状态、失败次数 | world、capability 或 system，不需要 Agent 决策 |
| 规范化歌曲资料是否成为角色知识 | Agent 决定，subconscious 持有 |
| 已经学会歌曲的技术产物和可用性 | singing capability/world 维护 |
| “角色学会了某首歌”的经历、日记和动态 | Agent 决定并通过 ActionPlan 持久化 |

VCPedia 抓取器完成采集和规范化后产生：

```text
SongKnowledgeDiscovered
-> handle 判断新增、更新或忽略
-> ActionPlan[UpsertSongKnowledge, RequestSongLearning?]
-> realize 通过 subconscious 的歌曲知识 interface 幂等写入
```

`SongKnowledgeDiscovered` 至少携带供应商无关的歌曲资料、来源、外部标识或页面版本、抓取时间。VCPedia URL、HTML 和解析器对象不能进入 Stimulus。

学歌流水线确认音频和所需产物可用后产生：

```text
SongLearned
-> handle 形成角色“学会这首歌”的经历
-> ActionPlan[RecordLearnedSong, WriteMemory, PublishDynamic?]
-> realize 幂等写入角色知识和记忆
-> 后续 DiaryPlanningDue 通过 Recall 决定是否写入日记
```

除非产品明确要求学会后立即写日记，否则 `SongLearned` 只写入可供后续回想的经历；日记仍由之后的 `DiaryPlanningDue` 决定。这里的“由 Agent 落库”表示 `realize_action_plan` 调用 subconscious 的窄知识/记忆 interface，不表示 Agent 或 world 直接操作 SQL、Session 或 DatabaseManager。

### 6.7 明确不调用 Agent 的场景

- 身份认证、权限、ACK、连接保活和协议错误；
- 原始音频/传感器采集和供应商协议转换；
- 数据库迁移、备份、索引重建和系统健康检查；
- 歌曲下载、音频切分模型维护、凭据刷新；
- world 原始数据采集、地图请求和纯机械模拟推进；
- 角色注册、配置校验、实例装配和进程启停。

判断标准是：需要角色理解、选择、表达或留下角色状态的事情走 Agent；纯基础设施和机械维护不走 Agent。

## 7. Interface 一：`handle_stimulus`

### 7.1 用途

接收一次新的逻辑刺激和 stage 已拥有的交互快照，在 Agent 内完成理解、回想、决策和结构化内容生成。处理期间可以通过 `ActionPlanSink` 依次输出零到多个完整 ActionPlan；处理结束时返回一个 `HandlingReport`。

这两个输出承担不同职责：

- `ActionPlanSink` 回答“目前已经决定做什么”，使临时回应不必等待慢 Recall；
- `HandlingReport` 回答“这一次认知处理是否已经结束，以及原刺激之后是否还要重新判断”。

建议形态：

```python
class Agent:
    async def handle_stimulus(
        self,
        request: HandleStimulusRequest,
        plans: ActionPlanSink,
    ) -> HandlingReport:
        ...
```

`ActionPlanSink` 是调用方提供的计划输出端口，不是 Agent 的第三个业务 interface。外部仍然只调用 `handle_stimulus` 和 `realize_action_plan`。

### 7.2 输入

```python
@dataclass(frozen=True)
class HandleStimulusRequest:
    request_id: str
    stimulus: Stimulus
    interaction: InteractionSnapshot
    cancellation: CancellationToken
```

`request_id` 用于同一次处理请求的幂等重试。

`cancellation` 允许 stage 在交互关闭、新刺激使旧认知过期或系统停机时取消仍在等待 Recall、模型或只读能力的处理。Agent 必须把取消继续传给内部可取消操作，并且在每次输出计划前重新确认请求仍然有效。

`Stimulus` 至少具有：

- `stimulus_id`；
- 强类型 `kind` 和对应 payload；
- 发生时间；
- 来源；
- 目标角色；
- 相关用户，可为空；
- 持久化策略；
- 是否 ephemeral。

`InteractionSnapshot` 不是一份塞满可空字段的通用字典，而是强类型变体：

```python
InteractionSnapshot = (
    ChatInteractionSnapshot
    | CallInteractionSnapshot
    | ToyInteractionSnapshot
    | CharacterActivitySnapshot
)
```

所有变体只共享 Agent 必须知道的少量事实：

- `interaction_id` 和强类型交互种类；
- `user_id`，角色自主活动时为空；
- 按顺序排列的 pending stimuli；
- 当前时间与时区；
- 当前 stage 能接收的输出类型，例如文字、音频、表情和设备动作；
- 用于拒绝过期计划的交互状态版本。

各变体再携带自己的必要事实：

- Chat：近期对话或摘要、消息聚合状态；
- Call：通话状态、用户是否正在说话、供应商无关的 `realtime_session_ref`；
- Toy：设备可用输出和当前连续接触状态；
- CharacterActivity：角色活动、world 状态和既有日程，不携带某个用户的私有上下文。

`character_id` 不重复放入请求，因为 Agent 已由 `get_agent(character_id)` 确定。请求也不能携带 WebSocket、CallStream、SystemRuntime、CapabilityManager 或任意上下文字典。

### 7.3 计划输出端口

```python
class ActionPlanSink(Protocol):
    async def emit(self, plan: ActionPlan) -> None:
        ...
```

每次 `emit` 都必须满足：

- 输出的是完整、不可变、可独立实现的 ActionPlan，不能稍后再补写内容；
- 同一 `request_id` 下按 `emit` 的先后顺序执行；
- 返回只表示 stage 已接受并排入该交互的计划队列，不表示计划已经实现成功；
- stage 可以通过等待 `emit` 施加背压，Agent 不能无上限地产生计划；
- 交互已关闭、请求已被取代或计划身份不匹配时明确拒绝，不能静默丢弃；
- sink 只入队，不能在 `emit` 调用栈内同步回调 `realize_action_plan`，以免重入 Agent 或形成锁等待。

同一次处理允许输出零到多个计划。例如先输出完整的 `Say("让我想想……")` 计划，在内部 Recall 完成后再输出完整的正式回复计划。前一个计划不是“半成品回复”，后一个计划也不修改前一个计划。

### 7.4 最终处理报告

```python
@dataclass(frozen=True)
class HandlingReport:
    status: HandlingStatus
    resolved_stimulus_ids: tuple[str, ...]
    retained_stimulus_ids: tuple[str, ...]
    emitted_plan_ids: tuple[str, ...]
    reconsider_at: datetime | None
    error_code: str | None
    retryable: bool
```

`status` 为：

- `CONSUMED`：本次认知处理已经完成，不需要基于同一批输入再次判断；
- `DEFERRED`：需要等待 Agent 外部的新信息或时间条件，stage 保留刺激；
- `CANCELLED`：stage 或系统取消了尚未完成的认知处理；
- `FAILED`：认知处理因稳定、可观测的错误结束。

`resolved_stimulus_ids` 表示 Agent 不再需要重新理解的刺激，不等于 stage 此刻就能物理删除它们。`retained_stimulus_ids` 表示以后仍要重新判断的刺激。二者不能重叠。

`emitted_plan_ids` 必须与本次实际成功交给 sink 的计划一致，使 stage 能等待这些计划各自的 `ExecutionReport`。`reconsider_at` 只用于 `DEFERRED`；`error_code` 和 `retryable` 只用于 `FAILED`。

所有输出计划的 `origin_request_id` 必须等于本次 `request_id`，`plan_ordinal` 必须从 0 连续递增；计划引用的 `source_stimulus_ids` 必须来自本次请求可见的 pending stimuli。违反这些约束时 sink 明确拒绝。

#### CONSUMED

如果没有输出计划，stage 可以立即提交 `resolved_stimulus_ids` 已消费。如果已经输出计划，stage 先预留相关刺激，直到本次 handle 已结束并且所有相关计划都有最终 `ExecutionReport`，再按执行结果提交或释放。

#### DEFERRED

只用于信息不足、等待用户继续输入、等待 stage 截止时间或其他 Agent 外部条件。stage 保留刺激，在新刺激到达或 `reconsider_at` 到期时重新调用。

`DEFERRED` 不能同时输出 ActionPlan、产生用户可见输出或长期副作用。如果 Agent 已经启动并仍在等待自己的 Recall，它应保持本次 `handle_stimulus` 存活，而不是返回 `DEFERRED`。

#### CANCELLED / FAILED

报告必须列出取消或失败前已经成功输出的计划。stage 结合这些计划的 `ExecutionReport` 判断是否能够安全重试；只要已经产生可见输出或不可回滚的持久副作用，就不能自动从头重放整次刺激。

### 7.5 内部允许行为

`handle_stimulus` 可以：

- 进行语义预处理；
- 调用图片理解、ASR、检索等无外部副作用能力；
- 回想长期记忆并读取画像、关系、角色状态和 world 上下文；
- 调用 LLM 决定是否行动；
- 对 Call snapshot，通过内部 `RealtimeTurnPort` 配置和使用当前 Realtime turn；
- 生成并依次输出完整的结构化文字、语气、表情、歌曲选择、状态变化和日程意图；
- 启动并等待内部 Recall、模型或只读能力，然后在同一次调用中继续认知处理；
- 更新 Agent 私有的短期注意力和交互认知上下文。

`handle_stimulus` 不可以：

- 向外部通道发送内容；
- 调用 TTS 或生成演唱音频；
- 发布动态、评论或日记；
- 写入长期记忆、持久角色状态、world 状态或日程；
- 操作 stage 的 pending、timer、连接或播放状态；
- 通过 `RealtimeMediaIngress` 发送原始音频，或直接持有供应商 WebSocket；
- 把 Recall 的完成包装成 `RecallCompleted` 等 Stimulus 再调用公开 interface；
- 把未知刺激、非法 payload 或内部错误伪装成 `CONSUMED`。

### 7.6 未知刺激

已知但角色决定不回应的刺激返回无计划的 `CONSUMED`。未知 kind、版本不兼容或非法 payload 属于接口错误，必须失败并记录，不能静默消费。

## 8. Interface 二：`realize_action_plan`

### 8.1 用途

按 ActionPlan 的固定语义执行能力、持久化和流式输出。它解决“怎样完成”，不重新决定“做什么”。

建议形态：

```python
class Agent:
    async def realize_action_plan(
        self,
        plan: ActionPlan,
        context: ExecutionContext,
        output: AgentOutputSink,
    ) -> ExecutionReport:
        ...
```

`AgentOutputSink` 是当前 stage 为一次 realization 提供并绑定到具体 Interaction 的输出端口，不是 Agent 的第三个业务 interface。Agent 只向它写通道无关输出，不知道输出最终走 `/chat_ws`、`/call_ws` 还是设备连接。

### 8.2 输入

```python
@dataclass(frozen=True)
class ExecutionContext:
    execution_id: str
    interaction_id: str
    cancellation: CancellationToken
```

- `execution_id`：同一个计划重试时复用，用于能力执行和持久写入幂等；
- `interaction_id`：必须与计划绑定的交互一致；
- `cancellation`：允许 stage 请求停止长时间 TTS、唱歌或发布动作。

ActionPlan 至少绑定：

- `plan_id`；
- `origin_request_id` 和本次 handle 内从 0 开始递增的 `plan_ordinal`；
- `target_character_id`；
- `interaction_id`；
- `source_stimulus_ids`；
- 生成计划时依赖的状态版本；
- 有序且不可变的强类型 actions。

### 8.3 输出流

```python
class AgentOutputSink(Protocol):
    async def emit(self, output: AgentOutput) -> None:
        ...
```

每条输出至少携带：

```python
@dataclass(frozen=True)
class AgentOutput:
    interaction_id: str
    execution_id: str
    action_id: str
    sequence_no: int
    kind: AgentOutputKind
    payload: AgentOutputPayload
```

第一版通道无关输出可包括：

- `TEXT_DELTA` / `TEXT_FINAL`；
- `AUDIO_CHUNK` / `AUDIO_END`；
- `EXPRESSION`；
- `MOTION`；
- `HAPTIC`；
- `SONG_STATE`。

不同 stage 绑定不同 sink 实现，再由 sink 委托对应的协议 Adapter：

| stage | sink 实现角色 | 后续通道 |
|---|---|---|
| ChatStage | `ChatAgentOutputSink` | Chat Adapter 编码后发送到 `/chat_ws` |
| CallStage | `CallAgentOutputSink` | Call Adapter 编码后发送到 `/call_ws` |
| ToyStage | `ToyAgentOutputSink` | 设备 Adapter 转换为语音、动作或振动协议 |
| CharacterActivityStage / one-shot runner | `NoChannelOutputSink` 或明确的 world 输出端口 | 默认不允许即时用户输出；发布和持久化由 Action 执行 |

sink 的 interface 要求：

- 创建时绑定 `interaction_id` 和对应 stage，不让 Agent 根据 `if channel == ...` 选择连接；
- 校验每个输出的 `interaction_id`、`execution_id` 和严格递增的 `sequence_no`；
- 在通道关闭、交互已被取代或输出类型不受支持时明确拒绝，使 realization 返回 `CANCELLED` 或 `FAILED`；
- 负责输出顺序和背压，并把通道无关对象交给对应 Adapter；
- 不决定回复内容、不调用认知模型，也不把 WebSocket 或设备 SDK 暴露给 Agent。

支持的 `AgentOutputKind` 必须在 handle 前由对应 `InteractionSnapshot` 声明。Agent 据此生成可实现计划；`realize_action_plan` 收到不受支持的输出时必须明确失败，不能根据通道偷偷删除或改写 Action。数据库写入、发布和日程等持久副作用不经过 `AgentOutputSink`，只进入 `ExecutionReport`。

### 8.4 执行报告

```python
@dataclass(frozen=True)
class ExecutionReport:
    status: ExecutionStatus
    completed_action_ids: tuple[str, ...]
    failed_action_id: str | None
    output_started: bool
    error_code: str | None
    retryable: bool
```

`status` 为 `COMPLETED`、`CANCELLED` 或 `FAILED`。稳定错误码可以返回给 stage；内部异常细节进入日志。

### 8.5 实现规则

`realize_action_plan` 可以：

- 调用 TTS、唱歌、动画和设备动作；
- 分割、编码并流式发出音频；
- 幂等写入长期记忆、角色状态和 world 状态；
- 发布动态、评论和日记；
- 创建或取消持久日程。

它不可以：

- 再调用认知 LLM 改写回复内容或重新选择是否行动；
- 根据当前通道偷偷删除或重排 Action；
- 直接操作 WebSocket、电话供应商对象或 stage 队列；
- 把部分成功伪装成全部成功。

如果某种生成模型决定的是行动的语义内容，例如聊天回复、动态回复文字或一天的活动安排，它属于 `handle_stimulus`。只有在不改变语义的情况下完成媒介实现，例如 TTS 和演唱音频，才属于 `realize_action_plan`。

## 9. stage 共享的协调约定

不同 stage 不共用同一个状态机，但都从同一个 Agent seam 完成一次认知处理和行动结算。下面是共同约定，不是要求所有实现使用同一个类：

```text
1. Adapter 产生一个强类型逻辑刺激
2. 对应 stage 按自己的规则执行必须立即完成的交互控制
3. stage 建立 InteractionSnapshot
4. stage 建立绑定 request_id 和 interaction_id 的 ActionPlanSink
5. 调用 agent.handle_stimulus(request, action_plan_sink)
6. 每次 sink.emit(plan)：校验并预留 source stimuli，按顺序排入计划队列
7. 计划执行 worker 依次调用 agent.realize_action_plan(...)
8. handle 在内部等待 Recall 等结果，并可继续 emit 后续完整计划
9. handle 返回 HandlingReport
10. stage 等待已接收计划的 ExecutionReport
11. 根据 HandlingReport 和全部 ExecutionReport 提交、保留或释放刺激
12. 对应 stage 按自己的规则保存实际输入输出并更新交互状态
```

`ActionPlanSink.emit` 只负责把计划交给队列。计划执行 worker 可以和仍在运行的 handle 并行，但必须保持同一 request 内的计划顺序；它不能在 `emit` 调用栈中同步重入 Agent。

各 stage 只理解自己需要的交互控制事实。例如 ChatStage 理解消息聚合和重连，CallStage 理解用户开始说话必须打断播放，ToyStage 理解设备是否在线，CharacterActivityStage 理解活动和日程状态。它们不能理解记忆、话题、情绪、歌曲选择或动态回复语义。

## 10. 上下文与 Recall 的所有权

“上下文”分成三类，不能混为一个大字典。

### 10.1 各 stage 自己的交互状态

每一种 stage 只持有组织该类交互所需的状态，不要求几种 stage 共享同一套字段或状态机。例如：

- ChatStage 持有该用户聊天流的 pending 消息、聚合截止时间、重连和已接受的对话记录；
- CallStage 持有 `call_id`、音频序号、播放与取消状态、Realtime 会话引用和断线状态；
- ToyStage 持有设备在线状态、一次玩偶交互的上下文，以及振动或触摸的去抖窗口；
- CharacterActivityStage 持有角色当前活动、规划周期、日程版本和可见的 world 条件，不持有某个用户的私有聊天上下文。

stage 还要声明本次 Interaction 支持哪些输出形式。某一类 stage 不需要为了“统一”而保存其他交互方式才有的字段。

### 10.2 Agent 交互认知上下文

由 Agent/subconscious 内部 context store 按 `(character_id, interaction_id)` 保存：

- 当前注意点；
- 临时回想结果或其引用；
- 尚未完成的认知意图；
- 电话被打断、活动中断等角色可感知状态。

这个 store 是 Agent 的内部 seam，不是 Agent 实例上的用户字典。它必须支持 TTL、版本和显式结束清理；调用方只知道 `interaction_id`。

### 10.3 长期角色与关系状态

- 角色自身状态和每日活动按 `character_id` 保存；
- 用户关系、画像和私有记忆按 `(character_id, user_id)` 保存；
- world 活动状态使用明确的活动或 world 标识；
- 不同用户的私有记忆不能因为共享 Agent 实例而混用。

Recall 始终发生在 Agent 内部。为了观测和排错，可以记录召回的 memory ID、查询和分数，但这些是诊断数据，不是 stage 的业务行为。

### 10.4 慢 Recall 的续程

当一次回复需要较慢的进一步记忆查询时，`handle_stimulus` 自己持有并等待该内部任务：

```python
async def handle_stimulus(request, plans):
    quick_recall = await subconscious.fast_recall(request)

    if quick_recall.is_sufficient:
        await plans.emit(await build_final_reply(request, quick_recall))
        return HandlingReport.consumed(...)

    recall_task = subconscious.start_deep_recall(request)
    await plans.emit(ActionPlan.say("让我想想……"))

    recalled_memory = await recall_task
    request.cancellation.raise_if_cancelled()
    await plans.emit(await build_final_reply(request, recalled_memory))
    return HandlingReport.consumed(...)
```

这里的 `recall_task`、future、回调或 `RecallResult` 都是 Agent 内部实现。它们完成后直接唤醒仍在等待的 coroutine，不能转换成 `RecallCompleted` Stimulus 交给 stage，也不能递归调用公开的 `handle_stimulus`。

如果新的用户输入、电话打断或交互关闭使旧请求失效，stage 取消原处理；Agent 在输出后续计划前检查 cancellation 和交互版本，丢弃迟到的 Recall 结果。只有一个任务必须脱离当前 handle、可跨进程恢复并且其完成本身对角色构成新的外部事实时，才应由 world/system 在未来产生一个新的逻辑 Stimulus；普通 Recall 不属于这种情况。

## 11. ActionPlan 与定时行为

计划中的 Action 必须是强类型。预计需要：

- `Say`；
- `Sing`；
- `ChangeExpression`；
- `PerformMotion`；
- `WriteMemory`；
- `UpdateAgentState`；
- `WriteDiary`；
- `PublishDynamic`；
- `ReplyDynamic`；
- `CreateSchedule`；
- `CancelSchedule`；
- `UpsertSongKnowledge`；
- `RequestSongLearning`；
- `RecordLearnedSong`。

新增 ActionType 必须先补 interface spec，不能使用任意 `CALL_CAPABILITY` payload 绕过评审。

### 11.1 交互等待

“2 秒后强制回复”不是角色行动，而是 stage 调度：

```python
HandlingReport.deferred(
    retained_stimulus_ids=(...),
    reconsider_at=now + timedelta(seconds=2),
)
```

到期后 stage 产生 `InteractionDeadline` 逻辑刺激并再次调用 `handle_stimulus`。

### 11.2 未来日程

“明天上午去散步”是角色对未来的行动安排：

```text
ActionPlan[
    CreateSchedule(
        due_at=...,
        future_stimulus=ActivityDue(...),
    )
]
```

`realize_action_plan` 将其写入持久 scheduler。到期后 scheduler 生成新刺激，即使进程重启也不能丢失。

### 11.3 歌曲知识与学习结果

歌曲抓取记录、下载工件、学习任务状态等运行数据仍由 world/capability/system 管理。只有角色决定接受的歌曲知识和“我已经学会这首歌”的角色经历，才通过 Action 写入 subconscious：

- `UpsertSongKnowledge` 按外部来源、歌曲标识和修订版本幂等写入角色可用的歌曲知识；
- `RequestSongLearning` 只创建可恢复的后台学习任务，不能在一次 `realize_action_plan` 中同步等待完整学习流程；
- `RecordLearnedSong` 按学习任务 ID 幂等记录角色已学会歌曲的事实，并可与 `WriteMemory`、`PublishDynamic` 组成同一计划。

默认情况下，`SongLearned` 只形成学习经历，后续 `DiaryPlanningDue` 再回想并决定是否写日记。只有产品明确要求“学会后立即写日记”时，handle 才能在该次计划中加入 `WriteDiary`。

## 12. 功能分工

分工依据是“决定做什么”还是“完成已经决定的事情”，不是耗时长短。

| 功能 | `handle_stimulus` | `realize_action_plan` | Agent 外部 |
|---|---|---|---|
| 语义预处理 | 理解逻辑刺激 | — | Adapter 只做协议转换和聚合 |
| 完整图片、录音或语音消息 | 需要时调用图片理解或 ASR 等只读能力 | — | Adapter 交付完整媒体或引用；stage 管理交互生命周期 |
| 电话原始 PCM | — | — | CallStage 管理顺序、背压和生命周期，通过 `RealtimeMediaIngress` 发送 |
| Realtime 回合语义 | 通过 Agent 内部 `RealtimeTurnPort` 配置会话、读取语义事件并决定回应 | 仅实现已经形成的计划 | CallStage 只处理必须立即完成的播放停止、关闭和取消控制 |
| Recall | 内部检索并使用 | — | stage 不可见 |
| 是否等待、忽略、回应 | 决定；可输出零到多个完整计划 | — | stage 接收计划和最终报告 |
| 聊天回复 LLM | 生成最终结构化内容 | — | — |
| 动态回复 LLM | 生成最终文字和动作 | — | world 只负责发现新动态 |
| 每日活动规划 LLM | 生成活动与日程计划 | — | world clock 产生规划刺激 |
| TTS、音频分割 | 确定文字和语气 | 实际生成和流式输出 | stage 管理播放/打断 |
| 唱歌 | 选择歌曲、片段和衔接 | 获取和输出音频 | — |
| 输出路由 | 决定需要文字、音频、动作或触觉输出 | 产生通道无关的 `AgentOutput` | 当前 stage 绑定的 `AgentOutputSink` 校验并委托对应 Adapter |
| 动态、评论、日记 | 决定内容和是否发布 | 实际发布 | provider 负责外部协议 |
| 长期记忆和状态 | 决定写入内容与原因 | 幂等提交 | — |
| VCPedia 歌曲发现 | 判断是否接受知识、是否请求学习 | 通过 subconscious 写入歌曲知识或创建学习任务 | world 负责抓取、校验来源和规范化数据，不直接写角色记忆 |
| 歌曲学习技术流程 | 根据 `SongLearned` 决定记忆、动态和后续日记意图 | 记录学习经历并实现已决定的动作 | capability/world 执行下载、分离、训练等长任务并报告结果 |
| 2 秒等待 | 返回 DEFERRED，且不输出计划 | — | stage 设置截止时间 |
| 未来日程 | 生成 CreateSchedule | 持久写入 scheduler | scheduler 到期产生刺激 |
| 电话开始说话 | 理解打断并调整策略 | 可实现后续计划 | stage 立即停止播放 |
| 通话结束 | 决定是否形成记忆 | 可以执行无通道输出的持久动作 | stage 立即关闭资源 |

## 13. 典型流程

### 13.1 连续聊天

```text
消息 A -> handle -> DEFERRED(2s，不输出计划)
消息 B -> handle(pending A+B)
-> emit 正式回复计划 -> CONSUMED
stage 预留 A/B -> realize -> 文字/表情/音频
handle 已结束且执行成功 -> stage 提交 A/B 已消费
```

### 13.2 Realtime 电话与打断

```text
用户 PCM 帧
-> Call Adapter 解包和校验
-> CallStage 维护序号、背压和 call 生命周期
-> RealtimeMediaIngress.append_audio
-> Realtime Adapter 将音频送入当前供应商会话

供应商 speech_started
-> CallStage 立即停止本地播放并取消过期输出
-> UserSpeechStarted
-> handle_stimulus
-> 无计划 CONSUMED，或 emit[短反应/状态变化] 后 CONSUMED

供应商确认用户回合结束
-> Realtime Adapter 规范化为 VoiceUtteranceFinal(turn_id, transcript/media_ref)
-> handle 通过 Agent 内部 RealtimeTurnPort 读取该回合的回复语义事件
-> emit[正式回复计划] -> CONSUMED
-> realize 产生 AgentOutput
-> CallAgentOutputSink
-> Call Adapter 按 /call_ws 协议发送文字、音频或控制消息
```

CallStage 不解析供应商的回复内容、工具调用或角色意图；否则它会成为绕过 Agent 的第二套心智。Realtime Adapter 可以维护同一个供应商连接，但向 CallStage 和 Agent 暴露的是两个窄端口。

### 13.3 每日活动

```text
DailyPlanningDue
-> handle 读取角色状态和 world 条件
-> emit[CreateSchedule x N] -> CONSUMED
-> realize 写入日程
-> ActivityDue
-> handle 决定开始或调整活动
```

### 13.4 玩偶振动

```text
原始振动采样
-> Adapter 去抖并聚合为 ToyVibration
-> stage
-> handle 快速路径
-> 无计划 CONSUMED，或 emit[短句/声音/设备动作] 后 CONSUMED
-> realize
```

### 13.5 慢 Recall 与渐进回复

```text
TextMessage
-> handle 启动 Agent 内部 deep recall
-> emit 完整临时计划 Say("让我想想……")
-> stage 排队并 realize 临时计划；handle 仍在运行
-> deep recall 在 Agent 内部完成，不产生 Stimulus
-> handle 检查 cancellation 和交互版本
-> emit 完整正式回复计划
-> handle 返回 CONSUMED
-> stage 等待两个计划的 ExecutionReport 后结算原刺激
```

这条链路不需要“回复是否完成”的额外外部信号。认知过程是否结束由 `HandlingReport` 表示；每个 ActionPlan 是否实现完成由自己的 `ExecutionReport` 表示。

### 13.6 发现歌曲知识

```text
world 从 VCPedia 抓取、校验并规范化候选歌曲
-> SongKnowledgeDiscovered
-> handle 判断该知识是否属于角色，以及是否值得学习
-> emit[UpsertSongKnowledge, 可选 RequestSongLearning]
-> realize 通过 subconscious 持久化角色知识，并把学习请求交给可恢复任务队列
```

world 保存抓取游标、缓存和错误；Agent 不直接操作数据库，也不接管爬虫。

### 13.7 学会一首歌

```text
歌曲学习任务完成并保存工件
-> SongLearned
-> handle 决定这件事对角色意味着什么
-> emit[RecordLearnedSong, WriteMemory, 可选 PublishDynamic]
-> realize 幂等写入学习经历并实现已决定的公开行动
-> 之后 DiaryPlanningDue 可 Recall 这段经历并决定是否写日记
```

`SongLearned` 是一次新的外部事实，因此可以作为 Stimulus；它不同于 Agent 内部普通 Recall 的完成通知。

## 14. 并发、幂等、失败与取消

### 14.1 顺序与状态版本

- 同一 `interaction_id` 默认只有一个正在进行的认知处理；普通刺激按顺序处理；
- 具有实时控制意义的新刺激可以让 stage 先执行控制，再取消已经过期的 handle，随后开始新的认知处理；
- 电话媒体上行可以在某次 handle 运行期间继续；它由 CallStage 和 `RealtimeMediaIngress` 独立背压，不进入认知请求队列；
- 同一 request 输出的多个 ActionPlan 按 `emit` 顺序实现；临时计划可以在 handle 等待内部 Recall 时先执行；
- 不同交互可以并行，但对同一角色长期状态的修改必须使用版本检查或事务；
- ActionPlan 记录生成时使用的状态版本；版本冲突不得静默覆盖较新状态；
- Agent 私有 context store 不得把一个 interaction 的内容提供给另一个 interaction。

### 14.2 刺激预留与消费

- handle 开始时，刺激仍保存在 stage 的 pending 中；
- sink 接受某个计划时，stage 预留该计划的 `source_stimulus_ids`；
- `CONSUMED` 且没有输出计划：立即提交 `resolved_stimulus_ids` 已消费；
- `CONSUMED` 且输出了计划：等待本次 handle 结束以及所有相关计划都有最终 `ExecutionReport` 后再结算；
- `DEFERRED`：保留 `retained_stimulus_ids` 并设置重新判断条件；
- `CANCELLED` 或 `FAILED`：结合已经接收计划的执行结果决定释放还是提交，不能假设整次调用没有发生；
- 所有计划都在首次可见输出和不可回滚副作用前失败：可以释放预留并按报告决定是否重试；
- 任一计划已经产生可见输出或不可回滚副作用：相关刺激视为已消费，不自动从头重放；
- 只有无通道输出的持久 Action 失败时，依据 Action 幂等性决定重试。

“刺激已消费”只表示 stage 不应重新投递同一输入，不表示角色已经给出了语义上完整的最终回答。例如临时“让我想想……”已经输出后，正式回复生成失败，系统应记录一次不完整处理失败，但不能自动重放整轮让用户再次听到同一句临时回复。

### 14.3 幂等

- 同一 `stimulus_id` 不重复进入认知上下文；
- 同一 `request_id + plan ordinal` 使用稳定 `plan_id`；重复 `emit` 内容相同则由 stage 幂等接受，内容不同属于契约错误；
- `HandlingReport.emitted_plan_ids` 必须与 sink 实际接受的计划一致；
- 同一 `execution_id + action_id` 的写入、发布和日程最多成功一次；
- `interaction_id / stimulus_id / plan_id / execution_id / action_id` 必须能够串联日志。

### 14.4 取消

- stage 可以分别取消长时间认知处理和长时间行动实现；
- Recall、LLM 和只读能力应尽快响应 handle 的 cancellation；迟到结果不得继续生成计划；
- TTS、唱歌和设备动作应尽快响应 cancellation；
- 持久写入开始后不能假设取消等于回滚，必须报告具体 Action 是否完成；
- CallEnded 先幂等关闭 `RealtimeMediaIngress`，取消该通话的 Realtime response 和通道输出，再把 `CallEnded` 交给 Agent；
- CallEnded 后禁止向已关闭通道输出，但允许执行已经明确的无通道记忆整理动作；
- 关闭后迟到的供应商 delta、tool call 或最终语义事件不能再生成新计划，也不能恢复已取消输出。

### 14.5 错误

- 信息不足或等待外部条件：`DEFERRED`，并且没有输出计划；
- 已知刺激但角色不行动：无计划的 `CONSUMED`；
- 未知刺激或非法 payload：接口错误；
- Recall、模型或只读能力不可用：handle 返回 `FAILED`，并按是否已经输出计划及重试安全性填写报告；
- 执行能力不可用：`ExecutionReport.status` 为 `FAILED`；
- `AgentOutputSink` 遇到已关闭通道、不支持的输出类型或发送背压超限：拒绝该输出，并在对应 Action 的 `ExecutionReport` 中记录明确失败；
- Realtime 端口不可用：CallStage 保持通道生命周期可控，handle 按是否已经产生可见输出返回失败或降级计划；
- 非法计划、跨角色执行、输出序号倒退：抛出契约错误并报警。

### 14.6 Realtime 会话生命周期与背压

- 每个 `call_id` 绑定唯一的 `RealtimeSessionRef`，不能跨通话复用；
- CallStage 对原始音频执行序号校验、队列上限和背压，Realtime Adapter 负责供应商协议及事件规范化；
- 同一个供应商连接可以同时支持媒体写入和语义回合读取，但两个端口不能互相泄漏职责；
- Agent 不接收原始 PCM，也不持有供应商 WebSocket；
- `close_input`、取消 response 和关闭输出都必须幂等；
- 供应商不可用时，系统必须明确选择拒绝新通话、结束当前通话或进入已设计的降级模式，不能让 CallStage 自行生成角色回复。

## 15. 迁移与小 PR

1. **PRD PR（当前）**：确认场景、术语、状态归属、stage 家族和两个 Agent interface；不改代码。
2. **interface spec PR**：锁定 HandleStimulusRequest、四种 InteractionSnapshot、ActionPlanSink、HandlingReport、ActionPlan、ExecutionContext、AgentOutputSink、AgentOutput、ExecutionReport、两个 Realtime 端口，以及歌曲刺激和 Action；明确顺序、背压、拒绝、关闭和错误行为。
3. **Agent façade 与领域类型 PR**：先写公开 façade、强类型 Stimulus/HandlingReport/Action 的契约测试，再补最小实现；façade 可以暂时委托现有内部逻辑，但不能复制一套新业务行为。
4. **文字 handle 切片**：把一个真实聊天调用方迁移到 `get_agent(character_id)` 和 `handle_stimulus`，覆盖无计划 `CONSUMED`、`DEFERRED` 与单计划输出；同一 PR 删除该调用方对旧 Agent 内部对象的直接依赖。
5. **Say realization 切片**：迁移文字、TTS、流式输出、ChatAgentOutputSink、取消和部分失败，并删除该路径的直接 speech 调用。
6. **渐进计划切片**：覆盖临时计划、内部慢 Recall、正式计划、取消和迟到结果丢弃。
7. **触摸/玩偶切片**：迁移低延迟感知、ToyStage 与 ToyAgentOutputSink，不引入原始采样。
8. **Realtime 端口切片**：用契约测试固定 `RealtimeMediaIngress` 和 `RealtimeTurnPort`，并由 Realtime Adapter 在同一供应商会话上实现两个窄端口。
9. **电话媒体与控制切片**：迁移 CallStage 的音频上行、背压、开始说话、打断、关闭和 CallAgentOutputSink；stage 不解析供应商回复语义。
10. **电话认知切片**：将 VoiceUtteranceFinal 和供应商回合语义收进 Agent handle，通过内部 `RealtimeTurnPort` 生成计划，并删除旧 CallStream 的独立回复心智。
11. **持久 Action 切片**：记忆、状态、日记、动态和日程逐种迁移。
12. **歌曲知识切片**：world 只发现并规范化 VCPedia 数据，Agent 处理 `SongKnowledgeDiscovered`，通过 subconscious 实现 `UpsertSongKnowledge` 与 `RequestSongLearning`。
13. **歌曲学习结果切片**：学习任务只报告 `SongLearned`，Agent 决定并实现 `RecordLearnedSong`、记忆、动态及后续日记链路。
14. **world 活动切片**：迁移 CharacterActivityStage、每日规划、ActivityDue 和活动中刺激。
15. **旧路径清理 PR**：在所有调用方已经迁移后，删除 AgentRuntime 业务代理、旧入口、内部类型泄漏和 stage/world 直接能力调用。

不得把电话、玩偶、箱庭和所有旧路径清理放进同一个 PR。

“分小 PR 迁移”不等于长期保留两套路径。每个切片都必须迁移一个可运行的调用场景，并删除该场景已被替代的直接依赖；整个重构只有在所有角色决策调用方都经过 Agent façade、旧业务入口被删除后才算完成。

## 16. 验收标准

### 16.1 本 PRD

- 两个 Agent interface 的职责没有重叠；
- Recall、ActionPlan 输出和最终 HandlingReport 不再混为同一种结果；
- ChatStage、CallStage、ToyStage 和 CharacterActivityStage 可以拥有不同状态机，但都遵守同一套 Agent 调用、计划排队和刺激结算约定；
- InteractionSnapshot 使用强类型变体，不靠充满可选字段的通用对象表达所有交互；
- 慢 Recall 完成后不生成 `RecallCompleted` Stimulus，也不重新调用公开的 `handle_stimulus`；
- 临时回复和正式回复都是完整且不可变的独立 ActionPlan；
- 每日规划、活动刺激、电话和玩偶都能映射到同一组 interface；
- 电话打断、通话结束和设备安全不依赖 LLM 才能完成；
- 电话原始 PCM 只经过 CallStage 和 `RealtimeMediaIngress`；供应商回合语义由 Agent 通过 `RealtimeTurnPort` 处理，CallStage 不形成第二套回复逻辑；
- Agent 只产生通道无关的 `AgentOutput`，Chat/Call/Toy 的 stage-bound sink 再委托相应 Adapter；
- VCPedia 新歌与学习完成都先形成强类型 Stimulus，角色知识和经历由 Agent 决定并经 subconscious 持久化；
- 交互等待和未来日程被明确区分；
- “不在一个 PR 迁移”与“最终不保留旧路径”的边界清楚；
- 不读取内部代码也能判断一项工作属于 handle、realize、stage、Adapter 还是 world。

### 16.2 后续实现

- stage 和 world 不再导入 Agent 内部回复、话题和记忆对象；
- AgentRuntime 的业务入口收敛为 `get_agent(character_id)`；
- 业务代码不再直接调用角色 speech、singing、diary、dynamic 等能力；
- 强类型刺激覆盖当前聊天以及电话、玩偶、每日规划和活动事件；
- `SongKnowledgeDiscovered` 和 `SongLearned` 覆盖知识接受、学习任务、记忆、动态和后续日记链路；
- 零计划、单计划、多计划、DEFERRED、取消、迟到 Recall、重试、部分输出和重复执行都有 interface 级测试；
- 四种 InteractionSnapshot 的隔离、每种 AgentOutputSink 的通道绑定与关闭行为都有契约测试；
- Realtime 两个端口共享一次供应商会话，但媒体背压、语义事件、取消和关闭职责有独立契约测试；
- 同一角色的多用户、多交互测试不会串用私有记忆或认知上下文；
- 所有角色决策调用路径都只使用 Agent façade，旧回复路径和旧业务代理已经删除。

## 17. 已确定的设计决策

1. Agent 对外只有 `handle_stimulus` 和 `realize_action_plan` 两个业务 interface。
2. Agent 是每角色共享实例；交互认知状态按 interaction 保存，不直接作为用户字典挂在实例上。
3. stage 是交互组织角色，不是一个共享实例或统一状态机；当前不建立 BaseStage。
4. InteractionSnapshot 是 Chat、Call、Toy、CharacterActivity 的强类型联合，角色自主活动可以没有 `user_id`。
5. Recall 是 Agent 内部过程；其完成直接恢复当前 handle，不向 stage 返回记忆内容，也不产生 `RecallCompleted` Stimulus。
6. `handle_stimulus` 运行期间通过 `ActionPlanSink` 输出零到多个完整计划，结束时另行返回 `HandlingReport`。
7. `ActionPlanSink` 是 handle 的输出端口，不是 Agent 的第三个业务 interface；它只入队，不同步重入 Agent。
8. 临时回应和最终回应是两个独立的完整 ActionPlan，不使用可变的“半完成计划”。
9. Structured reply、动态回复文字和每日活动计划由 handle 生成；TTS、唱歌、发布和持久写入由 realize 完成。
10. AgentOutput 是通道无关的；每个 stage 绑定自己的 AgentOutputSink，再委托对应 Adapter 完成协议发送。
11. 电话原始 PCM 经 CallStage 和 `RealtimeMediaIngress` 进入供应商；Agent 通过内部 `RealtimeTurnPort` 处理供应商回合语义。
12. stage 先执行电话打断、通话关闭等实时控制，再取消过期 handle，并把相应逻辑刺激交给 Agent。
13. 2 秒强制回复属于 `DEFERRED` 和 stage 截止时间；未来活动属于持久 Schedule Action。
14. 原始音频帧和高频传感器数据不进入 Agent。
15. VCPedia 抓取和学习工件属于运行数据；角色歌曲知识与学习经历由 Agent 决定、由 subconscious 持久化。
16. 新 Stimulus 和 Action 使用强类型；不得依赖任意 payload 扩展协议。
17. 增加 Agent 公开 interface、Stimulus kind 或 ActionType 前，先更新 interface spec 并评审。
18. 渐进迁移只约束 PR 大小，不允许永久保留绕过 Agent 的旧角色决策路径。

## 18. 评审时必须能直接回答的问题

1. 用户在 Agent 正说话时开口，谁负责立即停止音频，谁决定角色之后怎么回应？
2. 电话连续 PCM 由谁转发，供应商的语义回复与工具调用又由谁解释？为什么这不会在 CallStage 形成第二套心智？
3. 聊天、电话、玩偶和角色自主活动的 stage 分别按什么标识隔离？哪些协调约定共享，哪些状态机不共享？
4. Agent 产生一段文字或音频后，怎样准确路由到 `/chat_ws`、`/call_ws` 或玩偶通道，而不让 Agent 知道 WebSocket 格式？
5. handle 输出一个计划后仍在等待 Recall，谁执行这个计划，谁表示整个认知过程已经结束？
6. Recall 在 Agent 内完成后，为什么不产生 `RecallCompleted` Stimulus，代码从哪里继续执行？
7. 临时“让我想想……”已经播放，但正式回复生成失败，原刺激是否自动重试？
8. TTS 在首个音频块前失败，刺激是否已经消费？
9. 通话已经关闭后，Agent 是否还能发出音频、写记忆或创建日程？
10. 玩偶连续产生 100 次振动采样时，为什么 Agent 不会收到 100 个刺激？
11. 从 VCPedia 发现新歌时，哪些数据由 world 保存，哪些知识必须由 Agent 决定后写入？
12. `SongLearned` 为什么可以成为 Stimulus，而普通 Recall 完成不能？学会歌曲后日记何时生成？
13. 每日计划写入一半时进程崩溃，重试怎样避免重复日程？
14. 两个用户同时和同一角色交互时，哪些状态共享，哪些状态隔离？
15. “本 PR 不迁移全部旧路径”为什么不代表可以永久保留旧回复入口？重构完成的可检查条件是什么？

如果这些问题必须阅读内部代码才能回答，interface spec 仍不够清楚，不能开始实现。
