# Server 模块化重构需求（PRD）

- 功能短名：server-模块化重构（进度文档同名）
- 依据文档：`docs/项目说明/项目架构与接口（spec）/接口文档/当前实现与目标架构差异.md`（下称"差异文档"，12 条已确认差距）；`docs/开发进程文档/开发守则.md`；接口文档各模块 README
- 分支：各切片分支自上游 `refactor/agent`（tip 4177799）拉出，经 fork `jinyiwei2012` 推送；PR 一律交到上游 `SheepLiu712/Agent-LuoTianyi` 的 `refactor/agent`
- 状态：需求评审中
- 最后更新：2026-08-28

## 1. 背景与问题

开发守则生效后，server 的目标架构、模块归属与依赖规则已成文，接口文档也把各模块"当前公开接口"按目标名整理完毕；差异文档确认了 12 处现状与目标的差距。经代码复核，主要问题包括：

1. **Agent 无有限门面**：`agent_runtime.py:173` 的 `get_agent()` 直接返回 `LuoTianyiAgent`，守则示例的 `handle_stimulus(stimulus, interaction_context)` 不存在；AgentRuntime 自身还公开 8 个业务编排方法（`preprocess_chat_event`/`try_handle_reflex`/`extract_topic`/`plan_topic_turn`/`realize_topic_plan`/`write_topic_memories`/`detect_dates_for_topic`/`update_user_profile_by_context`，agent_runtime.py:189-285），调用方可见全部内部链路。
2. **stage 直连 adapter 与整个运行时**：`chat_pipeline/chat_stream.py:16` 直接 import `system.user_interface.types.WSEventType`；`chat_stream_manager.py:5` 直接 import `WebSocketConnection`；ChatStream 通过 `set_system_runtime()`（chat_stream.py:120）持有整个 `SystemRuntime`。
3. **跨模块反向依赖**：`capabilities/singing/singing_manager.py:12` import `world.learn_sing_songs.auto_song_learner.WishlistManager`；`world/get_new_songs/daily_new_song_fetcher.py:22` 直接 import `subconscious.music_knowledge.song_database`；`utils/llm/llm_module.py:5`、`utils/vision/vlm_module.py:5` import `system.observability` 全局入口（system→utils→system 隐性环）；`utils/llm/client_llm_executor.py:106` 的 `bind(stream_manager)` 把 utils 绑到 stage。
4. **全局服务定位器**：`database_service.py:183` 的 `get_database_manager()` 未初始化时隐式自建；`chat_stream_manager.py:341` 的 `get_GCSM()` 配合 `chat_session_manager.py:50` 的模块全局赋值；`song_database.py:42-70` 的 `get_song_db()/get_song_session()` 未初始化时隐藏地自建 `res/knowledge/knowledge_db.db`；另有 `get_system_runtime/get_agent_runtime/get_observability_service` 等成对全局入口。
5. **包导出与实现不一致**：`system/__init__.py:8` 懒加载指向不存在的 `src.chat_session.conversation`；`capabilities/__init__.py` 的 `__all__` 含未定义的 `CapabilityRegistry` 且漏 `CapabilityManager`；`subconscious/__init__.py` 的 `__all__` 含 `extract_song_entities` 但整个 subconscious/ 下无此函数（访问即 AttributeError）；`agent/__init__.py` 未导出 `LuoTianyiAgent`。
6. **utils 混入业务**：`utils/enum_type.py` 的 `ContextType`/`ConversationSource` 是会话域枚举；`utils/helpers.py:54` 的 `get_unified_song_name` 是歌曲域逻辑；`utils/vision/image_process.py:1` import FastAPI `UploadFile` 做上传解析。
7. **测试目录与守则 0% 对齐**：`server/tests/` 下 59 个 `test_*.py` 100% 平铺在根目录，无任何模块子目录。

本次重构的目标是把上述可收敛差距处理掉，使新交互方式（电话、具身、游戏世界）接入时只需写 Adapter 和 stage 流程，不必复制"预处理→记忆→提示词→LLM→解析→能力"整条链路；测试可按模块回归；依赖方向可静态检查。

## 2. 目标与非目标

### 目标（第一批）

收敛差异文档第 3、4、5、6、7、8、9、10、11 条（Agent 门面、调用点改走门面、stage↔adapter 窄接口、world 注入收窄、utils 反向依赖、全局定位器第一批、包导出一致性、world↔capabilities 反向依赖），外加测试目录按守则 100% 归位。

**全程行为零变化**：对外 REST/WS 协议、数据库内容与位置、日志行为均不变。

### 非目标（本次明确不做）

