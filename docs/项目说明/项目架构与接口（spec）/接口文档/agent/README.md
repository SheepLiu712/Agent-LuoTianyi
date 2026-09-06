# agent 对外接口

## 两接口门面

[#63 门面契约](facade.md)记录 `Agent` 的两接口、入口校验、处理器调用、交付结算及关闭等待行为。`get_agent()` 返回新门面，下文记录通过 `get_character_runtime(...).conscious` 取得的旧 `LuoTianyiAgent` 兼容接口。

路由的文件结构、内部注册和解析接口见 [Handler 路由 SPEC](handler-routing.md)。

计划草稿、稳定身份与持久投递恢复见 [PlanEmitter 契约](plan-emitter.md)。

执行账本与逐行动安全恢复的当前契约见 [Execution Ledger](execution-ledger.md)。

## 模块职责

`server/src/agent` 负责角色如何理解上下文、组织回复并决定动作。

旧聊天使用 `LuoTianyiAgent`，下面记录其兼容接口。

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

## 正常与异常行为

- 正常调用顺序是先由 `agent_runtime.get_character_runtime(character_id).conscious` 取得 Agent，再调用上述接口。
- 规划、记忆、模型、唱歌和语音调用可能产生模型请求、数据库写入、文件读取或音频生成等副作用。
- 依赖未注入、模型返回无法解析或能力执行失败时会传播异常。
- 流式语音生成器可能在迭代过程中失败，不能只在创建生成器时判定成功。

## 使用示例

stage 整理出完整话题后，通过 `agent_runtime.get_character_runtime("luotianyi").conscious` 取得 Agent，再调用话题规划与回复接口。
