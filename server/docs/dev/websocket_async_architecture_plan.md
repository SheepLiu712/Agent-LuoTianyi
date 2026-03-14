## Plan: WebSocket异步化与低时延重构

本方案采用“先打通并发收发与任务解耦，再做可观测性，再做记忆检索质量，再扩展业务能力”的四阶段路线，优先解决用户可连续发言、服务端可并行处理、回复首包时延可测可控的问题。核心方法是引入 WebSocket 会话层 + 用户级任务队列 + 响应事件流协议，并把当前串行链路拆为可并行和后台化步骤，随后通过指标采集确认瓶颈主要在 LLM 还是 TTS，再按数据证据做优化。

**Steps**
1. 阶段A-架构基线与风险隔离（阻塞后续）
2. 明确并冻结“现网行为基线”：当前聊天入口 [server_main.py](server_main.py#L141) 调用的是 mock 流程 [src/agent/luotianyi_agent.py](src/agent/luotianyi_agent.py#L71)，先定义迁移验收口径：文本质量、首包延迟、音频可播放性、历史一致性。
3. 定义统一事件协议（输入事件、状态事件、文本增量事件、音频分片事件、完成事件、错误事件、ack事件），确保后续 WebSocket 与内部任务解耦。该步骤与第4步并行。
4. 规划向后兼容策略：保留现有 HTTP SSE 端点 [server_main.py](server_main.py#L141) 作为灰度回退，新增 WebSocket 端点并在客户端逐步切换。
5. 阶段B-WebSocket与异步并发主链路（依赖阶段A）
6. 新增会话连接管理层（ConnectionManager）：维护 user_id 到多连接映射、心跳、断线重连窗口、连接级流控、消息去重（客户端 msg_id 幂等）。
7. 新增用户级输入队列与调度器（Inbox + Worker）：每个用户可持续发送消息，服务端按策略聚合或插队处理，不阻塞下一条上行。建议默认策略为“短窗口聚合 + 最高优先级中断信号”。
8. 将主处理链改为任务图：接收输入后立刻返回 typing 状态事件，并异步推进“上下文读取 + 知识检索 + 规划 + 主回复 + TTS + 分片下发 + 后写入”。其中知识检索和昵称读取继续并行，记忆写入保持后台。
9. 从 mock 切回真实链路：WebSocket 处理统一调用真实流程 [src/agent/luotianyi_agent.py](src/agent/luotianyi_agent.py#L183)，并保留对图片输入的同构事件化入口 [src/agent/luotianyi_agent.py](src/agent/luotianyi_agent.py#L151)。
10. 阶段C-低时延与可观测性（可与阶段B后半并行）
11. 建立请求级追踪：在网关层生成 trace_id，贯穿 Planner、MainChat、TTS、数据库写入，日志记录每阶段起止和耗时，支持按 user_id 和 trace_id 检索。
12. 建立时延拆账指标：至少包含 queue_wait_ms、context_ms、retrieval_ms、planner_llm_ms、mainchat_llm_ms、tts_ms、first_text_ms、first_audio_ms、total_ms。以 P50/P90/P95 输出日报。
13. 基于数据确定首要瓶颈：若 mainchat_llm_ms 为主，优先减少调用与流式输出；若 tts_ms 为主，优先改分段合成与并发策略。避免无数据优化。
14. 阶段D-记忆/术语/复读治理（依赖阶段B稳定）
15. 检索去重升级：把当前前50字符去重 [src/memory/memory_search.py](src/memory/memory_search.py#L72) 升级为“内容哈希 + 语义近重阈值 + 来源优先级去重”，避免同义重复进入提示词。
16. 写入幂等升级：在记忆写入阶段 [src/memory/memory_write.py](src/memory/memory_write.py#L31) 增加“写前相似度检查”，高相似内容改写 v_update，降低重复 v_add。
17. 缓存一致性升级：优化知识缓存覆盖写 [src/database/database_service.py](src/database/database_service.py#L233) 的原子性，减少短窗重复召回。
18. 术语检索层建设：在 memory_search 工具路由前增加轻量术语抽取与归一化（alias、黑话、缩写），命中后注入标准释义与反查词，减少 LLM 自行猜测。
19. 阶段E-好感度与日程系统扩展（依赖阶段D）
20. 新增用户状态域（affinity、recent_events、schedule_slots），以小步快跑方式先读后写：先参与回复决策，再引入写回。
21. 将状态接入 Planner 输入 [src/agent/planner.py](src/agent/planner.py#L29)，通过策略约束影响回复强度、话题选择与主动行为，保持可解释。
22. 设计冲突解决：当长期记忆、实时上下文、好感度、日程冲突时，采用“实时上下文优先 > 用户显式指令优先 > 高置信长期记忆 > 默认人设”。
23. 阶段F-灰度与回滚（可并行准备）
24. 按用户白名单灰度 WebSocket 新链路；保留 SSE 回退开关；建立故障熔断（TTS异常仅文本返回，记忆写入异常不影响主回复）。
25. 制定发布门槛：并发用户数、首包时延、错误率、重复回复率、知识命中率达到阈值再扩大流量。

**程序架构设计**
1. 接入层
2. HTTP（保留）+ WebSocket（新增）双入口；WebSocket 负责长连接、心跳、客户端 ack、重传控制。
3. 会话编排层
4. ConnectionManager + SessionState + MessageRouter + UserInboxQueue + ResponseDispatcher。
5. 决策与生成层
6. Planner（是否回复、回复强度、是否唱歌）+ MainChat（文本/唱歌结构化输出）+ TTSAdapter（文本到音频分段）。
7. 记忆与知识层
8. ConversationManager（上下文）+ MemorySearcher（召回）+ MemoryWriter（写回）+ VectorStore/SQL/Redis/KnowledgeGraph。
9. 观测与治理层
10. TraceLogger + MetricsCollector + PolicyEngine（复读治理、上下文竞争覆盖、降级策略）。
11. 关键异步边界
12. 输入解耦边界：收到消息即入队并立即回状态；生成链路与连接生命周期解耦。
13. 输出解耦边界：文本事件与音频事件可独立到达，客户端按 seq 组装。
14. 持久化解耦边界：主回复完成后异步写入，不阻塞首包与主流。

**推荐技术栈（含可选项）**
1. 连接层
2. 首选 FastAPI 原生 WebSocket（与现有栈一致，改造成本最低）。
3. 备选 python websockets（更轻量，但与现有依赖注入整合成本更高）。
4. 并发与任务
5. asyncio + asyncio.Queue（MVP），后续可演进到 Redis Stream 或 Celery（多进程扩展、跨实例调度）。
6. 协议与序列化
7. JSON 事件协议（MVP），后续可升级 msgpack 降低音频分片开销。
8. 可观测性
9. logging + 结构化 JSON 日志（MVP）；后续接 Prometheus + Grafana；可选 OpenTelemetry 做跨阶段 trace。
10. 记忆检索增强
11. flashtext 或 jieba 做术语抽取；rapidfuzz 做别名/近似匹配；向量层继续 Chroma，后续可评估 Milvus/pgvector。
12. 降级与弹性
13. tenacity（重试）、aiobreaker（熔断，可选）、限流令牌桶（用户级与连接级）。

**Relevant files**
- [server_main.py](server_main.py) - 新增 WebSocket 路由、连接生命周期、回退开关，保留现有 HTTP SSE。
- [src/service/types.py](src/service/types.py) - 扩展事件模型（WebSocket 入出站事件、ack、错误码）。
- [src/agent/luotianyi_agent.py](src/agent/luotianyi_agent.py) - 从单次请求流程改为可重入任务流程，明确首包与后写入边界。
- [src/agent/conversation_manager.py](src/agent/conversation_manager.py) - 上下文读取与摘要更新节流策略，避免并发竞争。
- [src/agent/planner.py](src/agent/planner.py) - 接入快速决策信号、好感度/日程输入槽位。
- [src/agent/main_chat.py](src/agent/main_chat.py) - 响应结构支持文本增量或分句输出，为分段 TTS 提供上游粒度。
- [src/memory/memory_manager.py](src/memory/memory_manager.py) - 检索与写回编排策略调整。
- [src/memory/memory_search.py](src/memory/memory_search.py) - 去重机制升级、术语工具前置、上下文竞争覆盖。
- [src/memory/memory_write.py](src/memory/memory_write.py) - 写入幂等、相似度判重、更新策略。
- [src/database/database_service.py](src/database/database_service.py) - 知识缓存写入原子性与最近更新读取一致性。
- [src/database/vector_store.py](src/database/vector_store.py) - 判重辅助查询、批量接口优化。
- [src/tts/tts_module.py](src/tts/tts_module.py) - 分段合成、首包优先策略、失败降级。
- [config/config.json](config/config.json) - 新增 websocket、queue、metrics、dedup、feature flag 配置。
- [README.md](README.md) - 运行方式、协议说明、灰度与回退说明更新。

**Verification**
1. 单元验证：memory_search 去重策略、memory_write 幂等策略、事件模型序列化反序列化。
2. 集成验证：单用户连续发送 20 条消息不阻塞；多用户并发下每用户消息有序处理。
3. 协议验证：WebSocket 心跳、断线重连、ack 重发、重复 msg_id 幂等。
4. 时延验证：采集并对比 first_text_ms 与 first_audio_ms，确认是否达到目标首包 2-5 秒范围。
5. 回归验证：保留 SSE 路径可用，开关切换后功能等价。
6. 业务验证：歌曲/知识命中正确率、复读率下降、异常场景降级有效。
7. 发布验证：灰度阶段监控错误率与时延分位数，达到阈值再扩容。

**Decisions**
- 先做连接与并发解耦，再做记忆质量优化，不在第一期同步做好感度和日程复杂策略实现。
- 第一阶段保留双通道（SSE + WebSocket），以降低迁移风险。
- 以指标驱动优化顺序，不先验假设瓶颈在 LLM 或 TTS。
- 复读治理以“召回去重 + 写入幂等 + 上下文覆盖”三件套并行推进。

**Scope**
- 包含：WebSocket 接入、异步队列化、时延观测、记忆去重与幂等、灰度回滚机制。
- 暂不包含：跨节点分布式调度、全量更换向量数据库、复杂推荐算法、全自动日程推理引擎。

**Further Considerations**
1. 客户端协议升级策略建议：方案A 先新端口并行；方案B 同端点按协议头升级。推荐方案A，风险更低。
2. 队列实现建议：方案A asyncio.Queue（快）；方案B Redis Stream（可横向扩展）。推荐先A后B。
3. TTS优化路径建议：方案A 分段合成优先；方案B 先并行多句合成。推荐先A，首包收益更直接。
