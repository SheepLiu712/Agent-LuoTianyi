# Stimulus 领域契约

> 状态：当前总 SPEC 登记的 15 个可构造类型及 7 个不可构造占位类型均已实现，并已通过领域契约测试。
>
> 权威范围：本文件定义当前总 SPEC 的 Stimulus 公共字段、15 个可构造类型、7 个占位类型、构造所需值对象和稳定错误。`InteractionSnapshot`、request、report、ActionPlan、Call/Realtime、`UserJoinedActivity`、`ActivityInterrupted` 与玩偶触摸不在本契约中。

## 模块和调用者

这些类型归 `server/src/domain/agent/` 所有，并从 `src.domain.agent` 公开导出。Adapter、stage 和 world 通过具体 Stimulus 表达已经规范化的领域事实；Agent 只接收这些类型，不接收 WebSocket 事件、供应商对象或任意 `dict` payload。

`domain` 只负责不可变数据及其自身结构校验。构造对象不会访问数据库、网络、模型或文件，也不会决定会话记录或长期记忆持久化。受控引用是否存在、调用方能否读取，由消费引用的 Handler 通过对应 port 判断。

## 当前公开导出

`src.domain.agent` 公开本文登记的全部 Stimulus 类型、枚举、稳定错误和构造签名中出现的领域值类型。可构造类型提供下文定义的直接构造入口；占位类型只提供名称和固定 `kind`，不承诺未来字段签名。调用方不得从私有实现文件导入构造 helper。

目标公开包不导出 `PersistPolicy`。迁移期旧协议仍从旧路径使用自己的 `PersistPolicy`；本契约不删除旧 `server/src/domain/stimulus.py` 或迁移其生产调用方。

## `Stimulus`

`Stimulus` 是所有登记类型的抽象基类，不能直接构造。它集中定义可构造刺激共有的身份、版本、时间、来源、目标和 interaction 生命周期字段；具体内容和固定 `kind` 由子类型提供。

所有实例及其集合字段都不可变，不提供任意 `payload` 扩展口，也不携带持久化策略。

| 字段 | 类型 | 含义 | 构造约束 |
| --- | --- | --- | --- |
| `stimulus_id` | `str` | 一项外部事实或协调信号的稳定身份 | 非空白；同一事实安全重投时保持不变 |
| `kind` | `StimulusKind` | 具体 Stimulus 的稳定判别值 | 由具体子类型固定，不是构造参数，也不能被调用方改写 |
| `schema_version` | `int` | 当前具体变体的结构版本 | 可构造类型当前只支持整数 `1`；`bool` 不视为整数版本 |
| `occurred_at` | `datetime` | 事实在来源处发生的时间 | 必须带时区；保留调用方提供的值，不以接收或处理时间替代 |
| `source` | `StimulusSource` | 供应商无关的语义来源 | 必须是已定义枚举值；Agent 不根据 `kind` 推断或改写 |
| `target_character_ids` | `tuple[str, ...]` | 应感知该事实的角色 | 至少一个成员；每个成员都是非空白字符串；保留调用方给出的顺序和值 |
| `user_id` | `str \| None` | 与事实有关的账户用户 | 没有相关用户时为 `None`；字符串时必须非空白，不回退默认用户 |
| `ephemeral` | `bool` | 该事实是否只在当前 interaction 窗口内有意义 | 只描述 interaction 生命周期，不直接命令是否写入会话或长期记忆 |

每个可构造类型使用仅限关键字的直接构造器。其完整参数集合是上表中除 `kind` 外的全部公共字段，加上下文各类型表列出的专有字段；所有字段都必须由调用方显式提供，没有隐式业务默认值。

## `StimulusKind`、来源与可用性

`StimulusKind` 的成员名和序列化值属于稳定公开协议：