- 不实现电话 CallStream（差异第 12 条，属功能开发）；
- 不做物理目录搬移：`chat_session` 不改名 stage、不新建顶层 adapter 目录（差异第 1、2 条，官方迁移顺序放在⑥之后）；
- 不动 `server_main.py` 的 17 个 REST 处理器（第二批评估）；
- 不拆分 9 个 >500 行自有文件（第二批）；
- 不收缩 `get_system_runtime/get_agent_runtime/get_admin_shell`（定位器第二批）；
- 不移植 fork 独有 dev 提交（server hardening 约 +7096 行，单独任务）；
- 不搭建 CI（仓库当前无任何 CI，另立任务）；
- 不新增产品功能、不改任何用户可见行为。

## 3. "用户"与使用路径

本重构无终端用户可见变化（见验收标准 1）。受影响的是开发者与 AI：

- **修改某模块行为**：先读该模块接口文档 README → 从模块公开 interface 写测试 → 实现；代码放归属模块目录，测试放对应 tests 子目录；
- **接入新交互方式**：只写 Adapter（外部协议→Stimulus）+ stage 流程，经 `agent_runtime.get_agent()` 门面调用角色，不得绕过门面直接取得 subconscious/capabilities/数据库/提示词对象；
- **新增公开 interface**：必须先更新接口文档 spec，评审通过后才实现。

## 4. 模块归属与公开 interface

模块设计已由上游完成（守则 + 接口文档各模块 README + 差异文档及其建议迁移顺序），本 PRD 不重复设计。**全程唯一新增的公开 interface 是 Agent 门面的 `handle_stimulus(stimulus, interaction_context)`**，其定义已写在 `接口文档/agent/README.md` 的"目标接口（尚未实现）"章节，第一版纯委托现有管线，不重写内部实现；其余一律不新增、不扩大公开 interface。若实现中发现必须新增或扩大，立即停止并另行确认。

## 5. 改造清单（33 个代码/测试切片 + 片 0 文档）

一片一 PR，一片只解决一个可独立验证的问题；除标注外行为零变化。测试归位的逐文件映射见进度文档附录 A。

### 片 0｜文档

创建本 PRD + 进度文档（含映射表与证据复核记录）。不碰任何代码。

### 批次 1｜包导出修复（差异#10，每包一片，零行为变化）

| 片 | 内容 | 验证 |
|---|---|---|
| 1 | `system/__init__.py:8` 死引用（指向不存在的 `src.chat_session.conversation`，实际模块在 `chat_session/dependency/conversation_service.py`）修正 | import 冒烟 + 全量回归 |
| 2 | `capabilities/__init__.py`：`__all__` 删未定义 `CapabilityRegistry`、补 `CapabilityManager` | 同上 |
| 3 | `subconscious/__init__.py`：删不存在的 `extract_song_entities` 导出（含 `__getattr__` 路由） | 同上 |
| 4 | `agent/__init__.py`：补导出 `LuoTianyiAgent` | 同上 |

### 批次 2｜测试归位（守则"tests 目录管理"；纯移动不改内容；每片前后 `pytest --collect-only` 数量一致 + 全量跑一遍）

| 片 | 内容 |
|---|---|
| 5 | pytest.ini 注册 `real_llm` marker（纯配置） |
| 6 | chat_stream/pipeline/topic 系 6 个 → `tests/stage/` |
| 7 | websocket/认证/限流系 8 个 → `tests/adapter/` |
| 8 | runtime/admin/database/event_store 系 15 个 → `tests/system/` |
| 9 | world 系 8 个 → `tests/world/` |
| 10 | capability/tts/diary/dynamics 系 7 个 → `tests/capabilities/` |
| 11 | LLM/logger/preferences 系 6 个 → `tests/utils/` |
| 12 | 跨模块流程（legacy_account_atomicity 等）→ `tests/integration/`（按附录 A 映射执行） |
| 13 | 其余单点（agent/agent_runtime/subconscious 系 8 个）按映射归位 |

### 批次 3｜Agent 门面（差异#3/#4）

| 片 | 内容 | 验证 |
|---|---|---|
| 14 | 新增门面：`get_agent()` 返回只暴露少量公开 interface 的门面，第一版 `handle_stimulus()` 纯委托现有管线（PRD §4 已声明的新增 interface）；红测试先行（`tests/agent_runtime/`，Fake LLM/Fake capability 走既有 seam） | 新门面测试 + 全量回归 |
| 15 | AgentRuntime 8 个业务方法（:189-285）标注"过渡接口，禁止新增调用方"（docstring + 接口文档，零行为变化） | 文档一致性检查 |

### 批次 4｜stage 改走门面（差异#5，按调用路径一片一路）

| 片 | 内容 |
|---|---|
| 16 | 主聊天轮次链路改调 `agent.handle_stimulus` |
| 17 | reflex 边路改走门面 |
| 18 | topic 规划/落地方链路改走门面 |

（实现时若内部交织无法干净拆分，按可独立验证的边界继续细分。）

### 批次 5｜stage↔adapter 窄接口（差异#6）

