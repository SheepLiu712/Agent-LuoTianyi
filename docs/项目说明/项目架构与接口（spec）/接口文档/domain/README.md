# domain 对外接口

## 模块职责

`server/src/domain` 只定义跨模块传递的数据和领域词汇，不访问数据库、网络、模型或文件。其他模块可以依赖 `domain`；`domain` 不应反向依赖它们。

## 对外接口

### 输入与响应

- [`Stimulus` 与 `TextMessage` 目标契约](stimulus.md)：工单 1 首个行为切片的权威 interface，定义抽象公共字段、文字消息专有字段、枚举、构造错误和公开测试 seam。
- `src.domain.agent`：Agent 强类型领域协议的公开导入路径。当前实现只有迁移期 `TextMessage`、`StimulusKind`、`StimulusSource` 和兼容导出的 `PersistPolicy`；目标 interface 以专用契约为准。
- 旧 `src.domain.stimulus.Stimulus`：当前生产链仍使用的 Mapping 协议，提供 `targets_character()`、`should_persist_conversation()` 和 `can_be_memory_candidate()`。它及其 `SourceChannel`、`StimulusModality`、`PersistPolicy` 在迁移期保持可用，但不构成新 `src.domain.agent` 协议的一部分。
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
- `Stimulus` 与 `TextMessage` 的目标正常行为、字段校验和稳定错误以[专用契约](stimulus.md)为准；在 Green 实现完成前必须按“目标 interface”阅读，不能提前用于生产调用方。
- 枚举值和字段名属于跨模块协议；修改时必须先更新 spec 和消费者测试。
- 旧 Stimulus 的持久化判断和目标强类型 Stimulus 的构造错误属于两套迁移期 interface，调用方不得混用。

## 使用示例

假设 WebSocket 收到一条文字消息：Adapter 选择 `TextMessage`、填写 `source` 和规范化内容，stage 管理 pending 后交给 Agent；Agent 在内部决定需要的会话记录和记忆证据，再生成零到多个 `ActionPlan`。stage 不读取或选择 Agent 的持久化策略。整个过程中，各模块共享的是公开领域数据，而不是彼此的内部对象。

## 应覆盖的契约场景

- `Stimulus` 与 `TextMessage` 只按[专用契约](stimulus.md)列出的公开 seam 验证，不通过实现细节补充未来变体。
- 迁移期旧 `Stimulus` 在不同 `PersistPolicy` 下，`should_persist_conversation()` 和 `can_be_memory_candidate()` 返回预期结果；该测试不构成目标强类型 Stimulus 必须暴露策略的依据。
- `AgentState.with_updates(...)` 返回新对象且不修改原状态。
