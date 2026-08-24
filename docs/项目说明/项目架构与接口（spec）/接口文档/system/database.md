# system.database 对外接口

## 模块职责

`server/src/system/database` 统一拥有 SQL、Redis、向量库和知识图谱资源，并向上层提供按业务主题划分的存储服务。调用方不应自行创建第二套全局数据库连接。

## `DatabaseManager`

- `DatabaseManager(config=None)`：创建数据库管理器。
- `init_all_databases()`：初始化 SQL、Redis、向量库、知识图谱以及各存储服务。
- `wire_dependencies(llm_service=...)` / `create_llm_modules(...)`：给需要模型的存储服务注入 LLM。
- `ensure_dependencies()`：检查数据库和服务是否已就绪。
- `open_sql_session()`：返回由调用方负责关闭的 SQLAlchemy Session，推荐配合 `with` 使用。
- `await shutdown()`：关闭写入器、Redis、向量库等资源。
- 属性 `conversation_service`、`credential_service`、`dynamic_store`、`event_store`、`memory_store`、`user_store` 和 `redis`：取得专用服务。
- `set_default_database_manager(...)` / `get_database_manager()`：旧代码使用的进程级定位器。

## 专用存储服务

### `ConversationService`

- 用户偏好、描述、昵称的读取和保存。
- `add_conversations(...)`：批量加入对话记录。
- `prefill_buffer(...)`、`get_conversation_context_state(...)`：建立并读取对话缓存。
- `compact_conversation_context(...)`、`reset_conversation_context_if_stale(...)`：压缩或重置上下文。
- `get_history_from_db(...)`、对话总数/上下文条数查询。
- `get_image_server_path(...)`、`update_image_client_path(...)`：处理历史图片路径。

### `CredentialService`

- 用户名到 UUID 查询。
- 注册、密码登录、自动登录和账户重置。
- auth token、message token 的生成和校验。
- 登录时间更新。
- 管理端邀请码列出、生成、启用/禁用和删除。

### `DynamicStore`

- `create_dynamic(...)`、按用户分页列出动态、读取单条动态。
- 列出和创建评论。
- 未读状态查询和已读标记。
- 待自动回复/待记忆的动态与评论查询，以及处理状态更新。
- 管理端动态和评论列表。

### `EventStore`

- 按 ID、类型或用户查询事件。
- `find_matching_event(...)`、`add_event(...)`、`remove_event(...)`。
- 查询到期事件、清理过期事件、补齐节日数据。
- `try_claim_notification(...)`、`mark_notified(...)`、`release_notification_claim(...)`：保证提醒不会被重复派发。

### `MemoryStore`

- `write_memory_update(...)`：保存记忆变更命令。
- `write_agent_memory_record(...)`：保存 Agent 长期记忆并返回记录 ID。
- 按记录 ID 或 embedding ID 读取记忆。
- 读取近期记忆更新缓存。

### `UserStore`

- 批量加载用户显示名、查询用户是否存在。
- 用户偏好和描述的读取/保存。
- 带 Session 的变体供需要同一事务的内部调用使用。

## 向量与图谱

### `VectorStore`

- `add_documents(documents) -> list[str]`。
- `await search(user_id, query, k=5, **kwargs) -> list[(document, score)]`。
- `delete_documents(...)`、`delete_user_records(...)`、`update_document(...)`、`get_document_by_id(...)`。
- `init_vector_store(...)`、`get_vector_store()`、`clear_vector_store(...)`：当前全局兼容入口。

### `KnowledgeGraph`

- `add_entity(...)`、`update_entity(...)`、`add_relation(...)`。
- `has_entity(...)`、`get_neighbors(...)`、`find_path(...)`、`get_entities_by_type(...)`。
- `load_graph_data(...)`、`save_graph_data()`、`save_alias_map()`。
- `get_aliased_name(...)`：取得实体别名。
- `init_knowledge_graph(...)` / `get_knowledge_graph()`：当前全局兼容入口。

## 正常与异常行为

- 查询没有结果时返回 `None`、空列表或零；具体以方法签名为准，不应把“无结果”记录成系统异常。
- 写接口会修改 SQL、Redis、向量库或文件，跨存储写入不天然是同一事务。
- `open_sql_session()` 返回的 Session 必须关闭；提交由具体方法的 `commit` 参数或调用方事务决定。
- 重复通知必须经过 claim 接口，不能先发送后只靠 `mark_notified` 去重。
- 数据库不可用、约束冲突或模型辅助匹配失败会返回业务失败值或抛出存储异常；上层应保留原因。

## 使用示例

假设 subconscious 要保存一条长期记忆：它调用注入的 `MemoryStore`，由后者协调 SQL 记录和向量索引。subconscious 不直接导入 SQLAlchemy 表，也不自行初始化 ChromaDB。

## 应覆盖的契约场景

- 查询无结果与数据库异常产生不同结果；调用方能区分空列表/`None` 和失败。
- 同一提醒并发 claim 时只有一个调用者成功，释放后才能重新领取。
- 写记忆后 SQL 记录和向量索引可按公开接口读回；任一侧失败不会伪报完整成功。
- `shutdown()` 后连接和后台写入器退出，调用方创建的 Session 仍由调用方负责关闭。
