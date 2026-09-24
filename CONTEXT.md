# AgentLuo Domain Language

This glossary defines the project-specific language used when describing a character receiving stimuli, deciding what to do, and acting through different interaction carriers.

## Language

**消息投递完成**：
本次消息的内容及必要的终止通知已交给连接发送；它与客户端播放完成是两个不同的事实。

**输出投递接受**：
输出已被接收并进入待发送流程，但尚未确认发送完成；接受结果与后续的发送成功、失败或取消分开表达。

**消息终止通知**：
标记一条消息不再有后续内容的通知。取消时可以不携带正文和音频，但仍属于原消息及原呈现方式，不表示撤回已播放的内容。

**Stimulus**:
A logical event that may be perceived by a character, after raw protocol messages and sensor samples have been normalized and aggregated.
_Avoid_: Raw event, packet, sensor sample

**Stimulus Source**:
The supplier-independent semantic origin explicitly supplied by the Adapter, Stage, or World that constructs a Stimulus. The Agent does not infer it from the stimulus kind, and delivery mechanisms such as World Clock do not overwrite it.
_Avoid_: Transport channel, inferred source, kind-source whitelist

**Agent Persistence Decision**:
角色根据输入与理解结果，判断哪些内容可以构成对话或长期记忆证据的认知决定；它与提交保存的交互时机、底层存储操作分别表达。
_Avoid_: Stimulus PersistPolicy, database transaction, Action Plan

**Interaction**:
A continuous period with a shared context and lifecycle. In the current Agent design it may be a character-user chat, a toy session, or one character's ongoing relationship with a sandbox world.
_Avoid_: Connection, user session

**Stage**:
角色在一种交互场景中的组织者，拥有该交互的上下文生命周期、待处理输入、回复批次、等待策略、优先级与打断决定。不同场景的 Stage 可以采用不同交互规则。
_Avoid_: Transport-only forwarding, global stage, universal BaseStage

**Interaction Snapshot**:
一次处理所依据的不可变交互事实视图。交互标识表示持续交互，交互修订表示其中的事实版本；该视图不等于可变的交互状态或整个上下文。
_Avoid_: Live Stage context, global state version, SnapshotRef

**Cancellation Token**:
The shared mutable control object supplied with a handle request. Stage requests cancellation and Agent observes it. The first reason is retained: SUPERSEDED means the decision basis is outdated; NO_LONGER_NEEDED means handling is no longer required. Cancellation does not roll back accepted plans or committed effects.
_Avoid_: Immutable cancellation snapshot, automatic pending consumption, resettable token

**World**:
The sandbox environment outside the Agent. It owns authoritative world and activity facts, produces normalized external events, and applies world-side effects; relative to the Agent it occupies a role analogous to the user in chat.
_Avoid_: Agent mind, WorldStage, clock

**World Stage**:
The long-lived coordinator for one character's interaction with one sandbox world. It owns interaction pending state, deadlines, cancellation, plan queues, output routing, and settlement, but not authoritative world facts.
_Avoid_: World task, one-shot activity runner, Agent state

**World Clock**:
The time-driving mechanism inside the world subsystem. It wakes world tasks when registered times arrive but does not assign semantic meaning, construct character decisions, or call the Agent.
_Avoid_: World, scheduler policy, WorldStage

**Handling Process**:
一次明确处理意图下的认知过程，可以是输入预处理、批次回复、即时交互或认知维护。调用完成只表示该次处理结束，不自动代表输入已被正式回复消费。
_Avoid_: Entire interaction, implicit preprocessing phase, consume-all

**Handling Report**:
一次认知调用的结果，区分调用完成、取消或失败，并按处理意图表达预处理成果或输入消费事实。行动计划在处理期间单独交付，报告不决定交互计时器。
_Avoid_: Timer command, consume-all flag, Action Plan

**Action Plan**:
An immutable, ordered, independently complete description of what a character has decided to do.
_Avoid_: Reply, capability call

