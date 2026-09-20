# Server 模块边界重构

## 目标

本轮重构把角色能力、外部适配和中立基础设施放回各自模块，最终满足：

1. `src/resources` 与 `src/system` 完全删除，不保留兼容目录或生产导入。
2. TTS、唱歌、图像理解和预制语音归入 `src/agent/skills`；所有 Agent 共享同一组 Skill，并通过每次调用的 `SkillInvocation` 区分角色、用户、交互和取消状态。
3. 数据库、媒体持久化、模型服务、配置和可观测性归入 `src/infrastructure`。
4. HTTP、WebSocket 物理信道和管理端入口归入 `src/web`；用户与管理用例归入 `src/application`。
5. `src/adapter` 只负责外部信道与 Agent/Stage 语义转换、业务消息接收判定和逻辑绑定。
6. `src/server_runtime.py` 是唯一组合根；删除 `SystemRuntime`、`InfrastructureRuntime` 及业务代码中的服务定位器式访问。
7. `src/utils` 只保留无业务语义、无连接、无生命周期的纯工具。
8. 为模型服务、预制语音、角色 Skill、持久化 Adapter、HTTP/WebSocket 路由和 ServerRuntime 生命周期补齐模块测试。
9. 所有测试通过；本轮重构涉及的代码通过 Black 和 Ruff。未修改的遗留代码只允许通过明确的检查范围排除，不能用全局 ignore 掩盖新债务。

## 必须保持的行为不变量

- HTTP 路径、认证规则、状态码和响应结构不变。
- WebSocket 消息格式、确认与结束通知语义不变。
- LLM/VLM 供应商选择、客户端委托、降级路径和 Prompt 内容不变。
- TTS 的并发请求隔离、取消、临时音频和关闭语义不变。
- 数据库 schema、既有数据路径和媒体标识不变。
- 预制语音的稳定名称、文本、表情、音频和顺序不变。
- Agent 对外仍只暴露 `handle_stimulus` 与 `realize_action_plan`。
- Stage、World 和 Adapter 不得绕过 Agent 门面取得 Skill 或基础设施内部对象。

## 目标依赖方向

```text
web ───────> application
 │                │
 └──> adapter <───┘
         │
       stage ---> agent/skills ---> infrastructure
         │                              ^
       world ---------------------------┘

server_runtime 只负责构造、注入、启动、回滚和关闭
```

`infrastructure` 不依赖 `adapter`；业务模块不依赖 `server_runtime`。模块的公开 interface 同时是测试 seam，测试不锁定私有实现。

## 计划与验收

| 阶段 | 内容 | 验收证据 | 状态 |
| --- | --- | --- | --- |
| 0 | 冻结基线、依赖和路由清单 | 当前测试、Ruff、导入与引用扫描 | 已完成 |
| 1 | `utils` 中 LLM/VLM 迁入 `infrastructure/models`，拆开 WebSocket 客户端委托 | 模型模块测试；无 `infrastructure -> adapter/system` | 已完成 |
| 2 | 预制语音收口到 `agent/skills/expression`，删除 `src/resources` | Catalog 模块测试；零旧导入 | 已完成 |
| 3 | 图像理解迁入认知 Skill | 图像理解模块测试；删除旧目录 | 已完成 |
| 4 | TTS 全部迁入 Speaking Skill | 生命周期、并发和取消测试；删除旧目录 | 已完成 |
| 5 | 唱歌能力迁入 Singing Skill，拆分歌曲知识语义与持久化 | 唱歌模块测试；删除旧目录 | 已完成 |
| 6 | 数据库、配置、可观测和 DueEvent 实现迁入 infrastructure | 持久化与观测测试；零 `system.database/observability` 导入 | 已完成 |
| 7 | HTTP、WebSocket、Admin 初步迁入 adapter | 路由、认证、WebSocket 集成测试 | 已完成，后续在阶段 10 收紧 |
| 8 | 建立 `ServerRuntime`，删除旧 Runtime 和整个 `src/system` | 生命周期测试、全量测试、残留扫描 | 已完成 |
| 9 | 文档、Ruff/Black 范围和最终验收 | 全量测试、Ruff、Black、目录与导入审计 | 已完成 |

