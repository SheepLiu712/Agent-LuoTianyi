# Server 模块边界与组合根

本文记录 Server 当前需要长期保持的模块职责、依赖方向和组合规则。实现细节以源码和自动化门禁为准。

## 模块职责

### `src/agent` 与 `src/agent_runtime`

- `agent` 拥有角色的认知与表达能力。图像理解、预制语音、TTS、唱歌、歌曲知识处理均属于 Skill。
- Skill 实例由 `SharedSkills` 统一构造并被全部角色 Agent 共用；用户、角色、交互和取消状态通过调用上下文传入，不通过复制 Skill 隔离。
- `agent_runtime` 负责角色注册、角色级记忆和上下文工厂，以及 Agent 门面的构造与关闭。
- Agent 对外业务入口仍只有 `handle_stimulus` 和 `realize_action_plan`。

### `src/infrastructure`

- `models`：LLM/VLM/Embedding、Prompt 和客户端模型执行协议。
- `persistence`：数据库、媒体持久化、歌曲知识持久化和 DueEvent 查询适配器。
- `media`：中立的媒体引用、解析和图片持久存储，不包含角色判断。
- `observability`：日志、指标和追踪生命周期。
- `config`：配置文件、密钥和配置校验。

Infrastructure 提供技术机制，不拥有角色行为，也不依赖 `agent`、`world`、`stage`、`adapter` 或组合根。

### `src/web`

- `http`：公开 HTTP 请求模型、限流、运行时访问和项目计划书注册。
- `websocket`：Wire Message、物理连接、认证、心跳、ACK/NACK 和协议收发。
- `admin`：管理 HTTP 路由和管理 UI 注册。

Web 承载 FastAPI 和 WebSocket 网络语义，不解释 Agent 行为，也不拥有 Stage 生命周期。

### `src/application`

- `user`：账号安全、用户对话读取等用户用例。
- `admin`：AdminShell、运行时管理、配置/密钥协作、QQ 音乐凭据刷新和系统动态发布。

Application 编排非 Agent 的服务端用例。Web 调用这些用例，Infrastructure 提供其持久化和技术机制；Application 不依赖 FastAPI、HTTP Request/Response 或 WebSocket 实现。

### `src/adapter`

- `websocket/adapter.py`：业务消息接收判定、WebSocket 输入到强类型 Stimulus 的转换、Stage 绑定和输出提交。
- `websocket/_input.py`：输入语义转换和媒体准备。
- `websocket/_delivery.py`、`_protocol.py`：Agent/Stage 输出到 WebSocket Wire Message 的转换与有序交付。
- `websocket/client_model_executor.py`：通过客户端 WebSocket 实现模型执行端口。

Adapter 位于外部信道与 Agent/Stage seam 之间，只拥有语义转换和逻辑绑定；物理连接归 Web，交互生命周期归 Stage。

### `src/stage`、`src/world` 与 `src/domain`

- `stage` 拥有交互生命周期、排队、取消、结算和输出 sink。
- `world` 负责定时世界任务；需要角色能力时依赖由 World 自己定义的窄端口，而不是读取 Agent 内部对象。
- `domain` 保存跨模块稳定的值对象、事件和端口契约。例如 DueEvent 契约位于 `domain/stage`，实现位于 `infrastructure/persistence`。

### `src/server_runtime.py`

`ServerRuntime` 是唯一组合根。它按顺序构造可观测、模型服务、持久化、媒体解析、AgentRuntime、WorldRuntime、Web 信道、Adapter 和 StageManager，并负责：

- 显式依赖注入；
- 启动后台服务；
- 初始化失败回滚；
- 按所有权顺序关闭资源；
- 清除进程级默认引用。

不再存在 `SystemRuntime` 或 `InfrastructureRuntime`。业务模块不得把组合根当作通用服务定位器；目前 WorldTask 仅使用其已有的数据库、Stage 查询等应用门面，角色唱歌能力通过 `SingingBackendPort` 显式注入。

## 依赖方向

```text
external client
      |
     web
      |
   adapter ------------+
      |                 |
    stage ---> agent ---+--> infrastructure
      |                 |
    world --------------+

server_runtime 构造并连接上述模块，本身不下沉为业务依赖。
```

允许业务模块依赖 `domain`。`infrastructure` 不得反向依赖业务层或外部 Adapter。静态边界由 `scripts/check_architecture_boundaries.py` 的 B1–B8 检查。

## 配置归属

- 角色能力：`agent_runtime.skills.*`。
- 角色和 Agent 行为：`agent_runtime.*`。
- 模型注册和 Prompt：`llm_service.*`。
- 中立媒体解析：`infrastructure.media_resolution`。
- 数据库：`database.*`。
- 世界任务：`world.*`。
- HTTP/WebSocket 连接协议：对应 Web 配置。
- 信道转换、Stage 绑定和输出投递：对应 Adapter 配置。

配置中不保留已删除实现的兼容键。重命名或迁移必须同时更新模板、管理端校验和测试夹具。

## 测试与质量门禁

- 单元测试守住模型、Skill、持久化、配置、Web、Application、Adapter 和组合根等模块 seam。
- 集成测试守住路由、认证、WebSocket、数据库、Stage/World 装配和生命周期。
- 少量 E2E 守住生产装配；需要外部模型、凭据或硬件的用例默认显式跳过。
- Ruff 和 Black 的范围由 `server/pyproject.toml` 定义：覆盖全部新架构目录与本次重构的 World 组合文件；未改造的 World 遗留实现不纳入本轮门禁，不能通过全局 ignore 隐藏新债务。
- 圈复杂度上限为 10。超过上限必须拆分，或在后续变更中给出具体、局部且可审查的例外理由。