| 成员 | 序列化值 | 对应类型 | 当前可用性 |
| --- | --- | --- | --- |
| `TEXT_MESSAGE` | `text_message` | `TextMessage` | 已实现、可构造 |
| `IMAGE_MESSAGE` | `image_message` | `ImageMessage` | 已实现、可构造 |
| `VOICE_MESSAGE` | `voice_message` | `VoiceMessage` | 已实现、可构造；当前尚无生产者，为下一版本预先建立契约 |
| `USER_TYPING` | `user_typing` | `UserTyping` | 已实现、可构造 |
| `IMAGE_SELECTION_OPENED` | `image_selection_opened` | `ImageSelectionOpened` | 已实现、可构造 |
| `IMAGE_SELECTION_CLOSED` | `image_selection_closed` | `ImageSelectionClosed` | 已实现、可构造 |
| `TOUCH_INTERACTION` | `touch_interaction` | `TouchInteraction` | 已实现、可构造；当前只表示客户端 Live2D 触摸 |
| `TOY_VIBRATION` | `toy_vibration` | `ToyVibration` | 占位、不可构造 |
| `DEVICE_CONNECTED` | `device_connected` | `DeviceConnected` | 占位、不可构造 |
| `DEVICE_DISCONNECTED` | `device_disconnected` | `DeviceDisconnected` | 占位、不可构造 |
| `PROACTIVE_PROMPT_DUE` | `proactive_prompt_due` | `ProactivePromptDue` | 已实现、可构造 |
| `INTERACTION_DEADLINE` | `interaction_deadline` | `InteractionDeadline` | 已实现、可构造 |
| `DYNAMIC_OBSERVED` | `dynamic_observed` | `DynamicObserved` | 已实现、可构造 |
| `DIARY_PLANNING_DUE` | `diary_planning_due` | `DiaryPlanningDue` | 已实现、可构造 |
| `WORLD_OBSERVATION` | `world_observation` | `WorldObservation` | 已实现、可构造 |
| `DAILY_PLANNING_DUE` | `daily_planning_due` | `DailyPlanningDue` | 占位、不可构造 |
| `ACTIVITY_DUE` | `activity_due` | `ActivityDue` | 占位、不可构造 |
| `ACTIVITY_STARTED` | `activity_started` | `ActivityStarted` | 占位、不可构造 |
| `ACTIVITY_OBSERVATION` | `activity_observation` | `ActivityObservation` | 已实现、可构造 |
| `ACTIVITY_ENDED` | `activity_ended` | `ActivityEnded` | 占位、不可构造 |
| `SONG_KNOWLEDGE_DISCOVERED` | `song_knowledge_discovered` | `SongKnowledgeDiscovered` | 已实现、可构造 |
| `SONG_LEARNED` | `song_learned` | `SongLearned` | 已实现、可构造 |

`StimulusSource` 表达领域事实由谁产生，不表达 WebSocket、HTTP、蓝牙、供应商或 scheduler 等传输和投递机制。

| 成员 | 序列化值 | 语义 |
| --- | --- | --- |
| `USER` | `user` | 用户行为产生的事实 |
| `DEVICE` | `device` | 设备自身状态或行为产生的事实 |
| `WORLD` | `world` | world 规范化的外部或活动事实 |
| `STAGE` | `stage` | stage 为其 interaction 产生的协调或期限事实 |

可构造类型不维护 `kind / source / ephemeral` 或其他字段的组合白名单。字段各自合法时，即使组合当前没有生产者，也必须允许构造；某个 Handler 暂不支持该输入时，由后续 handle 运行时契约表达。

### 占位类型的统一行为

`ToyVibration`、`DeviceConnected`、`DeviceDisconnected`、`DailyPlanningDue`、`ActivityDue`、`ActivityStarted` 和 `ActivityEnded` 是公开的 `Stimulus` 子类型，其类级 `kind` 固定为上表成员，但当前版本不存在合法实例。

这些类型不承诺构造参数或未来专有字段。使用任意参数直接构造，都必须抛出 `InvalidStimulusError(code="CONTRACT_STIMULUS_UNAVAILABLE")`；不得先因参数缺失产生 Python `TypeError`，也不得构造一个只有公共字段的空壳实例。未来启用某个类型时，必须先在本文件补全构造 interface、正常行为和失败行为，再进入 Red/Green。

