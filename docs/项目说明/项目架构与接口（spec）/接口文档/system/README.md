# system 对外接口

## 模块职责

`server/src/system` 负责应用装配、启动和关闭、数据库、外部接口基础设施、管理后台、网络辅助与可观测性。它是组合根，不承载角色业务决策。

数据库和可观测性接口分别见 [database.md](database.md) 与 [observability.md](observability.md)。

## `SystemRuntime`

### 生命周期

- `await SystemRuntime.initialize(config, observability=None) -> SystemRuntime`：按配置创建数据库、模型、能力、Agent、stage、Adapter 和 world，并连接依赖、启动后台服务。
- `config.capabilities.media_resolution.root`：同一永久媒体根目录同时传给 WebSocket Adapter 的 `PermanentMediaStore` 和 CapabilityManager 的 `FilesystemMediaResolver`。Adapter 先构造只含永久 UUID 引用的候选 `ImageMessage`，验证目标 Stage 存在且可接收后，才在线程池中解码、验证并发布媒体目录；Agent 只接触引用。省略 root 时 resolver 明确失败，Adapter 拒绝图片输入。
- 默认配置将目录设为 `data/media`，`max_encoded_bytes=8388608`、`max_bytes=6291456`。每个永久 UUID 目录包含 `content.bin` 与 `metadata.json`，metadata 保存 MIME 和认证上传用户。编码/解码超限返回 `MEDIA_TOO_LARGE`，且不产生最终媒体目录。
- 发布先写唯一 staging 目录，再以一次目录 rename 发布完整身份；并发相同内容复用，冲突内容拒绝，残缺或损坏的已有身份稳定按 `MEDIA_UNKNOWN` 处理。永久媒体不设 TTL、过期或自动清理；大文件分块和超时策略仍未决定。
- `ensure_dependencies()`：检查运行时各部分是否已经正确装配。
- `await shutdown()`：按所有权顺序停止后台任务和服务，清理进程级引用。

### 只读访问入口

- `agent`：默认 Agent 的兼容入口。
- `websocket_service`：WebSocket Adapter 服务。
- `chat_adapter` / `stage_manager`：生产聊天的共享协议 adapter 与连接/交互生命周期入口；`stage_manager` 缺失时生产聊天和首次登录明确失败，不静默回退旧链。
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

## 首次登录欢迎配置

- `agent_runtime.prepared_speech.manifest`：现有预制语音清单路径。清单条目以名称提供 `audio_path`、`text` 和 `expression`；首次欢迎使用同条目的文字与音频引用，但表达固定为 `normal`，不采用 manifest 的 expression。
- `agent_runtime.proactive.first_login.prepared_names`：按发送顺序配置恰好两个预制语音名称，例如 `["first_greet_1", "first_greet_2"]`。`AgentRuntime` 解析该列表并注入首次登录 handler；handler 不读取文件系统。
- 首次登录的 Stage/Agent 接口使用 `ProactivePromptDue(reason=ProactiveReason("first_login"))`：调用方通过 `StageManager.record_login(user_id, character_id, ...)` 按 `(user_id, character_id)` 记录一次事实，每个已启用角色各消费一次。生产 `UserInterface.login/auto_login` 在认证结果的 `elapsed_from_last_login is None` 时，直接为默认角色记录首次登录；对应 ChatStage 完成连接绑定后开始约 1 秒同步窗口，再进入真实 `handle_stimulus` 链路。handle 容量已满时保留 pending 并延后重试，不越过 `max_stimuli` 也不丢弃。`elapsed_from_last_login is not None` 的回访登录继续调用兼容 `chat_session_manager.on_user_login(...)`，不会进入首次登录 Agent 链。
- 每个名称独立形成一个 `Say(prepared_audio_ref=MediaRef(name), expression="normal", delivery=CONVERSATION)` 计划，显示文字取 manifest，并以 `source=agent` 追加到交互对话。名称缺失时该条返回稳定失败并记录错误，不静默跳过。
- `RETURN_LOGIN` 久别问候仍保持关闭；非首次登录不会由本配置触发欢迎。
- 旧 `chat_session_manager.proactive_topic_maker.activity_res.first_login` 的 `manifest` 与 `resource_names` 配置仍为兼容代码保留；生产首次登录已经使用 `agent_runtime.proactive.first_login.prepared_names` 的 Stage/Agent 路径，回访登录仍保留旧 `on_user_login` 行为且不恢复 `RETURN_LOGIN`。

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

