# Contract 收束规格（提案，未实现）

- 状态：**设计提案，待评审**。只记录收束范围与前置条件，不执行删除。
- 关联工单：Issue [#88](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/88)（29 按真实调用图清理旧业务入口与旁路）
- 相关规范：总 SPEC 第 8.1 节 A1—A9、9.3 节；现状：`server_main.py:169-174` 仍调 `try_accept_chat_event`；`AgentRuntime` 仍暴露 `preprocess_chat_event/extract_topic/plan_topic_turn/realize_topic_plan/write_topic_memories/detect_dates_for_topic/update_user_profile_by_context/try_handle_reflex`；world 4 个任务仍 import `CharacterRuntime`。

## 1. 要解决的问题

expand—migrate—contract 的最后一步：迁移完成后删除旧业务入口与旁路，使生产依赖图只剩两个 Agent 接口。**本提案只定义范围与顺序**，不执行。

## 2. 前置条件（必须全部满足）

1. 07—25 全部完成并合入 `refactor/agent`（含 07 的生产接通、15 触摸、16 登录、17 提醒、19—25 world 链）；
2. `#66` 的生产切换已可用：`try_accept_stimulus_event` + `StageManager.connect/disconnect` 取代旧 `try_accept_chat_event`；
3. 依赖扫描脚本/规则确定（A6/A9 的可检查项）。

## 3. 删除清单（按序）

1. **旧聊天入口**：`websocket_service.try_accept_chat_event`、`chat_session/chat_pipeline/*`（`ChatStream`/`IngressHelper`/`TopicPlanner`/`TopicReplier`/`ReflectionWorker`）、`chat_stream_manager`；
2. **旧业务代理**：`AgentRuntime` 的预处理/提取/规划/实现/记忆/日期/画像/reflex 代理方法；`get_character_runtime` 的生产业务使用；
3. **旧反射**：`agent/reflex/*`（触摸迁移到新 handler 后）；
4. **world 直连**：`citywalk`/`diary`/`dynamic_interaction`/`learn_sing_songs` 对 `CharacterRuntime` 的导入与调用；
5. **内部类型外泄**：`UnreadMessage`/`ExtractedTopic`/`AttentionPlan`/`OneSentenceChat`/`SongSegmentChat` 不再被 Agent 外部依赖；
6. **过渡 adapter**：无生产调用者的迁移适配层。

## 4. 验证方式

- 静态依赖扫描：external→`domain`/façade 单向；无 Handler→capability/DB/runtime；无 Skill→Handler/stage/report 反依赖；`agent/__init__` 只导出 façade；
- 删除后所有已迁移流程测试仍绿 + 全量 `python -m pytest tests -q`；记录收集数/通过/跳过/失败；
- 不得只为让测试通过而保留转发层，也不得删除后不恢复失败调用方（应回到对应迁移工单）。

## 5. 未决问题

1. `CapabilityManager` 是否保留为纯技术装配容器（取决于删除后是否仍有真实使用）？
2. `legacy/` 目录的最终形态与保留项？
3. 扫描用什么方式固化为可重复检查（脚本 / CI / 人工清单）？

## 6. 明确不包含

- 本提案不删除任何文件、不修改 `server_main.py`、不改 `AgentRuntime`。
- 不重写已通过新 façade 的内部 Handler/Skill，不做无关目录美化。
