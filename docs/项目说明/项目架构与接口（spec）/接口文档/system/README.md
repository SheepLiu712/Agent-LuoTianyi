# system 对外接口

## 模块职责

`server/src/system` 负责应用装配、启动和关闭、数据库、外部接口基础设施、管理后台、网络辅助与可观测性。它是组合根，不承载角色业务决策。

数据库和可观测性接口分别见 [database.md](database.md) 与 [observability.md](observability.md)。

## `SystemRuntime`

### 生命周期

- `await SystemRuntime.initialize(config, observability=None) -> SystemRuntime`：按配置创建数据库、模型、能力、Agent、stage、Adapter 和 world，并连接依赖、启动后台服务。
- `ensure_dependencies()`：检查运行时各部分是否已经正确装配。
- `await shutdown()`：按所有权顺序停止后台任务和服务，清理进程级引用。

### 只读访问入口

- `agent`：默认 Agent 的兼容入口。
- `websocket_service`：WebSocket Adapter 服务。
- `gcsm` / `chat_stream_manager`：聊天流管理器。
- `conversation_service`：stage 对话上下文服务。
- `activity_maker`：主动话题组件。
- `global_speaking_worker`：全局语音队列。
- `capabilities`：能力管理器兼容入口。

这些属性方便现有代码迁移。新增代码应优先只注入真正需要的窄接口，避免把完整 `SystemRuntime` 传到业务模块。

### 进程级兼容函数

- `init_system_runtime(config) -> SystemRuntime`、`shutdown_system_runtime()`：初始化和关闭默认运行时。
- `set_system_runtime(runtime)`：设置默认运行时。
- `get_system_runtime() -> SystemRuntime`：未初始化时抛出异常。
- `get_system_runtime_optional() -> SystemRuntime | None`：允许未初始化。

## 管理运行时

### `AdminShell`

- `AdminShell.initialize(root_dir, config_path="config/config.json")`：初始化管理配置、密钥、运行时监督和可观测性服务。
- `shutdown()`：停止管理运行时。
- `init_admin_shell(...)`、`get_admin_shell()`、`shutdown_admin_shell()`：进程级管理入口。

### `RuntimeSupervisor`

- `status()` / `public_status()`：取得详细或可公开的运行状态。
- `request_start()`、`request_stop()`、`request_restart()`：安排一次非阻塞状态转换。
- `start()`、`stop()`、`restart()`：等待对应转换完成。
- `validate_current_config()`：检查当前配置是否足以启动核心模块。

### 路由注册

- `register_admin_ui(app, current_dir)`：挂载管理后台静态界面。
- 管理 API 路由提供健康状态、配置/密钥、运行时控制、模型统计、日志、动态和邀请码管理。
- 项目计划路由注册函数：向 FastAPI 组合根注册项目计划查询接口。

## 正常与异常行为

- `initialize` 要么返回已完整装配的运行时，要么回滚本次创建的资源并抛出异常，不能留下“半启动”全局状态。
- `shutdown` 应可处理部分初始化和重复关闭，并尽可能释放所有已拥有资源。
- 启动/关闭会创建或销毁数据库连接、模型客户端、后台协程和外部服务连接，副作用明显。
- 管理接口中的“请求已受理”和“转换已完成”是两个状态；调用者应通过 status 继续确认。

## 使用示例

FastAPI lifespan 启动时调用 `SystemRuntime.initialize(config)`，之后路由从运行时取得 Adapter 或 stage 服务。应用关闭时只调用 `runtime.shutdown()`，由它按照所有权顺序统一清理，而不是由各路由各自关闭共享资源。

## 应覆盖的契约场景

- 完整配置能初始化并通过 `ensure_dependencies()`；任一步初始化失败会回滚已经创建的资源。
- 正常关闭、部分初始化后关闭和重复关闭都不会遗留进程级运行时引用。
- `RuntimeSupervisor.request_start()` 返回“已受理”后，最终状态可变为运行或带明确错误的失败。

## 当前导出注意事项

`server/src/system/__init__.py` 当前尝试从不存在的 `src.chat_session.conversation` 延迟导出 `ConversationService`。修复前应从实际定义模块导入，不要依赖该包级名称。