阶段按纵向行为切片推进：先为目标 interface 写会失败的测试，再做足以通过的迁移；不为私有类和搬迁路径编写实现耦合测试。

## 当前进度

### 2026-09-19 启动与基线检查

- 已确认工作分支：`qa/contract_finish`。
- 已确认开始时工作树干净，HEAD 为 `89c6e994 docs：归档不要的文档`。
- 已确认旧目录仍存在：`src/resources`、`src/system`、`src/infrastructure/{speech,singing,image_understanding}`。
- 已确认模型代码仍位于 `src/utils/llm`、`src/utils/llm_service.py` 和 `src/utils/vision/vlm_*`。
- 已确定测试 seam：模型服务、预制语音 Catalog、角色 Skill、持久化 Adapter、HTTP/WebSocket 路由和 ServerRuntime 生命周期。
- 该条记录是启动时快照；后续阶段已开始修改并持续记录切片验证结果。

### 2026-09-19 阶段 0—2

- 基线 Ruff 通过；启动时全量测试为 1289 passed、17 skipped。
- LLM/VLM、Embedding、Prompt 和模型注册迁入 `infrastructure/models`；可观测迁入 `infrastructure/observability`；通用图片处理迁入 `infrastructure/media`。
- 客户端模型执行器迁入 `adapter/websocket`，模型模块改为依赖 `ClientModelExecutor` interface，`infrastructure` 不再反向导入 Adapter。
- 删除 `src/utils/llm`、`src/utils/vision` 和旧 `system/observability` 目录；模型与可观测相关测试 31 passed，切片 Ruff 通过。
- 新增按角色索引的 `PreparedSpeechCatalog`，由 SharedSkills 唯一持有；触摸、首次登录和 Say 共用该 Catalog，不再重复加载 manifest。
- 预制语音配置改为 `prepared_speech.characters.<character_id>.manifest`，洛天依资源路径修正为真实的角色级 manifest；触摸配置只保留稳定资源名称。
- 删除 `src/resources`；预制语音、触摸、首次登录、Say、Stage 与 WebSocket 相关测试 94 passed，切片 Ruff 通过。

### 2026-09-19 阶段 3

- 将媒体解析、Base64 编码、VLM 注册与图片描述收口为 `ImageUnderstandingSkill`，SharedSkills 直接持有该深模块。
- 图像理解配置从 `infrastructure.image_understanding` 迁至 `agent_runtime.skills.image_understanding`；基础设施只保留中立媒体解析和 VLM 模型服务。
- 删除 `src/infrastructure/image_understanding`，移除 `InfrastructureRuntime.image_understanding`。
- 图像理解、媒体、配置编辑和并发预处理相关测试 67 passed；本切片 Ruff 通过。

### 2026-09-19 阶段 4

- 将 Speaking Skill、异步流适配、SpeechBackend、TTSModule、TTSServer 和错误语义收口到 `agent/skills/expression/speaking`。
- TTS 配置迁至 `agent_runtime.skills.speaking.characters`；Speaking Skill 构造并拥有 worker，SharedSkills/AgentRuntime 负责关闭与初始化回滚。
- 删除 `src/infrastructure/speech`，`InfrastructureRuntime` 不再构造或关闭 TTS。
- Speaking、TTS 生命周期、并发取消、WebSocket 和配置相关测试 84 passed；TTS 模块 Ruff 通过。

### 2026-09-19 阶段 5

- 将 Singing Skill、歌曲选择/渲染 backend、角色曲库 manager、情绪标注和愿望清单收口到 `agent/skills/expression/singing`；配置迁至 `agent_runtime.skills.singing`。
- SharedSkills 构造并持有唱歌实现；回复编排、学歌派发和 World 学歌任务只通过该 Skill 所有的 backend 协作，`InfrastructureRuntime` 不再组装角色唱歌能力。
- 将 `SongEntityLinker` 迁入 `agent/skills/cognitive`，将歌曲知识 SQLAlchemy adapter 迁入 `infrastructure/persistence/song_knowledge.py`。
- 删除 `src/infrastructure/singing` 和 `src/infrastructure/song_knowledge`；唱歌切片 109 passed，歌曲知识切片 26 passed，切片 Ruff 通过。

### 2026-09-19 阶段 6

