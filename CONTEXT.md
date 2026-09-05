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
The character's short-lived attention and unfinished cognitive intent within one interaction.
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

**Pending Settlement**:
A revision-protected, per-stimulus decision from a Handling Report that lists which considered pending stimuli are consumed and which remain pending. Completing the trigger request does not imply consuming every pending stimulus.
_Avoid_: Consume all, request completion status

**Agent-Owned State Change**:
An idempotent mutation of the character's own memory, knowledge, experience, or cognitive state performed inside the Agent boundary.
_Avoid_: Action Plan, stage database command

**Post-Interaction Reflection**:
Asynchronous cognitive maintenance performed by the Agent after a settlement checkpoint. A ReflectionPolicy evaluates Agent-owned conditions such as context size, while ledgers provide idempotent evidence of what actually happened.
_Avoid_: Action Plan, stage reflection worker