`ActivityDue` 保留“角色计划活动到达开始条件”的原有术语，不表示活动或事件前一天、当天的提醒。当前 EventStore 的日前/当天提醒由 `ProactivePromptDue` 表达。

## 构造所需领域值类型

### 受控引用

受控引用是只携带稳定 ID 的不可变名义类型。ID 指向服务端所拥有的资源；实际文件地址、存储实现和数据本身都不进入引用对象。不同引用类型不能互换；构造 Stimulus 时只校验 ID，存在性和授权由消费引用的 port 校验。

| 类型 | 字段 | 构造约束 | 含义 |
| --- | --- | --- | --- |
| `MediaRef` | `media_id: str` | 非空白 | 已由媒体边界接管的图片、音频或其他媒体；不是路径、URL、Base64 或 bytes |
| `EvidenceRef` | `evidence_id: str` | 非空白 | 可由消费方授权读取的事实或 EventStore 事件 |
| `SourceRef` | `source_id: str` | 非空白 | 外部知识来源的稳定身份；不是原始网页、URL 或解析器对象 |

- 生产者只有在资源已经被服务端可靠登记或持久化、并取得稳定且可查询的 ID 后，才能构造对应受控引用和 Stimulus；不得先发送临时 ID，再异步补写资源。
- Handler 通过面向 Agent 的窄读取 port 解析引用。ID 不存在、资源已失效或当前请求无权读取时，必须形成明确的 handle 运行时失败；这不属于 Stimulus 构造错误，也不得回退到默认资源、裸路径或空内容。具体存储介质、数据库表和读取实现不属于本契约。

### 规范化语义代码

`BodyRegion`、`ProactiveReason` 和 `WorldObservationKind` 都是不可变的单字段值对象，公开字段统一为 `value: str`，且必须非空白。Adapter/world 必须先把供应商值转成领域语义；当前 SPEC 没有稳定枚举全集，因此 domain 不建立臆测的值白名单。

`DynamicTargetKind` 是稳定枚举，只包含 `POST=post` 和 `COMMENT=comment`。

### 复合事实值

| 类型 | 字段 | 构造约束 | 含义 |
| --- | --- | --- | --- |
| `ActorRef` | `actor_id: str`、`display_name: str \| None` | ID 非空白；名称非 `None` 时非空白 | 平台无关的动态作者 |
| `TouchClickFrequency` | `count_10s: int`、`count_30s: int` | 均为非负整数且 `count_10s <= count_30s`；`bool` 非法 | 客户端观测到的最近 10 秒和 30 秒点击次数 |
| `DynamicMessage` | `message_id: str`、`parent_message_id: str \| None`、`author_ref: ActorRef`、`text: str`、`media_refs: tuple[MediaRef, ...]` | message ID 非空白；parent ID 非 `None` 时非空白；文字非空白或媒体非空，至少有一种内容 | 动态原帖或评论线程中的一条有作者、父子关系和内容的消息 |
| `WorldFact` | `fact_id: str`、`summary: str` | 两者非空白 | 一项已规范化 world 事实；不包含可变 Mapping |
| `ActivityFact` | `fact_id: str`、`summary: str` | 两者非空白 | 一项已规范化活动内事实；不包含 world 或 stage 对象 |
| `SongKnowledgeCandidate` | `song_name: str`、`uploader: str \| None`、`singers: tuple[str, ...]`、`introduction: str`、`lyrics: str \| None`、`lyric_keywords: tuple[str, ...]` | 歌名和介绍非空白；可选字符串非 `None` 时非空白；集合成员非空白，集合允许为空 | 一首歌曲已经规范化、可直接由 Agent 持久化的业务资料 |

## 15 种可构造 Stimulus

### 消息与输入协调

