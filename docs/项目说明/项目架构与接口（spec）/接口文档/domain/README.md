# domain 对外接口

## 模块职责

`server/src/domain` 只定义跨模块传递的数据和领域词汇，不访问数据库、网络、模型或文件。其他模块可以依赖 `domain`；`domain` 不应反向依赖它们。

## 对外接口

### 输入与响应

- `src.domain.agent`：当前 Agent 强类型领域协议的公开导入路径。本切片公开 `TextMessage`、`StimulusKind`、`StimulusSource` 和与旧协议共用的 `PersistPolicy`。
- `TextMessage`：用户已提交的一条完整文字消息。构造字段为 `stimulus_id: str`、`schema_version: int`、`occurred_at: datetime`、`source: StimulusSource`、`target_character_ids: tuple[str, ...]`、`user_id: str | None`、`persist_policy: PersistPolicy`、`ephemeral: bool`、`text: str` 和 `client_msg_id: str`；`kind` 不由调用方传入，始终为 `StimulusKind.TEXT_MESSAGE`。
- `StimulusKind.TEXT_MESSAGE`：当前已实现强类型 Stimulus 的稳定判别值。
- `StimulusSource.USER`：表示该领域事实由用户行为产生，不表示 WebSocket、HTTP 等传输通道。
- `PersistPolicy`：新旧 Stimulus 协议共用的同一四成员枚举；可从 `src.domain.agent`、`src.domain.stimulus` 和 `src.domain` 导入，不是三套独立类型。
- `Stimulus`：系统收到的一次刺激。主要字段为 `source_channel`、`modality`、`payload`、`text`、`sender_user_id`、`target_character_ids`、`client_msg_id`、`persist_policy` 和 `ephemeral`。
- `SourceChannel`、`StimulusModality`、`PersistPolicy`：分别限定刺激来自哪里、是什么形式、允许怎样持久化。
- `Stimulus.targets_character(character_id)`：判断刺激是否发给指定角色。
- `Stimulus.should_persist_conversation()`：判断是否应写入对话记录。
- `Stimulus.can_be_memory_candidate()`：判断是否允许进入长期记忆候选流程。
- `ActionPlan`：Agent 对一次刺激给出的动作计划，包含目标角色和一组 `PlannedAction`。
- `PlannedAction`：一个待执行动作；`ActionType` 包含说话、唱歌、表情、动作、写记忆、调用能力和不回复等类型。
- `ResponseEnvelope`：向指定渠道和用户发送的通用响应包装。

### 对话流水线数据

- `ChatInputEvent`、`ChatInputEventType`：当前 stage 使用的规范化聊天输入。
- `UnreadMessage`、`UnreadMessageSnapshot`：尚未组成完整话题的消息及其快照。
- `ExtractedTopic`：从若干输入中提取出的完整话题。
- `ConversationItem`：对话上下文中的一条记录。
- `SpeakingCommand`：交给语音执行部分的一条说话命令。

### 角色和状态

- `CharacterProfile`：角色静态配置，包括角色 ID、显示名、记忆命名空间、人格和声音配置等。
- `CharacterName`：当前已知角色名称枚举。
- `AgentState`：角色当前的情绪、唤醒度、活力、连接需求等状态。
- `AgentState.with_updates(**changes)`：返回应用修改后的新状态，不原地改变原对象。

### 记忆与知识

- `MemoryRecord`、`MemoryType`、`MemoryVisibility`：长期记忆记录及其分类。
- `MemoryHit`、`MemoryContext`：记忆检索结果和提供给回复阶段的记忆上下文。
- `MemoryUpdateCommand`：写入或修改记忆的命令。
- `Entity`、`Relation`、`GraphNode`、`KnowledgeItem`、`GraphEntityType`、`GraphRelationType`：知识图谱和事实检索使用的数据及枚举。

### 音乐与工具

- `WishEntry`、`SongMetadata`、`SongSegment`、`OneLyricLine`：歌曲愿望、元数据、片段和歌词行。
- `MyTool`、`ToolFunction`、`ToolOneParameter`：模型工具调用的声明数据。
- `PlanningStep`、`ReplyIntensity`、`SingingAction`：当前规划和回复实现共享的计划步骤、强度与演唱动作数据。

根路径完整公开名称以 `server/src/domain/__init__.py` 的导出为准；Agent 强类型领域协议当前从 `src.domain.agent` 导入。

## 正常与异常行为

- 创建这些对象只做字段校验和默认值生成，不产生外部副作用。
- `TextMessage` 构造后不可变，不提供任意 `payload` 扩展口，并逐项保留调用方提供的公共字段和文字消息专有字段。
- 当前契约测试只锁定合法样例：`source=USER`、`persist_policy=CONVERSATION_AND_MEMORY_CANDIDATE`、`ephemeral=False`。本切片尚未实现 source/persist/ephemeral 组合校验，因此其他组合当前不会按目标 spec 稳定返回 `CONTRACT_INVALID_STIMULUS`；调用方不得把这种暂未校验视为受支持行为。
- 枚举值和字段名属于跨模块协议；修改时必须先更新 spec 和消费者测试。
- `Stimulus` 默认不持久化。调用方必须显式选择 `PersistPolicy`，不能仅凭消息来源猜测。
- 构造参数不合法时由 dataclass、枚举或 Pydantic 抛出类型/校验异常，调用方不应静默吞掉。

## 使用示例

假设 WebSocket 收到一条文字消息：Adapter 先生成 `Stimulus`，stage 根据其持久化策略保存消息，再把规范化输入交给 Agent；Agent 的结果最终可用 `ActionPlan` 或现有回复对象表达。整个过程中，各模块共享的是这里的数据，而不是彼此的内部对象。

## 应覆盖的契约场景

- `TextMessage` 从 `src.domain.agent` 构造后固定为 `TEXT_MESSAGE`，逐项保留全部字段、拒绝赋值修改且不存在 `payload`。
- `src.domain.agent`、`src.domain.stimulus` 和 `src.domain` 导出的 `PersistPolicy` 是同一个四成员枚举对象。
- 不同 `PersistPolicy` 下，`should_persist_conversation()` 和 `can_be_memory_candidate()` 返回预期结果。
- `AgentState.with_updates(...)` 返回新对象且不修改原状态。
- 未指定目标角色、时间或 ID 时，默认值稳定且可序列化。
