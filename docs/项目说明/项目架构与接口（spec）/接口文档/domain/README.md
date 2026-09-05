# domain 对外接口

## 模块职责

`server/src/domain` 只定义跨模块传递的数据和领域词汇，不访问数据库、网络、模型或文件。其他模块可以依赖 `domain`；`domain` 不应反向依赖它们。

## 对外接口

### 输入与响应

- `src.domain.agent`：当前 Agent 强类型领域协议的公开导入路径。当前实现公开 `TextMessage`、`StimulusKind`、`StimulusSource` 和迁移期兼容的 `PersistPolicy`；目标 interface 将从强类型 Stimulus 构造参数和该包公开导出中移除 `PersistPolicy`。
- `TextMessage`：用户已提交的一条完整文字消息。当前实现的构造字段仍包含 `persist_policy: PersistPolicy`；这是 PR #90 已实现、等待后续 TDD 迁移的当前事实。目标构造字段为 `stimulus_id: str`、`schema_version: int`、`occurred_at: datetime`、`source: StimulusSource`、`target_character_ids: tuple[str, ...]`、`user_id: str | None`、`ephemeral: bool`、`text: str` 和 `client_msg_id: str`。调用方通过选择 `TextMessage` 提供刺激类型，`kind` 固定为 `StimulusKind.TEXT_MESSAGE`，不由 Agent 根据内容猜测。
- `StimulusKind.TEXT_MESSAGE`：当前已实现强类型 Stimulus 的稳定判别值。
- `StimulusSource.USER`：表示该领域事实由用户行为产生，不表示 WebSocket、HTTP 等传输通道。
- `PersistPolicy`：当前旧 Stimulus 与 PR #90 强类型切片仍共用的四成员枚举。它只用于描述迁移期当前实现，不再属于目标 `domain.agent` Stimulus interface；尚未迁移的旧生产调用方继续使用，直到对应链路把持久化判断收进 Agent 并由最终 contract 工单删除兼容导出。
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
- 当前契约测试只锁定 PR #90 的合法样例：`source=USER`、迁移期 `persist_policy=CONVERSATION_AND_MEMORY_CANDIDATE`、`ephemeral=False`。这些是该样例的输入，不是 `TextMessage` 的唯一合法 source/ephemeral 组合，也不应扩展成组合矩阵。
- **目标 interface**：非法 Stimulus 构造将直接抛出公开 `InvalidStimulusError(ValueError)`；字段自身或变体结构非法时 `code="CONTRACT_INVALID_STIMULUS"`，整数但不受支持的 schema 版本时 `code="CONTRACT_UNSUPPORTED_SCHEMA"`，两者的 `retryable=False`。合法字段之间不做 source/kind/ephemeral 白名单校验；构造失败发生在 handle 前，不产生 `HandlingReport`。该异常与 `StimulusErrorCode` 尚未在当前源码实现，不能提前用于业务代码。
- 枚举值和字段名属于跨模块协议；修改时必须先更新 spec 和消费者测试。
- 目标强类型 Stimulus 不携带 `PersistPolicy`。外部调用方显式提供刺激类型、source 和 interaction 生命周期字段；Agent 在 handle 内部决定会话记录和长期记忆候选，并对同一稳定刺激保证幂等。
- 构造参数不合法时由 dataclass、枚举或 Pydantic 抛出类型/校验异常，调用方不应静默吞掉。

## 使用示例

假设 WebSocket 收到一条文字消息：Adapter 选择 `TextMessage`、填写 `source` 和规范化内容，stage 管理 pending 后交给 Agent；Agent 在内部决定需要的会话记录和记忆证据，再生成零到多个 `ActionPlan`。stage 不读取或选择 Agent 的持久化策略。整个过程中，各模块共享的是公开领域数据，而不是彼此的内部对象。

## 应覆盖的契约场景

- `TextMessage` 从 `src.domain.agent` 构造后固定为 `TEXT_MESSAGE`，逐项保留目标公开字段、拒绝赋值修改且不存在 `payload`；source 和 ephemeral 的合法字段值不因组合少见而被构造器拒绝。
- 迁移期继续验证旧路径与当前 PR #90 路径导出的 `PersistPolicy` 是同一个四成员枚举对象；目标强类型 Stimulus 迁移完成后，改为验证 `src.domain.agent` 不再要求或公开该类型。
- 迁移期旧 `Stimulus` 在不同 `PersistPolicy` 下，`should_persist_conversation()` 和 `can_be_memory_candidate()` 返回预期结果；该测试不构成目标强类型 Stimulus 必须暴露策略的依据。
- `AgentState.with_updates(...)` 返回新对象且不修改原状态。
- 未指定目标角色、时间或 ID 时，默认值稳定且可序列化。
