# world 对外接口

## 模块职责

`server/src/world` 负责角色在聊天之外持续发生的世界活动，例如城市漫步、B 站事件、新歌发现和学唱任务。world 可以产生新的刺激或内容，但不应成为聊天请求的协议入口。

## 对外接口

### `WorldRuntime`

- `set_system_runtime(runtime)` / `wire_dependencies(...)`：注入系统级依赖。
- `initialize_modules()`：创建并连接已启用的世界模块。
- `start_background_services()`：启动 WorldClock 和世界后台任务。
- `await stop_background_services()`：停止调度器及其拥有的任务。
- `ensure_dependencies()`：在启动前检查配置和依赖。

### `WorldClock`

- `register_interval_action(...)`：注册按固定间隔执行的任务。
- `register_daily_action(...)`：注册每天指定时刻执行的任务。
- `start()`、`await stop()`：控制调度循环。
- `is_running()`：查询调度器状态。

### `WorldTask`

- `initialize(system_runtime)`：绑定运行环境。
- `await run_once()`：立即运行一次任务，供调度和测试调用。
- `ensure_dependencies()`：检查任务依赖。
- 任务元数据读取方法：供运行时登记名称、调度和状态。

具体任务由 `citywalk`、`bili_event_updater`、`get_new_songs`、`learn_sing_songs` 等包实现。

## 当前跨模块兼容接口

- `WishlistManager` 的愿望新增、查询、领取和状态更新方法目前被唱歌能力使用。
- QQ 音乐凭据刷新、歌曲和歌词下载等函数目前被 system 管理接口调用。

这些接口是当前事实，但它们把 world 的内部实现暴露给 capabilities/system。后续应由 `WorldRuntime` 或专用的窄服务接口承接，新增调用不要继续扩大这组接口。

## 正常与异常行为

- `start_background_services()` 只负责安排任务；单个世界任务的成功或失败应独立记录，不能让一次网络失败终止整个时钟。
- 世界任务可能访问外部网络、模型、数据库、文件和第三方平台，具有明显副作用。
- `stop_background_services()` 应取消本运行时创建的任务并等待退出，不能遗留跨测试的后台协程。
- 未配置密钥、外部服务不可用或数据不完整时，任务可报告跳过/失败，但不得伪报已发布或已学会。

## 使用示例

每天的新歌任务由 `WorldClock` 触发 `run_once()`，查询新歌并形成待学习记录；如果后来需要通知用户，应生成内部事件交给正常交互链，而不是直接操作某个用户的 WebSocket。

## 应覆盖的契约场景

- 一个周期任务失败不会停止其他已登记任务，失败原因可从日志/观测中读取。
- `stop_background_services()` 后时钟和所有归属任务均退出，不再触发外部写入。
- 外部凭据缺失或网络超时时，任务报告跳过/失败，不生成“已发布”“已学会”的成功记录。
