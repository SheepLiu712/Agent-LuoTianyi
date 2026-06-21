# 服务端认知运行时设计文档

## 1. 当前重构目标

服务端正在从「聊天 pipeline 驱动」迁移到「认知运行时驱动」。

旧主线：

```text
WebSocket -> ChatInputEvent -> TopicPlanner -> TopicReplier -> LuoTianyiAgent
```

新主线：

```text
UserInterface Stimulus
  -> System ConversationService
  -> Runtime / CharacterRegistry
  -> Agent
  -> Subconscious Memory / Jargon / State
  -> Capabilities
  -> World Provider
  -> ResponseEnvelope / Legacy ChatResponse
```

第一阶段仍完全兼容现有客户端协议。旧聊天 pipeline 已拆分为更明确的 agent 行为模块和 system 会话模块，并由 legacy adapter 继续适配旧协议。

## 2. 模块归属

### 2.1 `domain`

位置：`server/src/domain`

职责：

1. 定义核心领域对象。
2. 不依赖 FastAPI、数据库、LLM、TTS。
3. 给 runtime、subconscious、world、user_interface、system 提供共同语言。

已建立对象：

1. `Stimulus`
2. `ActionPlan`
3. `PlannedAction`
4. `ResponseEnvelope`
5. `CharacterProfile`
6. `MemoryRecord`
7. 旧 `src.types.*` 中的协议/记忆/音乐/工具类型

### 2.2 `runtime`

位置：`server/src/runtime`

职责：

1. 统一持有角色注册表。
2. 初始化和获取表意识 agent。
3. 管理未来多角色 agent 实例。

当前实现：

1. `CharacterRegistry`
2. `AgentRuntime`
3. `init_agent_runtime`
4. `get_default_agent`

重要决策：

`LuoTianyiAgent` 不再是服务端全局初始化入口。服务端启动从 `runtime.agent_runtime` 初始化默认 agent。

### 2.3 `subconscious`

位置：`server/src/subconscious`

职责：

1. 记忆。
2. 术语/歌名实体召回。
3. 未来注意力候选。
4. 未来 AgentState 和兴趣点维护。

当前实现：

1. `SubconsciousMemory`
2. `MemoryUpdateService`
3. `SongEntityLinker`
4. `extract_song_entities`
5. `SongKnowledgeMemory`

旧模块迁移状态：

1. 记忆正本已经物理迁移到 `src.subconscious.memory.*`。
2. `src.memory.*` 旧目录已删除，新代码必须 import `src.subconscious.memory.*`。
3. `agent.jargon_retriver` 旧兼容文件已删除，歌名实体召回统一通过 `subconscious.jargon`。
4. `agent.chat.ingress` 已改为从 `subconscious.jargon` 获取歌名实体。
5. 歌曲事实和歌词检索通过 `subconscious.memory.song_knowledge` 暴露；底层暂时复用 `MusicManager` 的知识库实现。

### 2.4 `system`

位置：`server/src/system`

职责：

1. 应用级会话事实。
2. 用户消息和 agent 回复落库。
3. history 查询和 UI history 格式化。
4. 会话上下文读取和摘要更新。
5. 系统级数据库、Redis、向量库和知识图谱基础设施。

当前实现：

1. `ConversationManager`
2. `ConversationService`
3. `database/`
4. `chat_session/`
5. `workers/`

重要决策：

`LuoTianyiAgent` 不再负责消息落库和 history 查询。聊天记录是应用事实，记忆是从应用事实中提炼出的认知事实。

数据库正本目录已经从 `src.database.*` 移动到 `src.system.database.*`。旧 `src.database` 目录已删除，新代码必须通过 `system` 层访问数据库基础设施。

### 2.5 `user_interface`

位置：`server/src/system/user_interface`

职责：

1. HTTP/WebSocket 协议适配。
2. 认证、ACK、错误响应。
3. 将外部 payload 转成内部 `Stimulus`。
4. 将系统服务结果返回给客户端。

旧模块迁移状态：

`src.interface.*` 和顶层 `src.user_interface.*` 旧目录已删除，新代码必须使用 `src.system.user_interface.*`。

