# agent_runtime 对外接口


AgentRuntime 直接装配角色身份和路由器；新 Agent 门面不接收数据库会话工厂。数据库仍由 SystemRuntime 管理，供角色运行时的业务依赖使用。

## #63 装配与查找契约

状态：已实现。门面入口和在途工作等待见 [Agent 门面 SPEC](../agent/facade.md)。

- `AgentRuntime` 初始化时在 `server/src/agent_runtime` 内完成新 Agent 的装配，为每个启用角色缓存一个实例；依赖通过现有初始化参数显式传入。角色身份和内部协作者由运行时绑定。
- `get_agent(character_id: str | None = None) -> Agent` 查找新门面。只有 `None` 使用默认角色；未知、禁用、空字符串或空白 ID 抛出 `KeyError`，其他非字符串参数抛出 `TypeError`。同一运行时内重复查找返回同一实例。
- 初始化必须完成全部实例装配才对外发布运行时。依赖装配失败时抛出异常，按现有初始化回滚路径清理已创建资源和全局引用。
- `shutdown()` 首先停止新 Agent 接受工作，再有界等待已接受的门面调用退出，然后执行现有资源关闭；等待超时保留依赖并抛 RuntimeError，重试继续等待；关闭成功后查找仍可返回原门面，调用门面会被拒绝。

`get_character_runtime(...)` 仍是运行时内部按角色取得 `CharacterRuntime` 的装配接口；`AgentRegistry.get/all` 仍保存意识对象。#88 已删除 `get_default_agent()`、`SystemRuntime.agent` 和八个旧业务代理，不再提供默认意识对象或 TopicReplier 的公共旁路。

契约测试覆盖初始化、缓存、严格角色查找、失败清理、关闭和上述兼容入口；现有关闭与初始化回滚测试中的适用场景一并回归。

## 模块职责

`server/src/agent_runtime` 是角色工厂和运行时注册表。调用方用角色 ID 取得 Agent，不负责具体业务决策。查找用法是：

```python
agent = agent_runtime.get_agent(character_id)
```

路由装配见 [Handler 路由 SPEC](../agent/handler-routing.md)：AgentRuntime 构造每角色的路由器并注入 Agent：刺激路由登记 InteractionEndingHandler，以及文本、图片、语音、打字、选图、触摸的 ChatPreprocessingHandler，占位期限回复 ChatReplyHandler 和独立的 ChatReflectionHandler。行动路由登记 SayHandler。每个角色的 ContextFactory 由运行时装配在 context_factories 中，仅提供 create。SystemRuntime 向 StageManager 注入按角色取得创建模块的函数；结束处理器不再接收 factory。

## 稳定入口

### `AgentRuntime`

- `AgentRuntime(config, llm_service, capability_manager, database_manager)`：创建运行时容器。
- `wire_dependencies(...)`：补充运行所需依赖。
- `ensure_dependencies()`：验证注册表、角色和服务已经就绪。
- `get_agent(character_id=None) -> Agent`：按角色 ID 返回 Agent；省略 ID 时使用默认角色。
- `await shutdown()`：关闭角色运行时并释放相关资源。

`get_agent` 返回缓存的新门面；显式角色不存在时抛出 `KeyError`。

### 全局运行时兼容入口

- `set_agent_runtime(runtime)`：设置进程级 AgentRuntime。
- `get_agent_runtime() -> AgentRuntime`：取得已设置的运行时；未设置时抛出 `ValueError`。
- `clear_agent_runtime()`：清除进程级引用。

这些全局函数供旧代码及测试取得或清理进程级运行时引用。

## 当前过渡接口

仍保留 `get_character_runtime(character_id=None) -> CharacterRuntime` 与 `get_state(...)` 供运行时内部技能和注册表装配；业务调用必须经 `get_agent()` 返回的两接口门面。

注册表类型：

- `CharacterRegistry.get(character_id)`、`resolve_targets(...)`：解析角色配置和刺激目标。
- `AgentRegistry.get(character_id)`、`all()`：保存并读取已创建的 Agent。
- `CharacterRuntime`：聚合角色配置、意识、subconscious、reflex 和能力管理器。其 conscious 保存旧 LuoTianyiAgent。

## 正常与异常行为

- 首次初始化会创建角色相关对象并连接共享能力和数据库；这是装配副作用。
- `get_agent` 只查缓存，不重复创建 Agent。
- 未初始化、缺依赖、未知角色会明确失败。
- `SystemRuntime.shutdown()` 统一调用该运行时的 shutdown。

## 使用示例

调用 `get_agent("luotianyi")` 取得绑定该角色的门面后，可以调用其两个业务方法。生产路由支持交互结束刺激及 SAY 的 TTS、预制音频分支；未登记的刺激或行动返回对应 UNSUPPORTED 报告。

## 已覆盖的契约场景

- 同一角色 ID 多次 `get_agent(...)` 返回注册表中的同一 Agent，不重复初始化共享资源。
- 未知角色 ID 抛出 `KeyError`；未设置全局运行时时 `get_agent_runtime()` 明确失败。
- 初始化后关闭能够释放角色资源；部分初始化失败不会留下可取得的半成品 Agent。