| 具体类型 | 固定 `kind` | 专有字段 | 结构约束 |
| --- | --- | --- | --- |
| `TextMessage` | `TEXT_MESSAGE` | `text: str`；`client_msg_id: str` | 两者非空白；保留原始正文，不自动 trim |
| `ImageMessage` | `IMAGE_MESSAGE` | `media_ref: MediaRef`；`caption: str \| None`；`client_msg_id: str` | client ID 非空白；caption 非 `None` 时非空白 |
| `VoiceMessage` | `VOICE_MESSAGE` | `media_ref: MediaRef \| None`；`transcript: str \| None`；`client_msg_id: str` | client ID 非空白；media 与非空白 transcript 至少有一个 |
| `UserTyping` | `USER_TYPING` | `text_length: int` | 必须为非负整数；`bool` 非法 |
| `ImageSelectionOpened` | `IMAGE_SELECTION_OPENED` | 无 | 只使用公共字段 |
| `ImageSelectionClosed` | `IMAGE_SELECTION_CLOSED` | 无 | 只使用公共字段；不会伪造 `ImageMessage` |

`VoiceMessage` 只表示一条已经结束的非 Realtime 录音消息。当前尚无生产者，但下一版本可以直接使用本契约；不得用它承载电话 turn、原始音频帧或未结束流。

已实现 `TextMessage` 的公开构造 interface 是其他可构造类型的范例：

```python
TextMessage(
    *,
    stimulus_id: str,
    schema_version: int,
    occurred_at: datetime,
    source: StimulusSource,
    target_character_ids: tuple[str, ...],
    user_id: str | None,
    ephemeral: bool,
    text: str,
    client_msg_id: str,
)
```

其他可构造类型遵守同一规则：公共字段在前，随后是本表列出的全部专有字段；不接受 `kind`、`payload` 或 `persist_policy`。

### 客户端 Live2D 触摸

| 具体类型 | 固定 `kind` | 专有字段 | 结构约束 |
| --- | --- | --- | --- |
| `TouchInteraction` | `TOUCH_INTERACTION` | `body_regions: tuple[BodyRegion, ...]`；`click_frequency: TouchClickFrequency \| None` | 部位至少一个；frequency 为 `None` 表示客户端没有提供可解释的统计窗口 |

`TouchInteraction` 当前只表达客户端在 Live2D 界面产生、由客户端聚合后提交的一次触摸。一次提交可以命中多个部位，所以字段使用复数 `body_regions`。App 可以提供 10/30 秒点击频率；当前桌面客户端没有同等统计时必须传 `None`，domain 不推断或伪造频率。

玩偶触摸是另一种领域事实，未来应使用独立 `ToyTouchInteraction` 和独立 `StimulusKind`，再定义 `device_id`、单一部位、gesture、intensity 与 duration。当前版本不登记该类型，也不为这些未来字段建立值对象。

### 到期、动态与 world 事实

| 具体类型 | 固定 `kind` | 专有字段 | 结构约束 |
| --- | --- | --- | --- |
| `ProactivePromptDue` | `PROACTIVE_PROMPT_DUE` | `reason: ProactiveReason`；`due_at: datetime`；`dedup_key: str`；`fact_refs: tuple[EvidenceRef, ...]` | 时间带时区；dedup key 非空白；事实引用允许为空 |
| `InteractionDeadline` | `INTERACTION_DEADLINE` | 无 | 只使用公共字段；表示 stage 已判定当前 interaction 到达强制重评时点 |
| `DynamicObserved` | `DYNAMIC_OBSERVED` | `dynamic_id: str`；`target_message_id: str`；`target_kind: DynamicTargetKind`；`messages: tuple[DynamicMessage, ...]`；`revision: int` | 两个 ID 非空白；messages 至少一条且 message ID 唯一；target ID 在 messages 中恰好出现一次；revision 为非负整数 |
| `DiaryPlanningDue` | `DIARY_PLANNING_DUE` | `local_date: date`；`timezone: ZoneInfo`；`trigger_id: str` | `local_date` 必须是 `date` 而非 `datetime`；trigger ID 非空白 |
| `WorldObservation` | `WORLD_OBSERVATION` | `observation_kind: WorldObservationKind`；`fact: WorldFact`；`evidence_refs: tuple[EvidenceRef, ...]`；`world_revision: int` | revision 为非负整数；证据允许为空 |