### 2.6 `capabilities`

位置：`server/src/capabilities`

职责：

1. Agent 可调用动作/技能执行层。
2. `speech.say` 调用 TTS 生成语音。
3. `singing.sing` 调用唱歌能力生成音频。
4. `CapabilityRegistry` 聚合动作能力，供 runtime、worker 和 agent 使用。

迁移状态：

1. `src.tts.*` 旧目录已删除，TTS 正本迁移到 `src.capabilities.speech.*`。
2. `plugins.music.singing_manager` 旧文件已删除，唱歌执行正本迁移到 `src.capabilities.singing.singing_manager`。
3. `plugins.music.music_manager` 暂时仍持有歌曲知识库底层实现；Agent 面向 `subconscious.memory.song_knowledge` 使用歌曲知识。

### 2.7 `world`

位置：`server/src/world`

职责：

1. 外部世界事件。
2. 内部箱庭事件。
3. 公开日记和空间的来源。
4. schedule、citywalk、未来小红书/地图 provider 的统一门面。

当前实现：

1. `WorldEvent`
2. `WorldEventProvider`
3. `ScheduleWorldProvider`
4. `PublicDiaryEntry`
5. `CitywalkDiaryProvider`

旧模块迁移状态：

1. `plugins.schedule` 暂时保留原位置。
2. `SystemRuntime` 新增 `world_event_provider`。
3. 新 runtime 代码应依赖 `world` facade，而不是直接依赖 schedule plugin。
4. `plugins.citywalk` 暂时保留原位置；其生成的 `citywalk_*.json` 报告通过 `CitywalkDiaryProvider` 暴露为公开日记和 `public_diary` 世界事件。
5. `SystemRuntime` 新增 `public_diary_provider`，用于后续空间/日记 API 或 runtime context 注入。

### 2.8 `legacy`

位置：`server/src/legacy`

职责：

1. 兼容旧聊天 pipeline。
2. 将旧协议对象转换为新领域对象，再转回旧 pipeline 需要的对象。

当前实现：

```text
WSMessage -> Stimulus -> ChatInputEvent
```

### 2.9 `agent.chat`

位置：`server/src/agent/chat`

职责：

1. 描述 agent 处理聊天刺激的一组行为。
2. 维护话题抽取、未读消息聚合、输入预处理和 topic reply 逻辑。
3. 仍适配旧 `ExtractedTopic` 流程，但不再作为服务端全局 pipeline 顶层目录存在。

当前实现：

1. `ChatInputEvent`
2. `UnreadStore`
3. `ListenTimer`
4. `TopicPlanner`
5. `TopicReplier`
6. `ingress_message`

### 2.10 `agent.reflex`

位置：`server/src/agent/reflex`

职责：

1. 处理不应进入长期聊天记忆和话题规划的瞬时刺激。
2. 当前覆盖 Live2D 触摸快回。
3. 后续可扩展为更多低成本、可丢弃、可不落库的即时反射动作。

当前实现：

1. `TouchFastReplyBuilder`
2. `TouchReflexResponder`

## 3. 数据库迁移

### 3.1 旧表保留

旧 `memory_records` 表不删除、不改语义，避免破坏历史数据和已有逻辑。

### 3.2 新正本表

新增：

1. `agent_memory_records`
2. `memory_chunks`
3. `memory_edges`

含义：

`agent_memory_records` 是记忆正本。  
`memory_chunks` 是向量索引投影。  
`memory_edges` 是图结构投影。

### 3.3 写入路径

现有 `MemoryWriter.write_user_memory` 和 `write_event_memory` 仍写向量库，同时会同步写入 `agent_memory_records`。

映射规则：

```text
write_user_memory  -> MemoryType.USER_FACT
write_event_memory -> MemoryType.INTERACTION_EVENT
```

默认 owner character：

```text
luotianyi
```

后续多角色实现时，写入接口必须显式传入 `owner_character_id`。

## 4. 表意识 agent 边界

`LuoTianyiAgent` 现在应被理解为：

```text
洛天依这个角色的表意识入口
```

它不再负责：

