# Agent 重构不变量测试矩阵

本文件把 `docs/开发进程文档/设计文档/行为不变量与副作用清单（#89 验收前置）.md` 的架构与业务不变量映射到当前自动化测试。单元测试提供局部行为与错误分支的密集证据；下面列出的集成或 E2E 用例负责跨组件边界的验收。

## 全局不变量

| 不变量 | 集成 / E2E 主证据 | 保障内容 |
|---|---|---|
| G1 外部认知只经两个业务入口 | `integration/architecture/test_architecture_boundaries.py`、`integration/agent/test_facade_contract.py`、`e2e/chat/test_production_stage_wiring.py` | 静态禁止旧入口和越层调用；生产装配只经 Agent 门面 |
| G2 world 不依赖 Agent/Stage 内部 | `integration/architecture/test_architecture_boundaries.py`、`integration/world/test_world_stage_registry.py` | 运行时依赖方向和已知只读偏差均被冻结 |
| G3 副作用只经 ActionPlan / EffectRef | `integration/architecture/test_architecture_boundaries.py`、`integration/agent/test_handler_dispatch.py`、`integration/stage/test_world_settlement_wiring.py` | handler 不自造副作用；结算只认已提交效果 |
| G4 handler 不直连基础设施 | `integration/architecture/test_architecture_boundaries.py`、`integration/agent/test_handler_dispatch.py` | 静态依赖边界与真实路由执行共同约束 |
| G5 Stage 持有 context、pending、计时与取消 | `integration/agent/test_context.py`、`integration/stage/test_chat_stage.py`、`integration/stage/test_world_stage.py`、`e2e/chat/test_production_stage_wiring.py` | context 生命周期、重连、顺序和取消归 Stage 管理 |
| G6 单次失败停止且不恢复账本/重投 | `integration/agent/test_handler_dispatch.py`、`integration/lifecycle/test_facade_inflight_shutdown.py`、`integration/stage/test_chat_reply_settlement.py` | 首败停止、保留已完成事实、无隐式重试 |
| G7 world 无实时输出通道 | `integration/architecture/test_architecture_boundaries.py`、`integration/stage/test_world_stage_contracts.py` | world 的 SAY/SING 无通道时明确失败，不借聊天连接发送 |
| G8 去重归各自业务边界 | `integration/stage/test_proactive_due_dispatch.py`、`integration/world/test_world_task_dynamics.py`、`integration/agent/test_diary_operations.py`、`integration/websocket/test_websocket_idempotency.py` | claim、来源唯一性、按角色/歌曲/日期幂等分别由 owner 负责 |
| G9 强类型领域契约不被绕过 | `integration/agent/test_facade_contract.py`、`integration/agent/test_handler_dispatch.py`、`integration/stage/test_world_stage_contracts.py` | 非法顶层值、伪造报告、错误身份和不支持的事实均在跨组件边界拒绝；类型枚举的精确冻结另由 `unit/domain` 保证 |
| G10 失败不冒充成功 | `integration/agent/test_handler_dispatch.py`、`integration/world/test_world_task_dynamics.py`、`integration/stage/test_world_settlement_wiring.py`、`e2e/chat/test_touch_stage.py` | 失败、取消和部分效果均按实际回执结算 |

## 业务链路不变量

| 前置清单章节 | 链路 | 集成 / E2E 主证据 |
|---|---|---|
| §2 | 聊天主链 | `integration/stage/test_concurrent_handling.py`、`integration/stage/test_chat_reply_settlement.py`、`e2e/chat/test_production_stage_wiring.py` |
| §3 | 交互控制与取消 | `integration/stage/test_chat_stage.py`、`integration/stage/test_concurrent_handling.py`、`integration/websocket/test_websocket_adapter.py`、`e2e/chat/test_touch_stage.py` |
| §4 | 主动提醒 | `integration/stage/test_proactive_due_dispatch.py`、`integration/system/test_login_stage_routing.py` |
| §5 | 首次登录欢迎 | `integration/stage/test_first_login_scheduling.py`、`integration/system/test_login_stage_routing.py`、`e2e/chat/test_first_login_welcome.py` |
| §6 | 反思与记忆 | `integration/stage/test_concurrent_handling.py`、`integration/agent/test_context.py`、`integration/persistence/test_subconscious_memory.py` |
| §7 | 明确记忆意图 | `integration/persistence/test_intentional_memory_storage.py`、`integration/agent/test_handler_dispatch.py` |
| §8 | 慢召回多计划 | `integration/stage/test_chat_reply_settlement.py`、`integration/stage/test_concurrent_handling.py`；两计划的细粒度时序由 `unit/agent/test_slow_recall_staged_reply.py` 补充 |
| §9 | citywalk | `integration/world/test_world_task_dynamics.py`、`integration/stage/test_world_settlement_wiring.py` |
| §10 | VCPedia 候选知识 | `integration/agent/test_song_knowledge_acceptance.py`、`e2e/external/test_world_live.py`（显式启用） |
| §11 | 学歌 | `integration/world/test_world_task_dynamics.py`、`e2e/external/test_infrastructure_singing.py`（显式启用） |
| §12 | 动态互动 | `integration/world/test_world_task_dynamics.py`、`integration/agent/test_dynamic_operations.py` |
| §13 | 日记 | `integration/world/test_world_task_diary.py`、`integration/agent/test_diary_operations.py` |
| §14 | B 站同步、QQ 凭据刷新、事件清理 | `integration/world/test_world_task_event_cleanup.py`、`integration/system/test_admin_runtime.py`、`e2e/external/test_world_live.py`（显式启用） |
| §15 | 媒体链 | `integration/websocket/test_websocket_adapter.py`、`integration/stage/test_concurrent_handling.py`、`e2e/external/test_infrastructure_image_understanding.py`（显式启用） |
| §16 | 输出与发送面 | `integration/agent/test_handler_dispatch.py`、`integration/websocket/test_websocket_adapter.py`、`e2e/chat/test_first_login_welcome.py`、`e2e/chat/test_touch_stage.py` |
| §17 | 调度与生命周期 | `integration/lifecycle/test_facade_inflight_shutdown.py`、`integration/lifecycle/test_system_runtime_shutdown.py`、`integration/runtime/test_runtime_shutdown.py`、`integration/world/test_world_stage_registry.py` |
| §18 | 失败与部分效果语义 | `integration/agent/test_handler_dispatch.py`、`integration/stage/test_world_settlement_wiring.py`、`integration/world/test_world_task_dynamics.py` |

外部 E2E 只证明具备环境时的真实依赖可用性，不会把默认跳过写成已通过。生产客户端播放、真实凭据和模型质量等人工边界仍按前置清单附录 C 管理。
