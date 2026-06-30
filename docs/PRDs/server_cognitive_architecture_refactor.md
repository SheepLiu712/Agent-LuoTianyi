# 服务端认知架构重构 PRD

## 1. 背景

AgentLuo 当前服务端已经具备聊天、Live2D 触摸、TTS、图片理解、音乐知识、城市漫步、日程提醒和记忆写入等能力。但这些能力大多围绕现有聊天 pipeline 逐步叠加：

```text
WebSocket -> ChatInputEvent -> ChatStream -> TopicPlanner -> ExtractedTopic -> TopicReplier -> LuoTianyiAgent -> ChatResponse
```

这条链路适合「用户发一段消息，角色回复一段内容」，但不适合未来要支持的电话、箱庭生活、公开日记、空间、多角色、物理交互、注意力系统和更复杂的记忆系统。

当前主要问题：

1. 用户消息、触摸刺激、系统提醒、内部世界事件都被迫进入类似聊天话题的流程。
2. `ExtractedTopic` 被当成通用事件格式使用，导致触摸快回等行为语义不清晰。
3. `LuoTianyiAgent` 逐渐变成所有智能能力和部分基础设施的总门面。
4. `plugins/` 既包含外部能力，也包含核心事件和生活记忆来源，例如 schedule event store、citywalk memory ingestor。
5. 记忆以向量检索为主，但缺少权威记忆实体和未来图结构扩展边界。
6. 回复生成同时承担计划、注意力选择、知识整合和角色扮演，长期会变成难维护的 prompt 巨块。

本次重构的目标不是一次性实现所有未来功能，而是先建立清晰的服务端认知运行时骨架，并让现有聊天流程作为兼容路径继续工作。

## 2. 目标

第一阶段目标：

1. 完全兼容现有客户端协议和用户体验。
2. 明确服务端长期分层：用户界面层、表意识层、潜意识层、箱庭/外环境层、能力层。
3. 引入统一输入刺激模型 `Stimulus`，让聊天、触摸、电话、物理交互、系统提醒和箱庭事件有共同入口。
4. 将旧聊天 pipeline 定位为兼容适配器，而不是未来核心抽象。
5. 明确多角色模型：每个角色状态完全独立，用户每条消息明确发给一个或多个角色。
6. 明确记忆架构：`MemoryRecord` 是权威正本，向量索引和图索引是投影。
7. 明确回复生成架构：计划/注意力选择与风格化角色输出分离。
8. 为箱庭、电话、AgentState、公开日记/空间预留架构位置，但第一阶段不强行实装。

## 3. 非目标

第一阶段不做以下事情：

1. 不修改桌面端或移动端协议。
2. 不实装完整电话功能。
3. 不实装完整箱庭模拟。
4. 不设计最终全局 AgentState 数值体系。
5. 不把 citywalk 的 mood/energy 迁移为全局 AgentState。
6. 不一次性替换完整聊天 pipeline。
7. 不一次性迁移全部历史记忆数据。

## 4. 架构原则

### 4.1 外部协议稳定，内部语义重建

现有 `/chat_ws`、`WSEventType`、`ChatResponse`、登录、history、图片、TTS、唱歌必须保持兼容。外部 WebSocket 消息进入服务端后，应先转成内部 `Stimulus`，再由 legacy adapter 转回旧 `ChatInputEvent`。

### 4.2 聊天 pipeline 是一个场景，不是智能体核心

文本聊天只是用户界面层的一种通道。未来电话、物理交互、Live2D 触摸、系统提醒、箱庭生活事件都不应伪装成聊天话题。

### 4.3 角色是第一类对象

每个角色拥有完全独立的：

1. 角色配置 `CharacterProfile`
2. 记忆命名空间
3. 状态机
4. 语音和 Live2D 映射
5. 行动策略

用户每条消息必须明确目标角色。第一阶段默认目标角色为 `luotianyi`，用于兼容现有客户端。

### 4.4 记忆正本与索引分离

`MemoryRecord` 是权威记忆实体。向量库负责模糊语义召回，图结构负责实体、事件、时间线、因果和关联扩展。任何索引都可以重建，不应成为唯一正本。

### 4.5 Planning 与 Realization 分离

计划层回答「现在应该关注什么、做什么」。风格化输出层回答「以某个角色应该怎么说、怎么表现」。角色扮演不应和注意力选择、行动计划、记忆筛选全部塞进一次 LLM 调用。

## 5. 目标分层

### 5.1 用户界面层 interface

职责：

1. WebSocket、HTTP、未来电话、物理设备协议适配。
2. 认证、ACK、错误响应。
3. 将外部 payload 转换为内部 `Stimulus`。
4. 将内部 `ResponseEnvelope` 转换为通道需要的输出格式。

不负责：

1. 角色如何理解用户。
2. 是否写入记忆。
3. 是否生成话题。
4. 是否触发主动行为。

### 5.2 表意识层 consciousness

职责：