1. 全局 agent 初始化。
2. 全局 agent 获取。
3. 多角色注册。

这些职责已经移入 `runtime.agent_runtime`。

它暂时仍保留较多旧职责，包括：

1. history API 数据组装。
2. 对话持久化。
3. TTS/Sing 代理。
4. topic reply pipeline 方法。

这些将在后续阶段继续拆分。

## 5. 记忆接口边界

后续新代码不要直接调用旧 `src.memory.*` 路径；该目录已经删除。

推荐调用：

```python
agent.subconscious_memory
agent.memory_updates
```

或在 runtime 层直接注入：

```python
SubconsciousMemory
MemoryUpdateService
```

所有记忆变更必须经过 `MemoryUpdateService`，包括：

1. 写用户事实。
2. 写交互事件。
3. 对话后处理。
4. 更新用户画像。

## 6. 测试策略

当前新增构造测试：

1. `test_cognitive_runtime_adapters.py`
2. `test_cognitive_memory_persistence.py`
3. `test_world_schedule_provider.py`
4. `test_subconscious_layer.py`
5. `test_agent_runtime.py`

覆盖内容：

1. WebSocket 旧协议兼容。
2. Stimulus 转换。
3. 默认角色注册。
4. 新 MemoryRecord 正本表创建。
5. MemoryWriter 同步写正本。
6. schedule 事件转 WorldEvent。
7. jargon 迁移到 subconscious。
8. 记忆更新统一入口。
9. runtime 初始化默认表意识 agent。

测试原则：

1. 尽量使用 fake LLM/TTS/vector store。
2. 构造测试不依赖真实外部服务。
3. 旧烟测试继续保留，用于验证真实服务运行。

## 7. 后续重构顺序

### 7.1 触摸快回剥离

目标：

```text
USER_TOUCH -> Stimulus(ephemeral) -> ReflexResponder -> ChatResponse
```

不再进入：

```text
TopicPlanner -> ExtractedTopic -> TopicReplier
```

### 7.2 Planning / Realization 拆分

目标：

```text
Topic + MemoryContext + WorldContext
  -> ActionPlan
  -> CharacterRealization
  -> ResponseEnvelope
```

`MainChat` 后续拆为：

1. `ReplyPlanner`
2. `CharacterRealizer`

### 7.3 MemoryRecord 正本读路径

当前新正本已写入，但检索仍主要依赖向量 store。

下一步：

1. vector result metadata 反查 `agent_memory_records`。
2. 返回 `MemoryContext`。
3. 引入 `memory_edges` 做图扩展。

### 7.4 world provider 迁移

后续将：

1. schedule event store 迁到 world 语义下。
2. citywalk 暴露为 world provider。
3. 日记和空间基于 world event / agent life memory 生成。

### 7.5 多角色

后续每条用户消息必须包含目标角色。

兼容策略：

1. 旧客户端默认目标为 `luotianyi`。
2. 新客户端可传 `target_character_ids`。
3. 每个角色拥有独立 `owner_character_id`、memory namespace 和 AgentState。

## 8. 当前完成状态

已完成：

1. PRD。
2. domain 骨架。
3. runtime agent 初始化入口。
4. subconscious memory/jargon facade。
5. world schedule facade。
6. legacy chat adapter。
7. 新 MemoryRecord 正本表。
8. 现有记忆写入同步正本。
9. 构造测试。

未完成：

1. 触摸快回完全剥离。
2. MainChat planning/realization 拆分。
3. MemoryRecord 正本读路径。
4. 图索引实际构建。
5. citywalk 完全 world provider 化。
6. 公开日记/空间实现。
7. 多角色运行时完整分发。
## 9. 2026-06-20 Conscious Layer Implementation Update

This update adds the first concrete conscious-layer boundary without changing
the client protocol.

The concrete modules now live under `server/src/agent`, because they describe
the conscious behavior of an agent rather than a separate top-level subsystem.

Implemented modules:

1. `AttentionPlanner`
2. `TopicAttentionPlan`
3. `ResponseRealizer`
4. `UserExpressionContext`

The legacy chat turn now has this shape:

