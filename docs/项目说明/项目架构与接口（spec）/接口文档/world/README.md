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
- `settlements: WorldSettlementRouter`：世界事实的结算端口。任务在投递前按刺激 ID 登记订阅者，随后收到处理结算（`FactHandlingOutcome`：是否消费、是否产生计划、失败原因；`ignored` 表示明确处理但没有计划）与执行结算（`FactPlanOutcome`：计划结果与已提交 `EffectRef`）。投递被拒用 `discard(stimulus_id)` 撤销登记；未匹配结算与订阅者异常只计数并记录，不打断 Stage。`SystemRuntime` 在创建 `WorldStage` 时把该端口交给 Stage 的两个结算回调。

### `WorldClock`

- `register_interval_action(...)`：注册按固定间隔执行的任务。
- `register_daily_action(...)`：注册每天指定时刻执行的任务。
- `start()`、`await stop()`：控制调度循环。
- `is_running`：只读属性，查询调度器是否处于运行状态。

### 调度与注册行为

`WorldRuntime.initialize_modules()` 根据配置创建任务并向时钟注册，重复调用不重复注册。citywalk、学歌、B 站事件和日记按角色展开；QQ 凭据刷新、VCPedia、动态互动、主动提醒和过期事件清理各注册一个。学歌按可用 singing manager 展开，QQ 凭据刷新要求存在学歌任务；B 站 UID 映射存在时只包含映射中的角色。动态互动使用默认角色。

citywalk、学歌、B 站事件、日记支持总开关及角色覆盖；QQ 凭据刷新和动态互动支持总开关。VCPedia、主动提醒和过期事件清理当前始终注册。调度参数来自传入配置的 `clock_config` 及任务自身的默认值。

`WorldClock.register_daily_action(name, hour, minute, action)` 使用服务器本地时间，每天在下一次指定时刻运行；恰好到达指定时刻时安排到次日。`register_interval_action(name, interval_seconds, action, run_immediately=False)` 默认先等待一个周期；立即运行开启时先执行一次。周期等待从上一次执行结束后开始。

同一调度类别中同名注册替换旧循环；`start()` 重复调用不重复启动。action 可同步或异步，普通执行异常被隔离，不停止其他任务或自身后续周期。`last_results` 保存每个名称最近一次成功结果。

`await stop()` 取消并等待所拥有的任务。超过 `stop_timeout_seconds` 仍有同步工作未停止时抛出 `RuntimeError`，保留任务供再次关闭；停止成功后可以再次调用。`is_running` 为假只表示停止调度，不保证同步工作已结束。`WorldRuntime.stop_background_services()` 传播时钟关闭失败。

`WorldRuntime.start_background_services()` 同时启动时钟和事件初始化；`ensure_holidays()` 属于启动初始化，不注册为时钟 action。

上述行为通过 `server/tests/world` 的公开入口回归测试验证，任务业务执行使用 Fake，不连接外部服务。

### 世界事实投递（21–25 迁移中）

迁移中的世界任务只投递规范化事实，不再直接写入知识、调用角色能力或写入角色内容：

- citywalk（`try_citywalk:{character_id}`）：概率抽样、地图/环境推进、报告生成、`travel` 事件与报告回写留在 world；散步成功后投递 `WorldObservation`，其 `observation_kind.value` 为 `citywalk_completed`、`fact.fact_id` 为 `citywalk:<报告路径>`、`fact.summary` 为报告叙述（缺叙述时由目的地/经过地点/时长拼出）、`world_revision` 取完成时刻。任务不再 import `CharacterRuntime`，也不再生成动态正文。
- 报告回写：动态身份与正文由结算回执（`FactPlanOutcome` 的 `DYNAMIC_POST` 效果与计划内 `PublishDynamic.body`）写回报告的 `dynamic_id`／`dynamic_content`／`diary_text`；发布失败只记录日志，不撤销散步事实与报告。
- 学歌（`learn_sing_songs:{character_id}`）：凭据检查与刷新、愿望清单状态、下载/清理/模型处理、工件校验、媒体库刷新、情绪标签、通知文件、`new_song` 事件与 `already learned` 去重留在 world；**只有工件验证通过**的新学会歌曲才逐首投递 `SongLearned`（`learning_job_id` 为本次学歌任务标识、`song_id` 为统一歌名、`completed_at` 带时区）。中间进度、失败与 `already learned` 一律不投递，任务结果改报 `submitted_count` 而不声称动态 ID。

- VCPedia 新歌任务（`sync_new_song_knowledge`）：抓取、字段规范化、来源检查与来源去重留在 world；每个候选产出 `SongKnowledgeDiscovered`（`source_ref=vcpedia`、外部歌曲标识、由规范化内容派生的修订号、供应商无关的歌曲资料 `SongKnowledgeCandidate`），经该角色长期 `WorldStage` 的 `fact_sink.submit(...)` 投递。任务不再写入歌曲知识或关键词索引。
- 结果统计为 `discovered_count`／`submitted_count`／`rejected_count`／`skipped_existing_count`／`fetch_failed_count`，不报告 `added`（知识是否写入由 Agent 侧接纳决定）。
- `WorldStage` 不可用或事实被拒时记录候选并在返回中计入 `rejected_count`，不降级为直接写入知识、不重试。

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