1. 注意力选择。
2. 行动计划。
3. 具体回复策略。
4. 将计划交给风格化输出模块。

长期目标流程：

```text
Stimulus + MemoryContext + AgentState + WorldContext
  -> AttentionFrame
  -> ActionPlan
  -> CharacterRealization
  -> ResponseEnvelope
```

### 5.3 潜意识层 subconscious

职责：

1. 记忆检索和写入。
2. 记忆转储和结构化。
3. 用户画像。
4. 角色状态机。
5. 兴趣点和注意力候选。
6. 关系、偏好、长期计划。

第一阶段可先建立接口和类型，不要求替换现有 `memory/`。

### 5.4 箱庭/外环境层 world

职责：

1. 内部箱庭世界。
2. 外部世界事件采集和归一化。
3. 城市漫步、B站动态、小红书、地图等 provider。
4. 公开日记和空间内容的来源。

第一阶段不实装箱庭，但要明确 `schedule`、`citywalk` 在架构上属于 world provider，而不是核心聊天插件。

### 5.5 能力层 capabilities

职责：

1. LLM
2. TTS
3. 视觉
4. 音乐
5. 地图
6. 搜索
7. 语音识别
8. 抓取器

能力层只提供能力，不拥有认知流程。

## 6. 核心领域对象

### 6.1 Stimulus

统一输入刺激。

关键字段：

```text
stimulus_id
source_channel
modality
sender_user_id
target_character_ids
payload
text
client_msg_id
timestamp_ms
ephemeral
persist_policy
raw_event_type
```

示例：

1. 用户文本：`source_channel=websocket`，`modality=text`，`persist_policy=conversation_and_memory_candidate`
2. 用户图片：`modality=image`
3. Live2D 触摸：`modality=touch`，`ephemeral=true`
4. 电话语音片段：`source_channel=phone`，`modality=voice`
5. 箱庭事件：`source_channel=world`，`modality=world_event`

### 6.2 InteractionTurn

可记录的用户-角色交互。不是所有 `Stimulus` 都会生成 `InteractionTurn`。触摸快回、心跳、typing 等不应默认进入聊天记录。

### 6.3 Topic

仅表示需要语义理解和深度回复的聊天话题。旧 `ExtractedTopic` 暂时保留，但应定位为 legacy pipeline 内部对象。

### 6.4 ActionPlan

表意识输出的结构化计划。

可包含：

1. `say`
2. `sing`
3. `change_expression`
4. `live2d_motion`
5. `write_memory`
6. `write_diary`
7. `ask_followup`
8. `no_reply`
9. `call_capability`

### 6.5 ResponseEnvelope

内部输出包。最终由 channel adapter 转成现有 `ChatResponse` 或未来电话流式输出。

### 6.6 CharacterProfile

角色配置。

关键字段：

```text
character_id
display_name
persona_ref
speaking_style_ref
voice_profile
live2d_profile
memory_namespace
default_target
enabled
metadata
```

第一阶段默认存在 `luotianyi`。

### 6.7 AgentState

角色全局状态的预留接口。

注意：

1. 第一阶段不强行实装。
2. citywalk 内部 mood/energy 是小游戏局部状态，不能作为全局 AgentState。
3. 未来 AgentState 应服务于全局行动倾向、可打扰程度、情绪、连接需求和长期计划。

### 6.8 MemoryRecord

权威记忆实体。

建议字段：

```text
id
owner_character_id
subject_user_id
memory_type
visibility
source
content
summary
importance
confidence
emotional_valence
created_at
happened_at
last_accessed_at
metadata
```

必须支持的记忆类型：

1. `user_profile`
2. `user_fact`
3. `interaction_event`
4. `agent_life`
5. `world_event`
6. `diary_source`
7. `public_diary`
8. `song_knowledge`
9. `character_setting`

索引投影：

```text
MemoryChunk -> vector index
MemoryEdge -> graph index
```

检索流程：

```text
query -> vector recall -> type/visibility/character filter -> graph expansion -> rerank -> MemoryContext
```

### 6.9 PublicPost

公开日记/空间内容。默认所有用户可见，不属于某个用户私有聊天记忆。

## 7. 第一阶段改造范围

### 7.1 新增领域模型

新增 `server/src/domain/`：

1. `stimulus.py`
2. `character.py`
3. `memory_record.py`
4. `action.py`

### 7.2 新增运行时骨架

新增 `server/src/runtime/`：

1. `character_registry.py`
2. `__init__.py`

第一阶段只提供默认 `luotianyi` 角色。

### 7.3 新增 legacy adapter

新增 `server/src/legacy/`：

1. `chat_input_adapter.py`

职责：

1. `WSMessage -> Stimulus`
2. `Stimulus -> ChatInputEvent`

现有 `WebSocketService.convert_to_chat_input_event` 改为通过 adapter 实现，保持外部返回行为不变。

### 7.4 标注触摸快回语义