```text
ExtractedTopic
  -> LuoTianyiAgent.plan_topic_turn_for_pipeline
  -> AttentionPlanner.plan_topic_turn
  -> TopicAttentionPlan
  -> LuoTianyiAgent.realize_topic_plan_for_pipeline
  -> ResponseRealizer.realize_topic_plan
  -> MainChat.generate_response
  -> OneResponseLine[]
```

`TopicReplier` no longer directly orchestrates memory search, fact search, or
sing planning in its main reply path. It keeps transport sequencing,
conversation persistence, speaking queue submission, and asynchronous side
effects.

The split means:

1. Attention/planning owns what to look at: topic text, retrieved memories,
   song facts, external schedule context, and coarse `ActionPlan`.
2. Realization owns how to say it: persona, speaking style, preferences, tone
   mapping, expression mapping, and the legacy response line format.
3. `MainChat` is still the current realization backend. It has not yet been
   fully decomposed internally, but it is no longer the place where the whole
   turn plan is assembled.

New tests:

```text
server/tests/test_conscious_layer.py
```

Verified behaviors:

1. `AttentionPlanner` merges external context, retrieves memory/facts,
   resolves sing plans, and builds `ActionPlan`.
2. `ResponseRealizer` delegates style generation to `MainChat` without
   performing planning itself.

Updated remaining work:

1. Touch fast replies should still be moved out of `ExtractedTopic` into a
   true reflex path.
2. `MainChat` can now be further split internally into prompt assembly,
   structured response parsing, and style realization.
3. Dead compatibility helpers in `TopicReplier` can be removed once no callers
   depend on the old helper methods.
4. `TopicAttentionPlan` should later accept world events and AgentState
   snapshots directly, not only schedule text.

## 10. 2026-06-20 Reflex Path Implementation Update

Touch fast replies have been moved out of the topic reply path.

New package:

```text
server/src/agent/reflex
```

Implemented modules:

1. `TouchFastReplyBuilder`
2. `TouchReflexResponder`

The touch flow is now:

```text
ChatInputEvent(USER_TOUCH)
  -> system.chat_session.ChatStream.touch_reflex.try_reply
  -> ChatResponse(display_in_chat=False, is_ephemeral=True)
```

If the reflex cannot answer because probability rejects it or no local audio is
available, the event falls back to the legacy path:

```text
TopicPlanner._handle_touch_event
  -> ExtractedTopic
  -> TopicReplier
```

This preserves compatibility while making the intended semantics explicit:
simple Live2D touches are transient stimuli, not memories, not chat records,
and not necessarily topics.

The old `server/src/pipeline/modules/touch_fast_reply.py` compatibility wrapper
has been removed with the top-level pipeline package.

New tests:

```text
server/tests/test_touch_reflex.py
```

Verified behaviors:

1. Touch audio produces ephemeral `ChatResponse` objects.
2. Non-normal expressions are reset to `normal`.
3. Touch reflex handles touch events before the topic pipeline.
4. Missing audio cleanly falls back to the legacy topic path.
5. Non-touch events are ignored by the reflex layer.

## 11. 2026-06-20 Typed Memory Recall Update

Canonical memory write had already been introduced through:

```text
agent_memory_records
memory_chunks
memory_edges
```

This update adds the matching typed read boundary.

New domain objects:

```text
MemoryHit
MemoryContext
```

Current recall flow:

```text
AttentionPlanner
  -> LuoTianyiAgent.search_memory_context_for_topic
  -> SubconsciousMemory.search_memory_context_for_topic
  -> vector_store.search
  -> MemoryChunkRecord.embedding_id
  -> AgentMemoryRecord
  -> MemoryContext
```

Compatibility rule:

1. If a vector result maps to `agent_memory_records`, the planner receives a
   typed `MemoryHit(record=MemoryRecord, ...)`.
2. If it does not map to a canonical record, it remains a legacy vector hit
   with `record=None`.
3. `MemoryContext.render_for_prompt()` preserves the old string-list behavior
   for `MainChat`.

This answers the current MemoryRecord design question:

