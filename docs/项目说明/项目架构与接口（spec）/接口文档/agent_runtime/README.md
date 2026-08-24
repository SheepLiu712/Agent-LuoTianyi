# agent_runtime 对外接口

## 模块职责

`server/src/agent_runtime` 是角色工厂和运行时注册表。调用方用角色 ID 取得 Agent，不负责具体业务决策。目标用法是：

```python
agent = agent_runtime.get_agent(character_id)
```

## 稳定入口

### `AgentRuntime`

- `AgentRuntime(config, llm_service, capability_manager, database_manager)`：创建运行时容器。
- `wire_dependencies(...)`：补充运行所需依赖。
- `ensure_dependencies()`：验证注册表、角色和服务已经就绪。
- `get_agent(character_id=None) -> LuoTianyiAgent`：按角色 ID 返回 Agent；省略 ID 时使用默认角色。
- `await shutdown()`：关闭角色运行时并释放相关资源。

`get_agent` 是业务调用首选且应逐步收敛为唯一取 Agent 的入口。角色不存在时抛出 `KeyError`，而不是悄悄换成另一个角色。

### 全局运行时兼容入口

- `set_agent_runtime(runtime)`：设置进程级 AgentRuntime。
- `get_agent_runtime() -> AgentRuntime`：取得已设置的运行时；未设置时抛出 `ValueError`。
- `get_default_agent() -> LuoTianyiAgent`：取得默认角色 Agent。
- `clear_agent_runtime()`：清除进程级引用。

这些全局函数便于旧代码迁移和测试替换；新代码优先通过构造参数获得运行时。

## 当前过渡接口

以下方法现在被其他模块使用，但目标架构下应缩回 Agent 内部或运行时装配层：

- `get_character_runtime(character_id=None) -> CharacterRuntime`、`get_state(...)`。
- `preprocess_chat_event(...)`、`try_handle_reflex(...)`、`extract_topic(...)`。
- `plan_topic_turn(...)`、`realize_topic_plan(...)`、`write_topic_memories(...)`。
- `detect_dates_for_topic(...)`、`update_user_profile_by_context(...)`。

注册表类型：

- `CharacterRegistry.get(character_id)`、`resolve_targets(...)`：解析角色配置和刺激目标。
- `AgentRegistry.get(character_id)`、`all()`：保存并读取已创建的 Agent。
- `CharacterRuntime`：聚合角色配置、意识、subconscious、reflex 和能力管理器。该对象目前可取得，但不应作为跨模块数据结构继续扩散。

## 正常与异常行为

- 首次初始化会创建角色相关对象并连接共享能力和数据库；这是装配副作用。
- `get_agent` 本身只查注册表，不应每次重新创建 Agent。
- 未初始化、缺依赖、未知角色会明确失败；调用方应在启动阶段发现，而不是在首条用户消息时降级。
- `shutdown` 应在 `SystemRuntime.shutdown()` 中统一调用。

## 使用示例

假设 stage 收到目标角色为 `luotianyi` 的话题：它通过注入的 `AgentRuntime` 调用 `get_agent("luotianyi")`，只拿到 Agent 外观并请求处理。它不读取 `CharacterRuntime.mind`，也不自行查找 capability。

## 应覆盖的契约场景

- 同一角色 ID 多次 `get_agent(...)` 返回注册表中的同一 Agent，不重复初始化共享资源。
- 未知角色 ID 抛出 `KeyError`；未设置全局运行时时 `get_agent_runtime()` 明确失败。
- 初始化后关闭能够释放角色资源；部分初始化失败不会留下可取得的半成品 Agent。