**Recall**:
角色在认知处理中检索与输入及上下文相关记忆的过程。召回结果与触发输入关联，召回完成不等于正式回复或消费该输入。
_Avoid_: RecallCompleted stimulus, reply completion, pending consumption

**Interaction Cognitive Context**:
一次交互使用的用户资料、近期对话、总结和召回内容，由该交互管理其使用与释放。释放临时内容不删除持久历史，取消单次处理也不等于结束交互。
_Avoid_: Pending queue, character-global mutable context, connection state

**Character State**:
The persistent state belonging to a character independently of any one user or interaction.
_Avoid_: Interaction state, relationship state

**Relationship State**:
The persistent private state belonging to one character-user relationship.
_Avoid_: Character state, global user state

**Song Knowledge**:
Normalized facts about a song that the character has accepted as usable knowledge, distinct from crawler cache, source pages, and download records.
_Avoid_: Crawl result, learning artifact

**Learned Song Experience**:
The character-owned fact and memory that a song has been learned, distinct from the technical job status and generated audio artifacts.
_Avoid_: Completed job, model artifact

**Coordination Stimulus**:
打字、选图等改变交互等待策略的刺激，本身不构成待回复正文。它对已有输入的影响由该场景的交互规则决定。
_Avoid_: User message, pending content

**Interaction Deadline**:
某次交互安排的到期事实，仅对仍然有效的安排有意义。到期不代表输入必然准备完成，也不等于已经决定开始回复。
_Avoid_: Pending container, automatic reply, obsolete timeout

**Non-Realtime Voice Message**:
A completed recorded message represented by `VoiceMessage`, optionally carrying controlled media and/or a final transcript. It is not a phone turn and never represents raw or unfinished audio frames.
_Avoid_: VoiceUtteranceFinal, realtime stream, audio packet

**Controlled Domain Reference**:
An immutable nominal identifier such as `MediaRef`, `EvidenceRef`, or `SourceRef`. It crosses the Agent boundary without exposing local paths, raw provider objects, or access credentials; existence and authorization are checked by the consuming port.
_Avoid_: File path, URL credential, provider object, arbitrary payload

**Client Touch Interaction**:
A client-aggregated touch on the character's Live2D surface, represented by one or more body regions and an optional measured click frequency. It is distinct from physical touch sensed by a toy.
_Avoid_: Gesture, pressure, toy sensor touch

**Dynamic Message Thread**:
An ordered, structured set of a dynamic post and its relevant comments with authorship, parent relationships, and one explicit reply target preserved.
_Avoid_: Concatenated prompt, list of anonymous strings

**Pending Settlement**:
A revision-protected, per-stimulus decision from a Handling Report that lists which considered pending stimuli are consumed and which remain pending. Completing the trigger request does not imply consuming every pending stimulus.
_Avoid_: Consume all, request completion status

**Agent-Owned State Change**:
角色自身记忆、知识、经验或关系内容的认知更新，与交互输入的排队和期限调整分别表达。
_Avoid_: Action Plan, pending settlement, timer update

**Post-Interaction Reflection**:
在回复结算或交互结束等时点进行的认知维护；交互流程决定触发时机，认知处理决定是否以及如何更新记忆、画像或总结。
_Avoid_: Lifecycle cleanup, Action Plan, automatic timer ownership

**输入准备完成**:
一条输入已完成必要的理解、对话保存和上下文更新，可以成为正式回复的依据。准备完成不等于已经回复或消费。
_Avoid_: Received, preprocessing computation finished, consumed

**待回复输入**:
已准备完成、尚未被正式回复消费的内容输入；它与仍在准备中的输入和仅改变等待策略的协调信号不同。
_Avoid_: Every received stimulus, raw pending, conversation history

**回复批次**:
准备一起考虑并回应的有序输入集合；开始回复时固定本批成员与依据，之后到达的内容属于下一等待批次。
_Avoid_: All interaction history, one handle call, one outgoing message

**输入接收顺序**:
内容进入一次交互的先后关系，不随图片理解、记忆检索或其他预处理的完成先后改变。
_Avoid_: Completion order, database insertion time