`ProactivePromptDue` 同时承载当前 EventStore 在事件前一天或当天产生的主动提醒：`reason` 表达提醒原因，`fact_refs` 指向需要读取的事件。它和 `InteractionDeadline` 都由拥有 interaction 的 stage 构造；底层 scheduler 或 world clock 可以唤醒拥有者，但不得覆盖原 `source` 或把 timer 对象放入 Stimulus。

`InteractionDeadline` 不是 pending 内容的容器，也不允许 Agent 按 ID 回查 stage。stage 触发 deadline 时必须同时构造 `HandleStimulusRequest`；实际待判断对象由同一请求的 `InteractionSnapshot.pending_stimuli: tuple[Stimulus, ...]` 以不可变快照传入。deadline Handler 处理该 snapshot 中的全部 pending，后续通过 `HandlingReport` 按 ID 结算。旧 timer 是否仍有效、它原先由哪个 request 建立、如何取消和去重，都由 stage 在调用 Agent 前根据自己的 interaction revision 与 timer 状态处理，因此 `origin_request_id`、`pending_stimulus_ids`、`due_at` 和 `dedup_key` 都不进入 `InteractionDeadline` 专有字段；公共 `stimulus_id` 标识这次协调信号，`occurred_at` 记录实际触发时间。

`DynamicObserved.messages` 按展示/对话顺序携带原动态与相关评论，并明确标出本次需要 Agent 判断的目标。第一项必须是 `message_id == dynamic_id` 且没有 parent 的原动态；后续消息的 parent 必须指向此前已出现的消息。`target_kind=POST` 时 target 必须是原动态，`target_kind=COMMENT` 时 target 必须是某条评论。调用方负责把数据库或外部记录规范化成 `DynamicMessage`，但不得预先拼接 prompt；Agent 负责根据作者、父子关系、目标和内容组织理解上下文。裸 `str` 列表不属于公开 interface。

### 活动与歌曲事实

| 具体类型 | 固定 `kind` | 专有字段 | 结构约束 |
| --- | --- | --- | --- |
| `ActivityObservation` | `ACTIVITY_OBSERVATION` | `activity_id: str`；`observation: ActivityFact`；`activity_revision: int` | ID 非空白；revision 为非负整数 |
| `SongKnowledgeDiscovered` | `SONG_KNOWLEDGE_DISCOVERED` | `source_ref: SourceRef`；`external_song_id: str`；`revision: int`；`candidate: SongKnowledgeCandidate`；`fetched_at: datetime` | external ID 非空白；revision 为非负整数；时间带时区 |
| `SongLearned` | `SONG_LEARNED` | `learning_job_id: str`；`song_id: str`；`completed_at: datetime` | 两个 ID 非空白；时间带时区 |

一次 `SongKnowledgeDiscovered` 只提交一首歌。crawler 一轮发现多首歌时，为每首候选分别产生稳定 Stimulus，使单首失败、重试和幂等持久化互不影响。需要持久化的规范化歌曲资料放在 `candidate`；原网页、抓取缓存和审计材料不是候选业务数据，也不通过 `evidence_refs` 变相传给 Agent。Agent 不重新抓取或解析来源，只负责按稳定身份持久化候选。

`SongLearned` 只在外部长任务已经保存并验证歌曲文件、完成技术状态更新且保证唱歌曲库可以读取后形成。文件路径和具体产物属于长任务与 singing capability 的实现，不进入 Stimulus；因此当前接口没有 `artifact_refs`。Agent 收到完成事实后更新角色自己的已学歌曲经验/状态，并可决定是否通过 ActionPlan 发动态或表达。

## 通用构造校验

除占位类型的统一失败行为及各表的专有规则外，所有可构造入口统一遵守：