| 片 | 内容 |
|---|---|
| 19 | `chat_pipeline/chat_stream.py:16` 去 `WSEventType` 直接依赖；port/事件类型 spec 先写入 stage 接口文档再实现 |
| 20 | ChatStream/ChatStreamManager 去 `WebSocketConnection` 直接依赖，注入窄发送 port |
| 21 | stage 去整个 `SystemRuntime` 依赖，改显式窄依赖注入 |

### 批次 6｜world（差异#7/#11）

| 片 | 内容 |
|---|---|
| 22 | `WorldTask` 注入收窄：不再拿整个 SystemRuntime，按任务显式窄依赖（超 500 行则按任务再拆） |
| 23 | `singing_manager.py:12` 对 `world.WishlistManager` 的反向依赖，用接口注入解耦 |
| 24 | `daily_new_song_fetcher.py:22` 直连 `subconscious.song_database`，改经归属模块公开接口/注入 |

### 批次 7｜utils 反向依赖（差异#8，一片一事）

| 片 | 内容 |
|---|---|
| 25 | `ContextType`/`ConversationSource`（`utils/enum_type.py`）迁入 `domain` |
| 26 | `get_unified_song_name`（`utils/helpers.py:54`）归歌曲域 |
| 27 | `utils/vision/image_process.py` 去 FastAPI 依赖，上传解析移回 adapter 层 |
| 28 | `llm_module.py:5`/`vlm_module.py:5` 观测全局入口改注入，打破 system→utils→system 环 |
| 29 | `client_llm_executor.py:106` 的 `bind(stream_manager)` 反向绑定解除（stage 侧注入回调） |

### 批次 8｜全局定位器第一批（差异#9，一片一个）

| 片 | 内容 |
|---|---|
| 30 | `get_database_manager()` 隐式自建消灭（`database_service.py:183`），调用方显式注入 |
| 31 | `get_GCSM()` 与模块全局赋值（`chat_stream_manager.py:338,341`、`chat_session_manager.py:50`）移除，消费方改注入 |
| 32 | `song_database` 隐藏自动初始化（`song_database.py:42-70`）改显式初始化 |
| 33 | 观测全局入口消费方注入化：`topic_planner/topic_replier/reflection_worker/global_speaking_worker/attention` 5 处改注入（跨模块改不完则拆 stage 侧/subconscious 侧两片） |

**完成后另行立项**（不在本 PRD）：第二批定位器（get_system_runtime/get_agent_runtime/get_admin_shell）、⑥物理搬移（chat_session→stage 改名、adapter 顶层归位）、`server_main.py` 17 个 REST 处理器下沉、9 个 >500 行自有文件拆分、CI 搭建、fork dev 独有提交移植。

## 6. 验收标准

1. **行为不变**：基线 pytest 收集数与通过/失败/跳过数在重构前后一致（环境性跳过逐条记录原因）；对外 REST/WS 协议无 diff；
2. **依赖方向可静态验证**（每片附 grep 检查命令与结果）：`chat_session` 不再 import `system.user_interface`；capabilities 不 import world；utils 不 import system 全局入口与 chat_session；`utils/vision` 不 import fastapi；
3. 每片 PR ≤500 行手写改动、只含本清单中一项、进度文档同步更新；
4. 批次 8 完成后 `get_database_manager` 隐式自建、`get_GCSM`、`song_database` 隐藏初始化在代码中不存在；
5. 测试目录与守则目标一致，pytest.ini 注册的 markers 均有说明；
6. 差异文档逐条更新收敛状态（每片合入后标注）。

## 7. 批次与评审节奏

每片 = 自上游 `refactor/agent` 最新提交拉独立小分支（推送至 fork `jinyiwei2012`）→ PR 交到上游 `SheepLiu712/Agent-LuoTianyi` 的 `refactor/agent` → 需求方逐一审查合并 → **每片完成即停**，确认后再进下一片。不设 fork 内集成分支，不做里程碑整体 PR——每片本身即独立可审 PR。

## 8. 风险与依赖

- **环境重依赖**：torch/gsv-tts/chromadb/redis 等可能限制本机可跑测试范围，基线如实记录，环境性跳过逐条列明，不伪造结果；
- **批次 4/5 改动面最大**（`chat_session` 共 3,582 行）：靠"一路一片"拆分与既有重连/幂等测试兜底；
- **fork 与主仓库 dev 已分叉**（fork 独有 9 提交，其中 server hardening +7096/-730）：本分支基于 `origin/refactor/agent`，不携带 fork 提交，移植另行立项；
- **附录 A 的"初判"映射**：按文件名与职责判定，执行批次 2 时逐文件复核，复核结论记录在对应 PR。

## 9. 埋点与页面行为

不适用：无 UI 变化；观测服务（ObservabilityService）的写入接口与数据格式保持不变。
