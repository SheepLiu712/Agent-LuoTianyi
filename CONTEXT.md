# AgentLuo Domain Language

This glossary defines the project-specific language used when describing a character receiving stimuli, deciding what to do, and acting through different interaction carriers.

## Language

**Stimulus**:
A logical event that may be perceived by a character, after raw protocol messages and sensor samples have been normalized and aggregated.
_Avoid_: Raw event, packet, sensor sample

**Stimulus Source**:
The supplier-independent semantic origin explicitly supplied by the Adapter, Stage, or World that constructs a Stimulus. The Agent does not infer it from the stimulus kind, and delivery mechanisms such as World Clock do not overwrite it.
_Avoid_: Transport channel, inferred source, kind-source whitelist

**Agent Persistence Decision**:
The Agent-internal, idempotent decision about whether stimulus content enters conversation history or becomes long-term-memory evidence. It is derived while handling a stimulus and is not supplied by the external caller as part of the Stimulus.
_Avoid_: Stimulus PersistPolicy, stage persistence flag, Action Plan

**Interaction**:
A continuous period with a shared context and lifecycle. In the current Agent design it may be a character-user chat, a toy session, or one character's ongoing relationship with a sandbox world.
_Avoid_: Connection, user session

**Stage**:
The role that organizes one kind of interaction around the Agent boundary, including ordering, deadlines, cancellation, output binding, and settlement. ChatStage, ToyStage, and WorldStage may use different state machines.
_Avoid_: Global stage, universal BaseStage

**Interaction Snapshot**:
The immutable Chat, Toy, or World facts supplied directly with one handle request; no snapshot registry, persistence, or generic SnapshotRef is required. Interaction ID identifies the continuous interaction; interaction revision identifies the Stage-owned decision basis within it. Input details are defined in [the handle input SPEC](docs/项目说明/项目架构与接口（spec）/接口文档/domain/handle-input.md), currently a draft without implementation.
_Avoid_: Live Stage context, global state version, typing or image-selection state copies

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
One continuous act of understanding one or more pending stimuli, which may produce zero or more complete action plans before it ends.
_Avoid_: Half-finished reply, recall event loop

**Handling Report**:
The result of one handling call. It separately reports whether the request completed, was cancelled, or failed, and which considered pending stimuli were consumed or retained; action plans are emitted separately while handling is in progress.
_Avoid_: Consume-all flag, action plan, recall result

**Action Plan**:
An immutable, ordered, independently complete description of what a character has decided to do.
_Avoid_: Reply, capability call

**Recall**:
The character's internal act of retrieving memories relevant to the current stimulus and context; its completion resumes the current handling process.
_Avoid_: Context returned to stage, RecallCompleted stimulus

**Interaction Cognitive Context**:
The Agent-owned working context scoped by character and interaction, including selected conversation history, summaries, recalled memory results, attention, and unfinished cognitive intent. Conversation fragments and related recall results share retention, compression, and cleanup management. Cleanup does not delete durable conversation or memory records; cancelling one handle does not end the interaction.
_Avoid_: Chat queue, connection state, user profile

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
An ephemeral stimulus, such as user typing or image-selection state, that changes when the Agent should reconsider all pending content without itself becoming reply content.
_Avoid_: User message, pending content

**Interaction Deadline**:
A stage-generated coordination stimulus stating that the current immutable interaction snapshot must now be reconsidered. It does not carry or own pending content; the request snapshot does.
_Avoid_: Pending container, stage timer state, stimulus lookup request

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
An idempotent mutation of the character's own memory, knowledge, experience, or cognitive state performed inside the Agent boundary.
_Avoid_: Action Plan, stage database command

**Post-Interaction Reflection**:
Asynchronous cognitive maintenance performed by the Agent after a settlement checkpoint. A ReflectionPolicy evaluates Agent-owned conditions such as context size, while ledgers provide idempotent evidence of what actually happened.
_Avoid_: Action Plan, stage reflection worker