## 角色触摸准入配置（当前事实）

触摸快速反应的准入由**角色配置** `reflex.touch.fast_reply.policy` 决定；`AgentRuntime` 在构造阶段读取并校验，缺省时沿用默认策略：

```jsonc
{
  "character_registry": { "characters": { "luotianyi": { "reflex": { "touch": { "fast_reply": {
    "manifest": "<prepared_speech manifest>",
    "resource_names": ["touch_voice1", "..."],
    "policy": {
      "allowed_regions": ["head", "辫子", "..."],
      "max_touches_10s": 8,
      "max_touches_30s": 16
    }
  } } } } } } }
}
```

- `allowed_regions`（可选）：允许的身体区域别名；默认沿用旧链别名集合（`head`/`body`/`legs`/`hands`/`头`/`辫子`/`耳机`/`袖`/`左腿`/`右腿`/`身体`/`裙子`/`8`/`左手`/`右手`）。
- `max_touches_10s` / `max_touches_30s`（可选）：10 秒 / 30 秒聚合点击次数上限，默认 `8` / `16`。
- **频率窗口本身不可配置**：`TouchClickFrequency` 的 `count_10s`/`count_30s` 由领域类型固定（客户端按 10/30 秒聚合上报），配置只影响**上限**与**区域**。
- **校验时点**：`policy` 不是映射、上限不是正整数、区域集合为空或含空白项，都会在**运行时构造阶段**抛错（类型问题 `TypeError`、取值问题 `ValueError`），不会延迟到触摸到达时才发现。
- **拒绝语义不变**：未知区域或频率超限 → `FAILED` + `UNSUPPORTED_INTERACTION`、`retryable=False`、不产计划、不兜底、不重试。

## 配置字段

`agent_runtime.agent.memory.explicit_intent` 已实现；其余字段仍是 Issue #75（16 首次登录）、#76（17 周期提醒）的目标草案。

### `proactive.first_login.prepared_names`（对应 Issue #75）

```jsonc
{
  "prepared_speech": { "manifest": "<manifest>" },   // 已有：音频清单
  "proactive": { "first_login": { "prepared_names": ["welcome_1", "welcome_2"] } }
}
```

- 文案取自 manifest 中该名称的 `PreparedSpeech.text`，表情固定为 `normal`；
- 名称不在 manifest → 该条失败并记录，不静默跳过；
- `RETURN_LOGIN`（久别问候）保持关闭的开关位置待定。

### `memory.explicit_intent`（对应 Issue #71，过渡期方案）

```jsonc
{ "memory": { "explicit_intent": { "enabled": true, "phrases": ["请记住", "记住", "记一下"] } } }
```

- 作为**过渡期**意图识别（关键词 allowlist）；待总 SPEC 6.4 的模型工具调用落地后应替换；
- 命中后必须「先写后承诺」；失败保留刺激并返回 `FAILED`，不承诺成功；
- `enabled` 控制识别开关；`phrases` 是可扩展短语表，旧默认短语始终兼容；
- 幂等性沿用长期记忆存储的业务证据去重，按 `(character_id, user_id, content)` 隔离，不维护 request/mutation ledger。

### `proactive.idle_threshold_seconds`（对应 Issue #76）

```jsonc
{ "proactive": { "idle_threshold_seconds": 30 } }
```

- 仅对空闲 ≥ 阈值的活跃聊天流检查提醒；由 ChatStage 持有；
- 与 `DueEventProvider`（见 [stage 接口](../stage/README.md)）的 claim/release 配合。

### 未决问题

1. 是否采纳上述键名与层级（`proactive` / `memory`）？
2. 过渡期关键词方案是否接受，替换条件是什么？
3. 这些字段由谁校验（`SystemRuntime` 启动配置检查还是各模块私有配置类型）？