- 运行时类型必须与注解一致；`bool` 不作为 `int`；数值必须有限；
- 所有 ID、key、正文、摘要和语义代码在要求存在时至少包含一个非空白字符，实例保留调用方原值；
- 所有 `datetime` 必须带时区；`ZoneInfo` 必须是实际 `zoneinfo.ZoneInfo`；
- tuple 必须是精确的不可变集合类型，成员逐项验证；构造器不静默接受 list 后转换；
- 固定 `kind` 不出现在构造参数中；实例不可修改，也不能修改其集合内容；
- domain 只检查引用对象和 ID 的结构，不访问外部系统判断引用是否存在或是否已授权；
- 除文档明确列出的结构完整性约束外，不增加 `kind / source / ephemeral`、user、目标角色或当前生产场景的组合限制。

## 构造错误

```python
StimulusErrorCode = Literal[
    "CONTRACT_INVALID_STIMULUS",
    "CONTRACT_UNSUPPORTED_SCHEMA",
    "CONTRACT_STIMULUS_UNAVAILABLE",
]
```

`InvalidStimulusError(ValueError)` 是公开构造异常，并稳定提供：

- `code: StimulusErrorCode`；
- `retryable: Literal[False]`，始终为 `False`。

字段缺失、类型不符、值为空白、目标或必需集合为空、时间不带时区、数值越界及变体缺少可处理内容等字段或结构错误，抛出 `InvalidStimulusError(code="CONTRACT_INVALID_STIMULUS")`。`schema_version` 是整数但不是当前支持的 `1` 时，抛出 `InvalidStimulusError(code="CONTRACT_UNSUPPORTED_SCHEMA")`；非整数版本属于 `CONTRACT_INVALID_STIMULUS`。构造已登记但当前不可用的占位类型，抛出 `InvalidStimulusError(code="CONTRACT_STIMULUS_UNAVAILABLE")`。

`str(error)` 只供人工诊断，具体措辞不是公开契约。调用方不能解析错误字符串，也不能依赖内部字段名、规则 ID、非法值映射或 cause。构造失败不产生部分实例，也不会进入 Agent handle 流程。

## 契约验证 seam

后续 Red/Green 只能从 `src.domain.agent` 的公开导出观察：

1. `Stimulus` 不可直接构造；15 个可构造类型均是其不可变子类型，并固定正确 `kind`；
2. 每个可构造类型至少一个合法样例逐项保留公共字段和专有字段，且不存在 `payload` 和 `persist_policy`；
3. 7 个占位类型是公开 `Stimulus` 子类型、具有固定类级 `kind`，但任意直接构造都稳定返回 `CONTRACT_STIMULUS_UNAVAILABLE`；不为它们写合法样例或猜测未来字段测试；
4. 每个当前所需领域值类型至少一个合法样例可公开构造且不可修改，不同名义引用不能互换；
5. 对每类实际存在的必填、类型、范围、时区、引用或内容为空问题选择最小代表错误，断言稳定 `code` 与 `retryable=False`；
6. 字段合法但少见的 `source / ephemeral` 组合仍可构造，不枚举任何组合矩阵；
7. `VoiceMessage` 至少有媒体或转写；Touch frequency 保持嵌套窗口计数关系；动态目标在消息线程中恰好出现一次；`InteractionDeadline` 不携带 pending ID 或 stage timer 状态；
8. `SongKnowledgeDiscovered` 每个实例只包含一个结构化候选；`SongLearned` 不暴露文件、路径或 artifact 引用；
9. `src.domain.agent` 不公开 `PersistPolicy`，旧 Stimulus 路径仍可使用迁移期协议；
10. 当前公开协议中不存在 Call/Realtime、`VoiceUtteranceFinal`、`UserJoinedActivity`、`ActivityInterrupted` 或玩偶触摸类型。

测试不导入私有构造 helper，不以当前生产者常用值推导组合白名单，也不测试本文件权威范围外的未来 Stimulus。