1. `MemoryRecord` is the source of truth.
2. Vector embeddings are retrieval indexes, represented by `memory_chunks`.
3. Future graph associations belong in `memory_edges`, pointing back to
   `MemoryRecord` ids.
4. Planning code should consume `MemoryContext`, not raw strings, so it can
   distinguish user facts, interaction events, world memories, diary sources,
   public diary records, and character settings.

New/updated tests:

```text
server/tests/test_subconscious_layer.py
server/tests/test_cognitive_memory_persistence.py
server/tests/test_conscious_layer.py
```

Verified behaviors:

1. Canonical records can be retrieved by vector embedding id.
2. `SubconsciousMemory` returns typed `MemoryContext`.
3. `AttentionPlanner` keeps typed memory context while rendering strings for
   the legacy prompt backend.

## 12. 2026-06-20 Multi-Character Runtime Update

Runtime now creates one conscious agent instance per registered
`CharacterProfile`.

Current flow:

```text
CharacterRegistry.characters
  -> AgentRuntime.init_agent_runtime
  -> conscious_agents[character_id]
```

Compatibility rule:

1. Existing server startup still registers only `luotianyi` by default.
2. `get_default_agent()` still returns the default Luo Tianyi agent for legacy
   `SystemRuntime.agent` callers.
3. New code can call `AgentRuntime.get_agent(character_id)` to get the target
   character agent.

Memory ownership update:

1. `LuoTianyiAgent` now receives a `CharacterProfile`.
2. Its `AttentionPlanner` target id is the profile character id.
3. Its `SubconsciousMemory` carries `owner_character_id`.
4. `MemoryManager` and `MemoryWriter` accept `owner_character_id`, so canonical
   `agent_memory_records.owner_character_id` can be scoped per character.

Still pending:

1. `system.chat_session.ChatStream`, `agent.chat.TopicPlanner`, and
   `agent.chat.TopicReplier` still route through `SystemRuntime.agent`, so they
   use the default agent when no target is supplied.
2. The next migration should route each `Stimulus.target_character_ids` through
   `AgentRuntime`.
3. Character-specific persona/prompt config is represented by
   `CharacterProfile`, but `MainChat` still loads the current Luo Tianyi prompt
   files. Real multi-character roleplay needs prompt/profile selection in the
   realization backend.

New/updated tests:

```text
server/tests/test_agent_runtime.py
server/tests/test_cognitive_memory_persistence.py
```

Verified behaviors:

1. Runtime creates independent agent instances for multiple registered
   characters.
2. Default agent lookup remains compatible.
3. Canonical memory writes can be scoped to a non-default `owner_character_id`.

## 13. 2026-06-20 Legacy Target Routing Update

The legacy chat path now carries target character ids far enough to choose the
conscious agent for a topic.

Current flow:

```text
WSMessage.payload.target_character_id / target_character_ids
  -> Stimulus.target_character_ids
  -> ChatInputEvent.payload.target_character_ids
  -> UnreadMessage.target_character_ids
  -> ExtractedTopic.target_character_ids
  -> TopicReplier._agent_for_topic
  -> AgentRuntime.get_agent(character_id)
```

Compatibility rule:

1. Missing targets default to `("luotianyi",)`.
2. Unknown targets fall back to `SystemRuntime.agent`, which is the default
   character agent.
3. Multi-target topics currently route to the first target only. The data model
   preserves the full tuple so future multi-character replies can fan out.

Updated tests:

```text
server/tests/test_cognitive_runtime_adapters.py
server/tests/test_topic_replier_routing.py
```

Verified behaviors:

1. Legacy adapter payload target ids survive into `UnreadMessage`.
2. `TopicReplier` selects the target character's agent from `AgentRuntime`.
3. Unknown character ids fail soft to the default agent.

## 14. 2026-06-20 AgentState Boundary Update

Global character state now has its own domain model and subconscious service.

New domain object:

```text
AgentState
```

Current fields:

1. `mood`
2. `arousal`
3. `vitality`
4. `connection_need`
5. `attention_bias`

All scalar fields are normalized to `[0.0, 1.0]`. The names are intentionally
not the same as citywalk state fields.

New subconscious service:

```text
SubconsciousState
```

