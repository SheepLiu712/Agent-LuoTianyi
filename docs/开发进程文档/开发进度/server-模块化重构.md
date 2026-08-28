# server-模块化重构

- PRD：`docs/开发进程文档/需求说明（PRD）/server-模块化重构.md`
- interface spec：`docs/项目说明/项目架构与接口（spec）/接口文档/` 各模块 README；本重构唯一新增公开 interface 为 Agent 门面 `handle_stimulus`（PRD §4，定义见 agent/README 目标接口章节）
- 当前阶段：需求
- 总体状态：进行中
- 最后更新：2026-08-28

## 本 PR（片 0）

- 目标：建立需求与进度记录，供评审
- 范围：新增 PRD 与本进度文档；不修改任何产品代码与测试
- 明确不包含：批次 1-8 的全部代码/测试切片；附录 A 映射表的执行（执行在片 6-13）
- 验证及结果：PRD 引用的 file:line 证据已逐条用 grep/sed 复核，见附录 B；文档评审待定

## 已完成

- 现状盘点：server/src 11 个模块目录均有实质内容；stage 职责由 `chat_session`（17 文件 3,582 行）承担；adapter 散落在 `system/user_interface`（6 文件）+ `legacy/chat_input_adapter.py`（363 行）+ `server_main.py`（476 行）；自有代码 500+ 行文件 9 个
- 差异文档 12 条与代码证据逐条复核（附录 B），修正了 3 处行号（WSEventType 实际在 chat_stream.py:16；get_database_manager 在 database_service.py:183；全局赋值在 chat_session_manager.py:50）

## 阻塞和未验证项

- 测试基线（pytest 收集数/通过/跳过数）未建立：需 Python 环境与依赖安装，安排在 PRD 合并后、片 1 开始前执行，结果记入本文件
- redis 等外部服务在本机的可用性未验证
- 附录 A 标注"初判"的 12 个测试文件归位目标，需在片 6-13 执行时逐文件复核

## 下一 PR

- 片 1（批次 1）：修复 `server/src/system/__init__.py:8` 死引用

## 附录 A：测试归位映射表（59 个文件，初判）

按守则"放置测试的判断顺序"初判；执行片 6-13 时逐文件复核，复核结论记录在对应 PR。判定依据"从哪个公开 interface 观察结果"，不由被修改的私有文件决定。

### `tests/stage/`（6 个）

| 文件 | 备注 |
|---|---|
| test_chat_stream_lifecycle.py | ChatStream 生命周期 |
| test_chat_stream_reconnect.py | 重连（守则示例归属） |
| test_pipeline_backpressure.py | 聊天管线 |
| test_pipeline_reliability.py | 聊天管线 |
| test_topic_planner_waiting_signals.py | 管线内部信号 |
| test_proactive_topic_maker.py | stage 依赖组件 |

### `tests/adapter/`（8 个）

| 文件 | 备注 |
|---|---|
| test_websocket_auth_limits.py | WebSocketService |
| test_websocket_delivery.py | WebSocketService |
| test_websocket_idempotency.py | 幂等（守则示例归属） |
| test_auth_rate_limits.py | 限流 |
| test_auth_security.py | 认证 |
| test_http_secret_security.py | HTTP 安全 |
| test_invite_security.py | 邀请码 |
| test_project_plan_route.py | REST 路由 |

### `tests/system/`（15 个）

| 文件 | 备注 |
|---|---|
| test_admin_auth_concurrency.py | admin |
| test_admin_runtime.py | admin |
| test_database_atomicity.py | database |
| test_database_manager.py | database |
| test_event_store_character.py | database/services |
| test_event_store_concurrency.py | 同上 |
| test_event_store_holidays.py | 同上 |
| test_event_store_llm_dedup.py | 同上 |
| test_memory_store_cold_cache.py | database/memory_store |
| test_observability_llm_summary.py | observability |
| test_preferences_normalization.py | 初判（可能属 user_interface 侧，复核） |
| test_runtime_error_surface.py | system_runtime |
| test_runtime_initialization_rollback.py | system_runtime（守则示例归属） |
| test_runtime_shutdown.py | system_runtime |
| test_system_runtime_shutdown.py | system_runtime |

### `tests/world/`（8 个）

| 文件 | 备注 |
|---|---|
| test_citywalk_amap_client.py | 初判（外部 seam 客户端，复核） |
| test_world_runtime_config.py | WorldRuntime |
| test_world_task_bili_event_update.py | world 任务 |
| test_world_task_citywalk.py | 同上 |
| test_world_task_event_cleanup.py | 同上 |
| test_world_task_learn_sing_songs.py | 同上 |
| test_world_task_proactive_topic_check.py | 同上 |
| test_world_task_vcpedia_new_songs.py | 同上 |

### `tests/capabilities/`（7 个）

