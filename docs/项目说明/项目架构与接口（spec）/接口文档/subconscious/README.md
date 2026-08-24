# subconscious 对外接口

## 模块职责

`server/src/subconscious` 负责话题提取、注意力规划、事实和记忆检索、日期识别、用户画像更新等“回复前后的思考”。目标架构中它是 Agent 的内部组成，不供 stage、Adapter 或 world 直接调用。

## 当前对外接口

### `CharacterSubconscious`

- `ensure_dependencies()`：检查模型、记忆和歌曲等依赖。
- `get_state() -> SubconsciousState`：返回当前 subconscious 状态。
- `await extract_topics(...) -> tuple[ExtractedTopic | None, list[UnreadMessage]]`：从未读消息中提取完整话题，并返回尚未消费的消息。
- `await search_fact_constraints_for_topic(...)`：生成或查询话题所需的事实约束。
- `await search_memory_context_for_topic(...) -> MemoryContext`：为话题检索用户记忆。
- `await plan_topic_turn(...) -> TopicAttentionPlan`：把话题、上下文、事实和记忆整理成注意力计划。
- `await write_topic_memories(...) -> dict`：决定并写入本轮记忆。
- `await detect_dates_for_topic(...) -> bool`：识别并处理重要日期。
- `await update_user_profile_by_context(...) -> str | None`：根据上下文更新用户画像。
- `await build_sing_plan_for_topic(...) -> tuple[song, segment]`：为话题形成演唱计划。

### 预处理、注意力和提取器

- `await ChatPreprocessor.preprocess_chat_event(character_id, user_id, event)`：规范化一条聊天输入。
- `TopicExtractor`：从消息集合提取 `ExtractedTopic`。
- `AttentionPlanner`：生成 `TopicAttentionPlan`。
- `TopicAttentionPlan`：供 Agent 实现回复时使用的计划数据。
- `SongEntityLinker.extract_and_verify(...)`：识别并核验歌曲实体。
- `DateDetector.detect(...)`、`process_detected_date(...)`、`get_today_important_dates(...)`：日期识别和重要日期查询。

### 记忆门面

- `await SubconsciousMemory.search_memory_context_for_topic(...)`：检索记忆。
- `await write_topic_memories(...)`、`await write_user_memory(...)`、`await write_event_memory(...)`：写入不同来源的记忆。
- 用户画像更新相关方法：读取上下文并更新用户描述。

该包使用延迟导入，首次访问名称时才加载具体实现。当前 `server/src/subconscious/__init__.py` 还声明了不存在的 `extract_song_entities`，因此不能仅凭 `__all__` 判断接口，详见差异文档。

## 正常与异常行为

- 查询接口正常返回空集合或 `None` 表示没有结果；这不等于调用失败。
- 写记忆、更新画像和处理日期会访问数据库，并可能调用模型；不是纯计算。
- 模型、存储或依赖异常会向 Agent/AgentRuntime 传播。
- `extract_topics` 返回的“剩余消息”必须继续保留，丢弃会造成用户消息丢失。

## 使用示例

假设用户连续发送“你听过这首歌吗”和歌曲名：Agent 内部让 subconscious 判断两条消息是否已经组成完整话题，再检索相关记忆和歌曲事实，最后把 `TopicAttentionPlan` 交回 Agent。stage 不应该分别调用这些步骤。

## 应覆盖的契约场景

- 多条消息只形成一个完整话题时，已消费和剩余消息不会重复或丢失。
- 记忆、事实和歌曲均无结果时返回空上下文，而不是伪造内容。
- 写记忆或更新画像失败时向 Agent 返回可识别失败，不把失败记录成成功。

## 依赖方向

允许：`agent -> subconscious -> domain/system.database/utils`。目标架构不允许：`stage/adapter/world -> subconscious`。当前仍存在少量跨越 Agent 的调用，详见根目录的《当前实现与目标架构差异》。
