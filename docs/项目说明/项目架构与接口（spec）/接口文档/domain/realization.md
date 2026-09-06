# 计划与 realization 领域契约

> 状态：2026-09-06 领域类型、构造校验及两个 Protocol 声明已实现；Agent 门面、请求账本和逐行动执行账本见 [Agent 接口](../agent/facade.md)，输出生产与持久序列增量见 [输出投递目标契约](../agent/output-delivery.md)。
>
> 对应 [issue #61](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/61)。字段和构造规则描述当前实现；stage 消费、执行、投递和客户端映射是运行时接入契约，不表示本轮已实现这些行为。
>
> 当前行为依据与风险见 [本轮核对记录](../../../../开发进程文档/设计文档/Issue-61-realization-契约核对.md)。输入沿用 [handle 输入契约](handle-input.md)，处理结算沿用 [HandlingReport](handling-report.md)。

## 1. 归属与公开入口

类型归 `server/src/domain/agent`，公开导入路径为 `src.domain.agent`。
值对象只在内存中验证字段和内部关系。跨调用的身份一致性、重复提交、当前修订和效果提交由对应运行时边界验证。

协作位置沿用两个业务入口：`await agent.handle_stimulus(request, plan_sink) -> HandlingReport` 和 `await agent.realize_action_plan(plan, execution_context, output_sink) -> ExecutionReport`。
两个 sink 是调用方传入的 Protocol；本文件定义其签名与接收契约，Agent 运行时行为由 Agent 接口文档说明。

本轮公开类型范围：

| 分组 | 名称 |
| --- | --- |
| 计划 | `ActionPlan`、`Action`、`ActionKind` |
| 具体行动 | `StartThinking`、`Say`、`Sing`、`WriteDiary`、`PublishDynamic`、`ReplyDynamic`、`RequestSongLearning` |
| 行动值 | `Tone`、`ChangeExpression`、`DynamicReplyTarget`、`DynamicSource`、`Visibility`、`OutputDelivery` |
| 接收协议 | `ActionPlanSink`、`PlanReceipt`、`PlanAcceptanceStatus`、`AgentOutputSink`、`OutputReceipt`、`OutputAcceptanceStatus` |
| 执行输入 | `ExecutionContext` |
| 输出 | `AgentOutput`、`TextFinalOutput`、`AudioChunkOutput`、`MessageEndOutput`、`ExpressionOutput`、`AudioFraming`、`MessageEndStatus`、`AudioErrorCode` |
| 结算 | `ExecutionReport`、`ExecutionStatus`、`ActionResult`、`ActionExecutionStatus`、`EffectRef`、`EffectKind` |
| 错误 | `InvalidRealizationContractError`、`RealizationContractErrorCode`、`SinkRejectedError`、`SinkRejectionCode`、`ExecutionErrorCode` |

复用已有 `MediaRef`、`CancellationToken` 和 `AgentOutputKind`。
这里的 `ActionPlan` 与旧 `src.domain.action.ActionPlan` 是不同类型。

## 2. 通用值规则

- 所有数据类不可变、仅限关键字参数；表内字段均显式提供，可选字段也显式传 `None`。
- 标识、语义代码、必填正文至少包含一个非空白字符，保存原值。
- 集合使用元组；输出能力集合沿用现有 frozenset。拒绝用可变集合代替。
- 整数不接受 bool，序号及计数非负；日期是 `date` 而非 `datetime`；时间必须具有有效时区偏移。
- 枚举字段只接受对应枚举实例；`kind` 由具体类型固定，不是构造参数。
- 不合法的参数、字段或内部组合抛出 `InvalidRealizationContractError(ValueError)`，其只读 `code` 取自 `RealizationContractErrorCode`。

构造错误码为 `CONTRACT_INVALID_ACTION`、`CONTRACT_INVALID_PLAN`、`CONTRACT_INVALID_EXECUTION_CONTEXT`、`CONTRACT_INVALID_OUTPUT`、`CONTRACT_INVALID_RECEIPT`、`CONTRACT_INVALID_EXECUTION_REPORT`、`CONTRACT_INVALID_VALUE`；协议值与枚举成员名相同。

## 3. Action 与值对象

`Action` 为不可直接构造的抽象基类，公共字段只有 `action_id: str`，具体类型提供固定 `kind: ActionKind`。
本轮 ActionKind 为 `START_THINKING=start_thinking`、`SAY=say`、`SING=sing`、`WRITE_DIARY=write_diary`、`PUBLISH_DYNAMIC=publish_dynamic`、`REPLY_DYNAMIC=reply_dynamic`、`REQUEST_SONG_LEARNING=request_song_learning`。

### 3.0 处理开始通知

`StartThinking(*, action_id: str)` 只携带公共行动身份，没有额外字段。Agent 开始实际内容处理后，在耗时的 Recall 或模型工作前，先通过 plan_sink 发出包含 StartThinking 的计划，通知 stage 已开始处理。

该通知使用本请求的首个计划（plan_ordinal=0），actions 只包含一个 StartThinking；同一请求最多产生一个这种计划。后续业务计划接着编号，状态通知与业务行动不能混在一个计划中。
ActionPlan 构造器验证包含 StartThinking 时的单行动和 ordinal=0 约束；跨计划的次数与顺序属于运行时约定。
plan sink 校验并接收通知后，由 stage 直接消费、发送既有 `agent_state_changed(thinking)`，不等待语音执行队列。它不调用 realize，不生成 ExecutionContext、AgentOutput 或 ExecutionReport。其余六种业务 Action 仍交给 realize。
若将这种通知计划误传给 realize，执行边界以 UNSUPPORTED_ACTION 拒绝，不把它当作已完成的业务行动。

已接收的通知计划也记入 HandlingReport.emitted_plan_ids；是否有待执行的业务计划依据计划内容判断，不能仅凭该字段非空推断。不为已由 stage 消费的通知等待 ExecutionReport。
思考状态归属 origin_request_id。stage 在相关处理全部结束、失败或取消时清理提示，旧请求完成不能关闭新请求的提示；不依赖 StopThinking。只处理协调信号的请求不自动产生 StartThinking。

### 3.1 表达

| 类型 | 字段 | 规则与语义 |
| --- | --- | --- |
| `Tone` | `value: str` | 非空白语气代码，兼容当前由角色配置决定的语气集合 |
| `ChangeExpression` | `expression_id: str` | 非空白表情代码，表达本次说话或演唱采用的表情 |
| `OutputDelivery` | 枚举 | `CONVERSATION=conversation`、`EPHEMERAL_REACTION=ephemeral_reaction` |
| `Say` | `content: str`、`sound_content: str \| None`、`prepared_audio_ref: MediaRef \| None`、`tone: Tone`、`expression: ChangeExpression \| None`、`delivery: OutputDelivery` | 显示文本、TTS 文本、预制媒体、语气、表情和呈现方式 |
| `Sing` | `song_id: str`、`segment_id: str`、`expression: ChangeExpression \| None` | 已确定的歌曲与片段；采用 CONVERSATION 呈现 |

`Say.sound_content` 非 None 时必须非空白，且与 `prepared_audio_ref` 互斥。
`content` 必须是字符串；空白显示文本只在提供预制音频时合法。两个音频来源均为 None 时是纯文字表达，不隐式从 content 再生成 TTS 文本。
`Say.content` 和 `sound_content` 表达不同内容：前者用于展示，后者可经过适合朗读的文本清理。

普通对话和欢迎消息采用 CONVERSATION。触摸快速回应采用 EPHEMERAL_REACTION，允许空显示文本、预制音频及表情。
同一 Action 生成的各项输出沿用相同 delivery。

演唱的歌曲标题和歌词从所选歌曲片段解析为 TextFinalOutput；不重新让模型选择歌曲。
演唱前后的说话分别用有序 Say 表达。

### 3.2 日记、动态与学歌

| 类型 | 字段 | 规则与语义 |
| --- | --- | --- |
| `Visibility` | 枚举 | `GLOBAL=global`、`PRIVATE=private`，对应当前动态可见性 |
| `DynamicReplyTarget` | `dynamic_id: str`、`parent_comment_id: str \| None` | None 表示回复原帖，否则回复指定评论 |
| `DynamicSource` | `source_type: str`、`source_id: str` | 发布来源的非空白语义代码和稳定业务身份；用于当前来源追踪与跨请求去重 |
| `WriteDiary` | `owner_user_id: str`、`local_date: date`、`body: str` | 发布给指定用户的当日日记；正文已包含日期、心情等展示内容 |
| `PublishDynamic` | `body: str`、`media_refs: tuple[MediaRef, ...]`、`visibility: Visibility`、`owner_user_id: str \| None`、`source: DynamicSource`、`allow_comment: bool` | 发布已决定的动态；正文必须非空白；PRIVATE 必须有 owner_user_id |
| `ReplyDynamic` | `target: DynamicReplyTarget`、`owner_user_id: str`、`body: str` | 在指定用户归属下发布原帖或评论回复 |
| `RequestSongLearning` | `song_id: str`、`dedup_key: str` | 请求外部长任务学习一首指定歌曲，dedup_key 表达跨 execution 的同一业务请求 |

WriteDiary 的效果是当前的私密日记动态：固定 private、禁止评论、来源为 diary，业务去重身份为角色、用户与日期。它与通用 PublishDynamic 的存储通道相同，但业务唯一性和发布规则不同。

PublishDynamic 的 `source` 同时携带当前动态页面使用的来源信息及业务身份，不再另设表达相同身份的 dedup_key。
ReplyDynamic 的安全重投由 execution/action 身份识别；当前没有证据要求再提供一个平行的任意 dedup_key。
RequestSongLearning 的执行结果通过 EffectRef 返回实际任务身份；提交 Action 本身不表示歌曲已经学会。

## 4. ActionPlan

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `plan_id` | `str` | 可独立排队和引用的稳定计划身份 |
| `origin_request_id` | `str` | 来源 handle 请求 |
| `plan_ordinal` | `int` | 同一请求的计划序号 |
| `target_character_id` | `str` | 实现该计划的角色 |
| `interaction_id` | `str` | 所属持续交互 |
| `basis_interaction_revision` | `int` | 生成决定时依据的交互修订 |
| `source_stimulus_ids` | `tuple[str, ...]` | 实际参与该计划决策的刺激身份，允许为空 |
| `actions` | `tuple[Action, ...]` | 非空、有序行动；action_id 在计划内唯一 |

source_stimulus_ids 内部唯一，保持传入顺序。引用范围为本次请求的触发刺激与 pending 的并集；主动到期刺激即使没有 pending 也可作为依据。
它表达计划依据，不代替 HandlingReport 的 considered/consumed/retained 结算。

构造时验证序号非负。Agent 按产生顺序从零分配 ordinal，stage 按正常接收顺序处理计划；本版不要求接收器实现缺号检测、乱序重排或丢包恢复。
plan_id 与 request/ordinal 分别服务独立计划引用和请求内排序；安全重投时两者以及完整计划值都保持不变。

## 5. ActionPlanSink 与 PlanReceipt

```python
class ActionPlanSink(Protocol):
    async def emit(self, plan: ActionPlan) -> PlanReceipt: ...
```

`PlanReceipt(*, plan_id: str, status: PlanAcceptanceStatus)`。
状态为 `ACCEPTED=accepted` 或 `ALREADY_ACCEPTED=already_accepted`。
回执身份必须对应被提交计划。两个状态都表示成功接收，不表示所有调用都成功，也不表示业务行动完成。

接收器已识别同一计划曾被接收时，返回 ALREADY_ACCEPTED；已知同一身份对应不同内容时拒绝。未能确认的重复投递不能冒充 ALREADY_ACCEPTED。
接收边界验证绑定的角色、交互、请求、可见刺激和当前修订；接收后才能将计划记入 HandlingReport.emitted_plan_ids。
emit 可以等待以施加背压，但必须有界。接收过程不在当前调用栈中同步重入 realize。

发生明确拒绝时，抛出 `SinkRejectedError`，通过只读 `code: SinkRejectionCode` 提供原因；不返回成功回执。
代码为 `IDENTITY_MISMATCH`、`CONTENT_CONFLICT`、`STALE_INTERACTION`、`UNSUPPORTED_OUTPUT`、`SINK_CLOSED`、`BACKPRESSURE_TIMEOUT`，协议值与成员名相同。
明确拒绝表示本次值未新增接收；连接丢失导致结果未知时，不宣称没有接收。本版不承诺跨连接自动重投、恰好一次投递或丢包恢复。

## 6. ExecutionContext

stage 在业务计划出队、开始执行时创建 ExecutionContext，将其作为第二个参数传入 `await agent.realize_action_plan(plan, execution_context, output_sink)`。它表达执行开始时的事实；StartThinking 由 stage 直接消费，不使用此上下文。

```python
ExecutionContext(
    *,
    execution_id: str,
    interaction_id: str,
    current_interaction_revision: int,
    cancellation: CancellationToken,
)
```

execution_id 标识一次计划执行及其重试，不能被不同 plan 共用。
context 保存传入的同一 CancellationToken；独立于原 handle 的取消令牌。
current_interaction_revision 是开始执行时的事实，覆盖计划接收后排队期间的变化，因此与 plan.basis_interaction_revision 含义不同。

表达型行动要求启动时修订匹配，执行中继续通过 cancellation 和绑定 sink 阻止失效输出。
持久行动是否开始取决于该行动的接受及取消边界；已经提交的效果保留在报告里。
构造器不查询当前 stage，也不自行验证另一对象或持久数据。

## 7. AgentOutput

AgentOutput 为不可直接构造的抽象基类。具体输出通过固定 kind 对应 AgentOutputKind，内容直接作为具体类型的字段，避免可任意搭配的 kind/content 二元组。
AgentOutputKind 使用 `MESSAGE_END=message_end` 表示消息结束，适用于 InteractionSnapshot.supported_outputs；该枚举不再提供 AUDIO_END。

| 公共字段 | 类型 | 含义 |
| --- | --- | --- |
| `interaction_id` | `str` | 输出归属与路由身份 |
| `execution_id` | `str` | 执行身份 |
| `action_id` | `str` | 产生输出的行动身份 |
| `sequence_no` | `int` | 当前 execution 的全局输出顺序 |
| `delivery` | `OutputDelivery` | 正常对话或瞬时反应 |

| 具体输出 | kind | 专有字段 |
| --- | --- | --- |
| `TextFinalOutput` | TEXT_FINAL | `text: str`，非空白的最终显示文本 |
| `AudioChunkOutput` | AUDIO_CHUNK | `data: bytes`，非空编码音频；`framing: AudioFraming` |
| `MessageEndOutput` | MESSAGE_END | `status: MessageEndStatus`、`error_code: AudioErrorCode \| None` |
| `ExpressionOutput` | EXPRESSION | `expression: ChangeExpression` |

AudioFraming 为 `COMPLETE_FILE=complete_file` 和 `FILE_FRAGMENT=file_fragment`：前者每块是可独立解码的音频文件，后者需将同一 Action 的音频块依序拼成一个文件。依据是当前 TTS 逐块编码 WAV、演唱对整体音频切分字节，两种方式不能混为同一种无说明的 chunk。
媒体编码、采样率与声道由编码文件头描述。
预制媒体先由执行边界读取为 bytes；不再给 AudioChunkOutput 提供第二套 MediaRef 输出路径。

MessageEndStatus 为 `COMPLETED=completed`、`FAILED=failed`、`CANCELLED=cancelled`。
AudioErrorCode 为 `EMPTY_AUDIO`、`GENERATION_FAILED`，值同成员名。
FAILED 必须有错误码，其他状态为 None。没有产生任何音频也可以发送 FAILED 结束事件，保留已有显示文本。
此处错误码描述当前音频生成失败，业务行动的完整失败原因由 ExecutionReport 表达。

Agent 生产者按发送顺序从零分配 sequence_no，文字、音频及表情跨 Action 共用同一 execution 序列。内部 Handler 只提供业务内容，身份和安全恢复由 [Agent 输出契约](../agent/output-delivery.md) 规定。发送方逐个 await emit；本版接收器按正常接收顺序处理，不要求根据序号重排、补包或建立严格重投去重机制。
每个 Say/Sing 对应一个展示消息、一条可选音频流；消息身份可由稳定 action_id 对应，持久化与 Adapter 必须使用同一映射。
TextFinalOutput 只表示文字定稿。每个已开始投递的 Say/Sing 消息在通道可用时以一个 MessageEndOutput 结束，包括纯文字、正常音频、空音频和生成失败的消息。
MessageEndOutput 表示该消息不会再追加文字或音频，Adapter 将其转换为既有 `is_final_package=True`；FAILED 映射到 `audio_error=True` 及对应错误码：EMPTY_AUDIO 对应 TTS_EMPTY，GENERATION_FAILED 对应 TTS_STREAM_ERROR。
客户端沿用终止包与播放队列机制，播完该消息后才执行后续包。MessageEndOutput 本身不声称客户端已经播放完成。
正常路径先输出文字、表情和音频，随后终止该消息；失败前尚未发出的显示文本仍应保留。取消时通道仍可用则发送 CANCELLED 终止，Adapter 映射为 audio_error=True、error_code=CANCELLED，避免客户端保存被截断的音频；该外部错误码由终止状态得出，MessageEndOutput.error_code 仍为 None。通道已关闭则由本地关闭流程清理，不宣称终止包已送达。
同一 Action 在消息终止后仍可输出恢复 normal 的表情，这属于后续控制包，不再追加上一条消息的内容。

当前输出枚举中的 TEXT_DELTA、MOTION 已存在；本轮不增加其具体输出构造类型，保留现有枚举成员。

## 8. AgentOutputSink 与 OutputReceipt

```python
class AgentOutputSink(Protocol):
    async def emit(self, output: AgentOutput) -> OutputReceipt: ...
```

`OutputReceipt(*, execution_id: str, sequence_no: int, status: OutputAcceptanceStatus)`。
状态为 `ACCEPTED=accepted` 或 `ALREADY_ACCEPTED=already_accepted`。
回执保留输出身份，便于持久记录与原输出关联；只表示接收，不表示播放完成。

sink 验证交互、执行和行动绑定，按正常收到的调用顺序处理输出；识别到同一输出已接收时可返回 ALREADY_ACCEPTED，已知身份对应不同内容时拒绝。ALREADY_ACCEPTED 保留成功识别语义，不代表本版已承诺跨连接去重。
支持种类、当前失效状态、关闭和背压同样在接收边界验证；发生明确拒绝时，抛出第 5 节的 SinkRejectedError。
持久发布和任务提交的结果记录在 ActionResult，不伪造媒体输出来充当效果回执。

## 9. ExecutionReport 与 ActionResult

ExecutionStatus：`COMPLETED=completed`、`CANCELLED=cancelled`、`FAILED=failed`。
ActionExecutionStatus 额外包含 `ALREADY_COMPLETED=already_completed` 和 `NOT_STARTED=not_started`。

| 类型 | 字段 |
| --- | --- |
| `EffectRef` | `kind: EffectKind`、`effect_id: str` |
| `ActionResult` | `action_id: str`、`status: ActionExecutionStatus`、`error_code: ExecutionErrorCode \| None`、`irreversible_effect_committed: bool`、`effect_ref: EffectRef \| None` |
| `ExecutionReport` | `execution_id: str`、`plan_id: str`、`status: ExecutionStatus`、`action_results: tuple[ActionResult, ...]`、`output_started: bool`、`error_code: ExecutionErrorCode \| None`、`retryable: bool` |

EffectKind 只登记 `DYNAMIC_POST=dynamic_post`、`DYNAMIC_COMMENT=dynamic_comment`、`SONG_LEARNING_JOB=song_learning_job`，对应本轮实际效果。日记返回动态效果引用。

ExecutionErrorCode 为 `CONTRACT_MISMATCH`、`UNSUPPORTED_ACTION`、`UNSUPPORTED_OUTPUT`、`STALE_INTERACTION`、`SINK_CLOSED`、`BACKPRESSURE_TIMEOUT`、`DEPENDENCY_UNAVAILABLE`、`PROVIDER_TIMEOUT`、`AUDIO_EMPTY`、`AUDIO_GENERATION_FAILED`、`CANCELLED`、`INTERNAL_ERROR`，值同成员名。
单项和整体失败使用同一组原因码，通过所在报告字段区分作用范围；不建立内容相同的 ActionErrorCode。

构造规则：

1. action_results 非空、action_id 唯一。按执行顺序为零到多个 COMPLETED/ALREADY_COMPLETED，可接一个 FAILED/CANCELLED，其后只能 NOT_STARTED。
2. COMPLETED 报告要求所有单项均为 COMPLETED/ALREADY_COMPLETED；FAILED/CANCELLED 报告允许在任何 Action 开始前结束，此时所有单项 NOT_STARTED。
3. 单项 FAILED 必须有非 CANCELLED 的错误码，CANCELLED 使用 CANCELLED，其余状态错误码为 None。整体状态与错误码采用相同规则；存在失败/取消单项时整体状态及错误码与该项一致。
4. NOT_STARTED 的 effect_ref 为 None，irreversible_effect_committed 为 False。其他状态如提供 effect_ref，必须已提交不可回滚效果；失败或取消可以保留此前已提交的效果。
5. `ExecutionReport.irreversible_effect_committed` 作为只读派生属性，等于各 ActionResult 对应值的 any，不接受重复构造参数。
6. output_started 是调用方记录的“该 execution 是否曾有输出被接收”；action_results 未携带输出列表，不能由其状态推导。retryable 表示原 execution 是否可安全继续，不表示可以换 ID 从头执行。

构造器只验证以上内部关系。action_results 是否完整对应原 plan、效果是否真实提交、重试是否重复输出，需要输入计划及 ledger/sink 验证。
同一 execution 重试复用原行动身份，已完成行动报告 ALREADY_COMPLETED；已接收的输出保持身份及内容，不重新生成后复用同一序号。retryable 表示行动可安全继续，已有副作用的行动不从头重做；UNKNOWN 接收不作为可安全重投的依据。

## 10. 当前客户端行为的覆盖边界

| 当前行为 | 承载方式 |
| --- | --- |
| 普通文字与不同的朗读文本 | Say.content / sound_content |
| 纯文字回复、TTS 成功和无音频失败 | TextFinalOutput、可选 AudioChunkOutput，均以 MessageEndOutput 结束 |
| 唱歌标题、歌词、音频及“唱歌”表情 | Sing，经文字、音频、表情输出 |
| 登录预制欢迎且保存聊天记录 | Say + CONVERSATION |
| 触摸预制音频且不显示气泡、不落聊天记录 | Say + EPHEMERAL_REACTION |
| 音频为空、生成中断、取消后的客户端清理 | MessageEndOutput 的状态及错误；断线时本地通道清理 |
| 私密日记、普通动态和评论 | 对应行动的 owner、来源、可见性和评论策略 |

开始思考通过第 3.0 节的 StartThinking 计划通知 stage，结束思考由 stage 根据对应 handle 的完成、失败或取消清理，发送既有 waiting 状态。

触摸恢复 normal 使用同一 Action 的 ExpressionOutput，顺序为音频及表情、MessageEndOutput、ExpressionOutput(normal)。客户端收到终止包后等待播放结束，再执行恢复表情包。本版沿用这一机制，不增加播放完成回执。

业务计划依次调用 realize，计划内 Action 依次执行，AgentOutput 依次发送。本版保持正常路径的顺序和终止包位置；严格乱序检测、丢包恢复和跨连接重投去重留待后续，不能把现有队列行为描述为这些可靠性保证。

## 11. 契约验证入口

从 `src.domain.agent` 的公开构造器验证合法值、字段缺失/多余、不可变性、Say 音频互斥、计划身份唯一、报告内部关系及错误分类。
两个 Protocol 的类型声明本身不证明运行时行为。正常排队、背压、身份绑定和持久效果幂等通过实际接收器及公开 Agent 调用验证；严格乱序/丢包恢复和跨连接投递去重不属于本版验收。
兼容验证包含思考包时序、文字与音频的消息 ID、音频失败终包、TTS 独立文件块/演唱文件片段、触摸 normal 恢复及私密日记的归属和去重。

当前领域测试为 `server/tests/domain/test_realization_contract.py`，同时由 `test_handle_input_contract.py` 验证 MESSAGE_END 在快照中的使用。在 server 目录运行 `python -m pytest tests/domain -q`。这些测试验证公开值与协议声明，不验证真实 sink 或客户端投递。