| 文件 | 备注 |
|---|---|
| test_capability_image_understanding.py | ImageUnderstanding |
| test_capability_singing.py | SingingCapability |
| test_capability_speech.py | SpeechCapability |
| test_diary.py | 初判（diary 能力 vs world 任务，复核） |
| test_dynamics.py | 初判（dynamic 能力 vs dynamic_store，复核） |
| test_streaming_tts_shutdown.py | TTS |
| test_tts_lifecycle.py | TTS |

### `tests/agent/`（2 个）

| 文件 | 备注 |
|---|---|
| test_main_chat_tone_mapping.py | agent/main_chat |
| test_response_parser_singing.py | 初判（agent/response_parser，复核） |

### `tests/agent_runtime/`（3 个）

| 文件 | 备注 |
|---|---|
| test_agent_failure_modes.py | AgentRuntime 失败路径 |
| test_agent_reflex.py | 初判（经 AgentRuntime.try_handle_reflex 观察，复核） |
| test_character_validation.py | 初判（CharacterRegistry，复核） |

### `tests/subconscious/`（3 个）

| 文件 | 备注 |
|---|---|
| test_birthday_date_reminder.py | 初判（date_processor，复核） |
| test_song_emotion_tagger.py | 初判（music_knowledge，复核） |
| test_subconscious_memory.py | memory 门面 |

### `tests/utils/`（6 个）

| 文件 | 备注 |
|---|---|
| test_client_llm_executor.py | utils/llm |
| test_client_model_types_validation.py | 初判（复核） |
| test_embedding_timeouts.py | utils/llm/embedding |
| test_llm_content_inspection.py | utils/llm |
| test_llm_service.py | utils/llm_service |
| test_logger.py | utils/logger |

### `tests/integration/account/`（1 个）

| 文件 | 备注 |
|---|---|
| test_legacy_account_atomicity.py | 初判（跨 user_interface + database 的账户流程，复核） |

汇总：6+8+15+8+7+2+3+3+6+1 = 59 ✓（conftest.py 留在根目录，不迁移）

## 附录 B：证据复核记录（2026-08-28，基于 4177799）

| PRD 断言 | 复核结果 |
|---|---|
| `system/__init__.py:8` 死引用 `from src.chat_session.conversation import ConversationService` | ✓ 确认，实际模块在 `chat_session/dependency/conversation_service.py` |
| `capabilities/__init__.py` `__all__` 含未定义 `CapabilityRegistry`、漏 `CapabilityManager` | ✓ 确认（import 了 CapabilityManager 但未列入 `__all__`，`__all__` 首项 CapabilityRegistry 无定义） |
| `subconscious/__init__.py` 导出 `extract_song_entities` 但函数不存在 | ✓ 确认：`__all__` 与 `__getattr__` 均引用，`grep -rn "def extract_song_entities" server/src/subconscious/` 无命中，访问即 AttributeError |
| `agent/__init__.py` 未导出 `LuoTianyiAgent` | ✓ 确认，文件仅有 docstring |
| `chat_stream.py:16` import `WSEventType` | ✓ 确认（用例 :267/:302；差异文档原行号 :20 有误，已修正） |
| ChatStream/ChatStreamManager 依赖 WebSocketConnection 与整个 SystemRuntime | ✓ 确认：chat_stream.py:25（TYPE_CHECKING SystemRuntime）、:120 set_system_runtime、:337 reconnect(ws_connection)；chat_stream_manager.py:5 直接 import WebSocketConnection |
| `singing_manager.py:12` import `world...WishlistManager` | ✓ 确认 |
| `daily_new_song_fetcher.py:22` import `subconscious...song_database` | ✓ 确认 |
| `utils/enum_type.py` ContextType/ConversationSource | ✓ 确认（:3/:10） |
| `helpers.py:54` get_unified_song_name | ✓ 确认 |
| `database_service.py:183` get_database_manager 隐式自建 | ✓ 确认（:185-187 `if _db_manager is None: _db_manager = DatabaseManager()`） |
| `chat_stream_manager.py:338,341` 模块全局与 get_GCSM；`chat_session_manager.py:50` 写全局 | ✓ 确认 |
| `song_database.py:42-70` 隐藏自动初始化 `res/knowledge/knowledge_db.db` | ✓ 确认（get_song_db/get_song_session 在 SessionLocal 为 None 时自建） |
| `llm_module.py:5`/`vlm_module.py:5` import system.observability 全局入口 | ✓ 确认（get_observability_service/get_trace_context） |
| `client_llm_executor.py:106` bind(stream_manager) | ✓ 确认（:114 经其 get_stream_by_user_uuid） |
| `image_process.py:1` from fastapi import UploadFile | ✓ 确认 |
| AgentRuntime 过渡方法 :189-285 共 8 个 | ✓ 确认（preprocess_chat_event:189 / try_handle_reflex:193 / extract_topic:204 / plan_topic_turn:222 / realize_topic_plan:244 / write_topic_memories:249 / detect_dates_for_topic:267 / update_user_profile_by_context:285；get_agent:173） |
| server/tests 59 个 test_*.py 100% 平铺 | ✓ 确认（ls 计数 59，无子目录；文件名无重复） |
