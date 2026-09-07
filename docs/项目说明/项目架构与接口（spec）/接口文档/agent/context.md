# 交互上下文

`server/src/agent/context` 提供交互上下文的创建、读取、更新和释放。数据库服务负责用户资料、正式对话和对话总结的读写；上下文持有当前交互使用的数据及召回缓存。

## 文件与类型

| 文件 | 公开类型 |
| --- | --- |
| `context_factory.py` | `ContextFactory` |
| `interaction_context.py` | `InteractionContext` |
| `user_context.py` | `UserContext` |
| `conversation_context.py` | `ConversationContext` |
| `recalled_memory_context.py` | `RecalledMemoryContext` |
| `models.py` | 身份、用户资料、对话、压缩结果和召回记录的数据类型 |

`_storage.py` 在数据库历史格式与上下文类型之间转换。`_lifecycle.py` 管理关闭状态及异步操作的完成边界。

## 创建和释放

```python
factory = ContextFactory(
    character_id="luotianyi",
    database=database_manager.conversation_service,
)
context = await factory.get("interaction-id", user_id="user-id")
await factory.release("interaction-id")
```

- 一个 `ContextFactory` 绑定一个角色，在一个事件循环内使用。
- `get(interaction_id, *, user_id) -> InteractionContext`：已有交互返回同一实例，首次访问在工作线程中完成构造。构造失败不缓存半成品。相同交互不能更换用户。
- `find(interaction_id) -> InteractionContext | None`：只查找已创建且未关闭的实例。
- `release(interaction_id) -> None`：等待创建和正在进行的数据操作结束，关闭并移除实例。不存在时无影响。
- `InteractionContext.__init__` 同步加载画像、偏好、对话总结及近期记录，自动建立空召回缓存。
- `close() -> None` 清空三部分内存并关闭实例；重复关闭无影响。关闭后的读取和更新抛出 `RuntimeError`。

`ContextIdentity` 包含 `character_id`、`interaction_id` 和 `user_id`。`user_id=None` 时构造空上下文，用户资料和正式对话写入抛出 `ValueError`。指定的用户不存在时构造抛出 `LookupError`。

## 用户资料

`context.user` 提供：

- `read() -> UserContextSnapshot`：返回当前画像和偏好。
- `update_profile(profile: UserProfile) -> None`：保存画像后更新内存。
- `update_preferences(preferences: UserPreferences) -> None`：保存偏好后更新内存。

`UserProfile.description` 保存画像文字。`UserPreferences` 包含 `relationship`、`speaking_style`、`personality_traits`、`custom_context` 和 `personality_text`；最后一个字段映射到现有存储键 `#sym:personality_text`。更新偏好保留数据库中其它未建模的键。

画像和偏好分别写入，保存失败抛出异常。读取得到的是当前交互视图；其他交互或管理接口修改数据库不会主动刷新已有视图。

## 近期对话

`context.conversation` 提供：

- `read() -> ConversationSnapshot`：返回总结和近期对话元组。
- `append(entries: tuple[ConversationEntry, ...]) -> None`：保存正式对话后从数据库刷新窗口。
- `compact(compaction: ConversationCompaction) -> None`：验证外部生成的压缩结果，保存总结并刷新窗口。

`ConversationEntry` 包含记录 ID、服务器本地时间、发言来源和内容。数据库时间精度为秒。内容使用 `TextContent`、`ImageContent`、`AudioContent` 或 `SongContent`；图片位置、关键词、曲名和片段名称均有明确字段。

`ConversationSnapshot` 由 `ConversationSummary` 和记录元组组成。`ConversationCompaction` 包含：

- `previous_summary: ConversationSummary`：生成新总结时使用的原总结。
- `covered_entry_ids: tuple[str, ...]`：本次总结覆盖的对话 ID，按窗口顺序排列，非空且不重复。
- `summary: ConversationSummary`：非空的新总结。

调用方决定是否压缩并生成结果。无需压缩时返回 `None`，调用方跳过 `compact`；`compact` 只接受完整的 `ConversationCompaction`。

应用前，context 重新读取数据库窗口，检查原总结相同、覆盖记录匹配当前窗口的连续前缀。不匹配时抛出 `ValueError`；数据库保存失败时抛出 `RuntimeError`。压缩仅更新总结和近期窗口条数，保留未覆盖的记录及完整历史，包括结果生成期间追加的消息。

同一工厂内，同一用户的资料写入、对话追加及压缩应用顺序执行。数据库操作已经开始时，取消调用者会等待操作及内存同步结束，再传播取消异常。

## 召回记忆

`context.recalled_memory` 提供：

- `read() -> tuple[RecallEntry, ...]`：按添加顺序返回记录副本。
- `append(entries: tuple[RecallEntry, ...]) -> None`：添加记录；批次内部或已有缓存出现重复记录 ID 时整批拒绝。
- `remove(entry_ids: frozenset[str]) -> None`：按记录 ID 删除，不存在的 ID 无影响。
- `remove_by_stimulus_id(stimulus_id: str) -> None`：删除指定刺激触发的全部记录。
- `clear() -> None`：删除全部缓存记录。

`RecallEntry` 包含 `entry_id`、`stimulus_id` 和 `content`。内容使用现有 `MemoryHit` 或 `JargonExplanation(keyword, explanation)`。同一条长期记忆由不同刺激触发时，可以建立不同记录 ID，分别管理生命周期。

删除操作仅影响当前交互的召回缓存。缓存由显式调用删除或关闭上下文时清空，完成一次 handle 调用不会触发清理。
