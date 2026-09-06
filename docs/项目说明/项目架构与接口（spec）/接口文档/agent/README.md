# agent 对外接口

## 模块职责

`server/src/agent` 负责角色如何理解上下文、组织回复并决定动作。按照目标架构，其他业务模块最终只应调用 Agent 提供的少量接口，不应直接操作 subconscious 或 capabilities。

当前实现还没有独立的“薄外壳”类；实际入口是 `LuoTianyiAgent`。下面记录当前确实可被其他模块调用的接口。

## 对外接口

### 生命周期

- `LuoTianyiAgent.ensure_dependencies()`：检查必要依赖是否已经注入。依赖缺失时抛出异常。

### 话题规划与回复

- `await plan_topic_turn_for_pipeline(user_id, topic, conversation_history, external_context=None) -> TopicAttentionPlan`：为一个完整话题生成注意力和回复计划。
- `await realize_topic_plan_for_pipeline(user_id, plan) -> list[OneResponseLine]`：把计划实现为文字或歌曲回复行。
- `await generate_topic_reply_for_pipeline(user_id, topic_content, memory_hits=None, fact_hits=None, sing_plan=None, conversation_history=None) -> list[OneResponseLine]`：兼容现有流水线的一步式回复入口。
- `await search_song_facts_for_topic(constraints) -> list[str]`：查询与话题约束有关的歌曲事实。
- `await search_memory_context_for_topic(user_id, queries, threshold=0.8, k=3) -> MemoryContext`：查询用户相关记忆。
- `await write_topic_memories_for_pipeline(...) -> dict`：根据本轮话题和回复决定并写入记忆。

### 唱歌和语音

- `await build_sing_plan_for_topic(...) -> tuple[song, segment]`：选择歌曲及演唱片段。
- `sing(song_name, segment) -> bytes | None`：生成或读取演唱音频；无法演唱时返回 `None`。
- `await tts_say(text, tone) -> str`：返回 Base64 编码的语音。
- `tts_say_stream(text, tone) -> Generator[str]`：逐块返回 Base64 编码的流式语音。

### 世界信息

- `await get_citywalk_diary_by_date(date_str) -> str | None`：读取指定日期的城市漫步日记。
- `await get_citywalk_overview_by_date(date_str) -> dict | None`：读取指定日期的城市漫步概览。

### 当前回复对象

`server/src/agent/main_chat.py` 中的对象目前也被 stage 直接使用：

- `OneResponseLine(type, uuid)`：回复行基类。
- `OneSentenceChat(sound_content, expression, tone, content, uuid)`：一条可显示、可朗读的文字回复。
- `SongSegmentChat(lyrics, song, segment, uuid)`：一段歌曲回复。

这些类型目前是事实接口，但后续应迁入稳定的领域协议或由 Agent 外壳隐藏。

## 正常与异常行为

- 正常调用顺序是先由 `agent_runtime.get_agent(character_id)` 取得 Agent，再调用上述接口。
- 规划、记忆、模型、唱歌和语音调用可能产生模型请求、数据库写入、文件读取或音频生成等副作用。
- 依赖未注入、模型返回无法解析或能力执行失败时会传播异常；调用方应在 stage/Adapter 边界转换为可观察的失败结果。
- 流式语音生成器可能在迭代过程中失败，不能只在创建生成器时判定成功。

## 使用示例

假设 stage 已经整理出一个完整话题：它先调用 `agent_runtime.get_agent("luotianyi")`，再让 Agent 规划并实现回复。stage 只负责排队、超时和发送，不需要知道 Agent 内部用了哪些记忆检索器或语音服务。

## 应覆盖的契约场景

- 使用 Fake subconscious/capability 时，给定同一话题能从公开规划接口得到可实现的回复计划。
- 没有记忆或歌曲事实时仍能正常回复；依赖未注入时 `ensure_dependencies()` 明确失败。
- `sing(...)` 无可用歌曲时返回 `None`；流式语音在中途失败时把错误交给调用者处理。
