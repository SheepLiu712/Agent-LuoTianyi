# domain 对外接口

## 模块职责

`server/src/domain` 只定义跨模块传递的数据和领域词汇，不访问数据库、网络、模型或文件。其他模块可以依赖 `domain`；`domain` 不应反向依赖它们。

## 对外接口

### 输入与响应

- [Stimulus 领域契约](stimulus.md)：当前总 SPEC 已登记的 22 个 Stimulus 类型名的权威 interface；其中 15 种定义为可构造，7 种只占位且当前统一拒绝构造。文档定义公共字段、专有字段、依赖值类型、稳定错误和公开测试 seam。
- [handle 输入契约](handle-input.md)：提供不可变请求、Chat/Toy/World 快照、共享取消令牌、枚举及稳定构造错误。
- [HandlingReport 类型契约](handling-report.md)：提供不可变报告、请求状态、pending 身份划分、计划身份、重评时间及稳定错误。
- `src.domain.agent`：Agent 强类型领域协议的公开导入路径。当前已实现抽象 `Stimulus`、当前总 SPEC 登记的 22 个具体类型、完整 `StimulusKind`、`StimulusSource`、构造所需领域值类型及三类稳定构造错误；其中 15 个具体类型可构造，7 个占位类型统一返回 `CONTRACT_STIMULUS_UNAVAILABLE`。目标包不导出 `PersistPolicy`。`InteractionSnapshot` 三种变体、`HandleStimulusRequest`、`CancellationToken` 及相关枚举/稳定错误已实现。
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
- 15 种可构造 Stimulus 与 7 种占位 Stimulus 的正常/拒绝行为、字段校验和稳定错误以[专用契约](stimulus.md)为准；生产调用方仍按后续迁移切片逐个接入。
- 枚举值和字段名属于跨模块协议；修改时必须先更新 spec 和消费者测试。
- 旧 Stimulus 的持久化判断和目标强类型 Stimulus 的构造错误属于两套迁移期 interface，调用方不得混用。

## 使用示例

调用方构造 `TextMessage`，将其放入交互快照的 `pending_stimuli`，再以相同内容作为 `HandleStimulusRequest.stimulus`。请求保存不可变快照，并持有调用方传入的同一枚 `CancellationToken`；具体构造示例见 [handle 输入契约](handle-input.md)。

## 应覆盖的契约场景

- 目标 Stimulus 只按[专用契约](stimulus.md)列出的公开 seam 验证，不通过实现细节增加总 SPEC 未登记的未来变体。
- 迁移期旧 `Stimulus` 在不同 `PersistPolicy` 下，`should_persist_conversation()` 和 `can_be_memory_candidate()` 返回预期结果；该测试不构成目标强类型 Stimulus 必须暴露策略的依据。
- `AgentState.with_updates(...)` 返回新对象且不修改原状态。