Current flow:

```text
LuoTianyiAgent
  -> SubconsciousState(owner_character_id)
  -> AgentState snapshot
  -> AttentionPlanner.plan_topic_turn(agent_state=...)
  -> TopicAttentionPlan.agent_state
```

Important boundary:

1. `CitywalkState` remains a temporary minigame/session state.
2. `AgentState` is the global character state for planning and future state
   maintenance.
3. Each conscious agent owns an independent `SubconsciousState`.
4. Persistence is not implemented yet; the service is currently in-memory so
   the architectural boundary can stabilize before adding storage.

New/updated tests:

```text
server/tests/test_agent_state.py
server/tests/test_conscious_layer.py
```

Verified behaviors:

1. AgentState metrics are clamped to `[0.0, 1.0]`.
2. State services are independent per character.
3. State snapshots reject owner mismatches.
4. `AttentionPlanner` preserves `AgentState` in `TopicAttentionPlan`.

## 15. 2026-06-21 MainChat Realization Split

`MainChat` has been cleaned up into a smaller realization backend.

New conscious-layer realization components:

```text
RealizationPromptAssembler
RealizationPromptInput
StructuredResponseParser
```

Current flow:

```text
ResponseRealizer
  -> MainChat.generate_response
  -> RealizationPromptAssembler.build
  -> LLMModule.generate_response
  -> StructuredResponseParser.parse
  -> OneResponseLine[]
```

Responsibilities after the split:

1. `RealizationPromptAssembler` builds prompt variables from topic, user
   context, retrieved facts/memories, and sing plan.
2. `StructuredResponseParser` parses `[tone] text` and `[sing] song` lines into
   legacy `OneSentenceChat` / `SongSegmentChat` objects.
3. `MainChat` owns only static variable loading, tone mapping, LLM invocation,
   and compatibility response types.

Encoding note:

PowerShell commands should explicitly use UTF-8 when inspecting or editing this
project, because Windows' default console encoding can display UTF-8 Chinese as
mojibake. `server/src/agent/main_chat.py` has been rewritten as clean UTF-8.

New/updated tests:

```text
server/tests/test_response_realization_components.py
```

Verified behaviors:

1. Prompt variables preserve legacy prompt inputs.
2. Structured tone lines become `OneSentenceChat`.
3. Matching sing lines become `SongSegmentChat`.
4. Unstructured model output falls back to the default response.

## 16. 2026-06-21 Import and Directory Ownership Update

The server source now uses `src.*` absolute imports for project modules. This
keeps imports readable as the tree becomes deeper and avoids fragile relative
paths between agent, subconscious, system, world, and capability layers.

Directory ownership changes:

1. `src.types.*` was merged into `src.domain.*`.
2. `src.user_interface.*` moved under `src.system.user_interface.*`.
3. `src.reflex.*` moved under `src.agent.reflex.*`.
4. Top-level `src.pipeline.*` was removed.
5. Agent behavior pieces moved to `src.agent.chat.*`.
6. Session orchestration moved to `src.system.chat_session.*`.
7. Global worker infrastructure moved to `src.system.workers.*`.

Compatibility note:

Existing client protocol remains unchanged. The movement is an internal module
ownership change; old WebSocket events, history APIs, and `ChatResponse`
payloads are still served through the system user-interface layer.

## 17. 2026-06-21 SystemRuntime Startup Ownership Update

The previous shared dependency container has been replaced by `SystemRuntime`.

New canonical module:

```text
server/src/system/system_runtime.py
```

`SystemRuntime` now owns application startup and shutdown:

1. database initialization
2. TTS and capability initialization
3. agent runtime initialization
4. conversation service initialization
5. websocket/chat-session/worker singleton wiring
6. schedule and world provider wiring
7. daily scheduler startup
8. account key generation
9. background service shutdown

`server_main.py` now only defines the FastAPI app, routes, rate limiting, and
dependency access. Its lifespan delegates to:

```python
init_system_runtime(config)
shutdown_system_runtime()
```

This makes `system` the owner of application software services, while agent,
subconscious, capabilities, and world remain runtime dependencies used by the
system.