- 将数据库、数据库服务和 DueEvent 查询实现迁至 `infrastructure/persistence`；DueEvent 契约下沉到 `domain/stage`。
- 将配置存储、密钥、校验和模型配置编辑迁至 `infrastructure/config`；删除无人使用的旧知识图谱实现及其配置键。
- 对持久化服务和配置校验中超过 10 的函数拆分职责；持久化切片 169 passed、2 skipped，配置/Admin 切片 44 passed，Ruff 通过。

### 2026-09-19 阶段 7

- 当时先将公开 HTTP、管理端和 WebSocket 服务迁至 `adapter` 作为过渡；该中间态已由阶段 10 的 Web/Application/Adapter 收口替代。
- WebSocket 输入准备和串行投递拆成窄步骤，复杂度不超过 10；客户端模型执行器作为外部协议 Adapter 实现 Infrastructure 定义的端口。
- 新增 Adapter 模块归属测试；HTTP、Admin 与 WebSocket 切片 185 passed，Ruff 通过。

### 2026-09-19 阶段 8

- 以 `src/server_runtime.py` 取代 `SystemRuntime`，删除 `InfrastructureRuntime` 和整个 `src/system`。
- `AgentRuntime` 直接接收数据库和媒体解析器；`ServerRuntime` 是唯一构造、注入、启动、回滚和关闭入口。
- World 学歌任务改为依赖 World 所有的 `SingingBackendPort`，由组合根显式注入，不再穿透 Agent 内部 Skill。
- 新增组合根、持久化、配置和 Adapter 归属测试；架构 B1–B8 检查全部通过，生产代码残留扫描为零。

### 2026-09-19 最终验收

- 全量测试及覆盖率门禁：1304 passed、17 skipped；重构统计范围行覆盖率 76.17%，超过 40% 下限。
- Ruff 全部通过；Black 检查覆盖 202 个重构范围文件并通过；所有受检函数均未超过复杂度 10。
- 架构边界 B1–B8、`git diff --check`、脚本编译和旧导入/目录扫描通过。
- 17 个跳过项均为已有的显式外部 E2E 条件，包括真实 LLM/VLM、网络、凭据或音频运行环境；默认测试不把这些环境缺失计作成功证据。
- 持久架构说明已写入 `设计文档/Server模块边界与组合根.md`，测试矩阵和文档索引已同步。

### 2026-09-20 阶段 10——Web、Application 与 Adapter 收口

- 新建 `src/web`，接管 HTTP/Admin 路由、请求模型、WebSocket 报文、物理连接和协议服务。
- 新建 `src/application`，接管用户账号/对话用例以及 Admin 运行时、配置和系统动态等管理用例。
- `src/adapter` 只保留 WebSocket 与 Agent/Stage 之间的输入转换、输出转换、Stage 绑定和客户端模型执行适配。
- 将业务输入的支持判断、去重、校验、过载判定和 Stimulus 提交移入 `WebSocketAdapter`；`WebSocketService` 不再依赖 Stage 或 Adapter。
- `ServerRuntime` 分别持有 `WebSocketService` 与 `WebSocketAdapter`，组合根显式连接物理信道、Adapter 和 Stage。
- 新增 B9–B10 静态边界门禁，禁止 Adapter 重新吸收 FastAPI 路由、物理网络服务或管理用例，并禁止 Application 依赖 FastAPI/Web 传输实现。
- 全量验收为 1306 passed、17 skipped；重构统计范围行覆盖率 76.10%，Ruff、Black 和 B1–B10 门禁通过。

## 最终完成审计

完成前必须逐项取得当前工作树证据：

- [x] `src/resources` 不存在。
- [x] `src/system` 不存在。
- [x] `src/infrastructure/speech`、`singing`、`image_understanding`、`runtime.py` 不存在。
- [x] `src/utils` 中不存在 LLM/VLM 模型生命周期代码。
- [x] 生产代码中不存在旧模块导入字符串。
- [x] 目标目录和依赖方向与本文件一致。
- [x] `src/adapter` 中不存在 HTTP/Admin 入口或 `WebSocketService`。
- [x] 新增模块测试覆盖所有约定 seam。
- [x] 全量测试通过，跳过项有既有且明确的理由。
- [x] 重构范围 Black 与 Ruff 通过。
- [x] 架构说明和测试说明同步到最终实现。