第一阶段不必彻底移除 `ExtractedTopic` 快回路径，但需要在 `Stimulus` 层明确：

```text
modality=touch
ephemeral=true
persist_policy=ephemeral_only
```

后续阶段再将触摸从 `TopicPlanner` 剥离到 reflex path。

### 7.5 记忆接口先显式类型化

第一阶段新增 `MemoryRecord` 类型，不立即替换现有向量写入。后续新增写入接口时，必须显式传入 `memory_type`、`owner_character_id`、`visibility`。

## 8. 迁移路线

### M1：领域模型与 PRD

产物：

1. 本 PRD。
2. `domain` 模型。
3. `CharacterRegistry`。
4. legacy adapter。

验收：

1. 现有测试通过或至少相关 adapter 测试通过。
2. WebSocket 输入转换行为不变。

### M2：触摸快回剥离

目标：

1. 触摸不再伪装成 `ExtractedTopic`。
2. 新增 reflex responder。
3. 快回不入库、不走记忆、不进入 planner。

### M3：记忆正本与索引

目标：

1. 新增 MemoryRecord 正本存储。
2. 向量库改为 MemoryChunk 索引。
3. 预留 MemoryEdge 图索引。

### M4：Planning 与 Realization 分离

目标：

1. 新增 planner 输出 `ActionPlan`。
2. main_chat 逐步拆成 action planning 和 character realization。

### M5：World 层占位和迁移

目标：

1. schedule/citywalk 作为 world provider。
2. world event 不直接推入 chat stream。
3. 由 runtime 决定是否转成主动刺激。

### M6：公开日记/空间

目标：

1. 新增 PublicPost 模型。
2. 箱庭/生活事件可生成公开日记草稿。
3. 对所有用户公开展示。

### M7：电话和多角色

目标：

1. 新增 phone channel adapter。
2. 每条用户消息携带目标角色列表。
3. 多角色状态和记忆完全独立。

## 9. 测试策略

当前烟测试仍保留，但新架构必须提高可测试性。

### 9.1 领域模型测试

测试内容：

1. `Stimulus` 默认字段。
2. 触摸刺激的 ephemeral policy。
3. 默认角色 registry。
4. MemoryRecord 类型和可见性。

特点：不依赖 DB、Redis、LLM、TTS。

### 9.2 协议契约测试

测试内容：

1. 现有 WebSocket payload 转换后的 `ChatInputEvent` 不变。
2. USER_TEXT、USER_IMAGE、USER_TYPING、USER_TOUCH 兼容。
3. ACK 和 ChatResponse 外形不变。

### 9.3 Fake capability 测试

长期目标：

1. fake LLM
2. fake TTS
3. fake memory store
4. fake channel sink

通过替换端口接口测试流程，不 mock 深层内部函数。

### 9.4 回放测试

保存真实输入事件 JSON，回放到 adapter/runtime，断言内部 `Stimulus` 和输出计划类型。

## 10. 架构决策记录

### ADR-001：MemoryRecord 是正本，向量和图是索引

原因：

1. 向量嵌入适合模糊语义召回，但不适合作为权威数据源。
2. 图结构未来需要表达事件、实体、时间、因果和关系。
3. 正本和索引分离后，可以重建索引、替换向量库或增加图数据库。

决策：

1. `MemoryRecord` 存储权威内容。
2. `MemoryChunk` 负责向量索引。
3. `MemoryEdge` 负责图索引。
4. 检索输出统一为 `MemoryContext`。

### ADR-002：Planning 与 Realization 分离

原因：

1. 注意力选择、计划和角色扮演是不同任务。
2. 一次 LLM 调用同时处理所有任务会导致 prompt 复杂、不可控、难测试。
3. 多角色场景下，同一个计划可能需要不同角色进行不同表达。

决策：

1. Planning 输出结构化 `ActionPlan`。
2. Realization 根据 `ActionPlan + CharacterProfile` 生成风格化回复。
3. 旧 `main_chat` 第一阶段保留，后续逐步拆分。

### ADR-003：旧聊天 pipeline 是兼容路径

原因：

1. 当前客户端和功能必须稳定。
2. 直接替换完整 pipeline 风险过高。
3. 未来能力不应继续依赖 `ExtractedTopic`。

决策：

1. 第一阶段通过 adapter 接入旧 pipeline。
2. 新功能优先接入 `Stimulus -> runtime`。
3. `ExtractedTopic` 仅作为 legacy chat pipeline 内部对象。

## 11. 第一阶段验收标准

1. PRD 已写入 `docs/PRDs/`。
2. 服务端新增 `domain`、`runtime`、`legacy` 骨架。
3. WebSocket 到 `ChatInputEvent` 的转换通过 legacy adapter，外部行为保持兼容。
4. 默认角色 `luotianyi` 可通过 `CharacterRegistry` 获取。
5. 新增测试覆盖文本、图片、typing、触摸输入转换。
6. 不引入对真实 LLM、TTS、Redis、数据库的测试依赖。
