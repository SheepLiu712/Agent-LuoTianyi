# handle 请求账本契约

状态：请求幂等与 [PlanEmitter](plan-emitter.md) 联动的可恢复 outbox 已实现。业务入口为 `Agent.handle_stimulus(request, plan_sink)`，输入和结果使用现有 domain 类型。

## 装配与持久化

`agent/ledgers/request_ledger.py` 拥有 Request Ledger；JSON 编码辅助代码位于同目录的私有模块。AgentRuntime 初始化时为角色门面注入 `database_manager.open_sql_session`，Agent 构造提供仅供装配使用的必填关键字参数 `sql_session_factory: Callable[[], Session]`。账本使用该工厂创建并关闭 SQLAlchemy Session，在原数据库中创建自己的表；初始化失败使运行时初始化失败，沿用已有回滚。

事务只覆盖本地登记、读取和结算，不能跨越 Handler 或 sink 的 await。唯一键为 `(character_id, request_id)`，数据库唯一约束保证不同 Agent、不同 Runtime 或不同进程争用时只有一个获得处理权。请求记录保存版本化 fingerprint、处理占用和完整报告；计划 outbox 保存恢复必需的完整计划及接收事实。原刺激正文、取消令牌、Handler、sink 或协程不持久化。字段使用显式 JSON 与标量编码，不使用 pickle。账本不从 Agent 包导出，也不提供 stage 查询入口。AgentRuntime 保持顶层位置和原兼容入口。

数据库操作通过同步 Session 执行，其间事件循环需要等待 SQL 返回；数据库锁等待时长由注入引擎的超时设置决定。Handler 与接收器调用期间不持有 SQL 事务。

## 请求身份

fingerprint 包含绑定角色以及请求的全部不可变语义：触发刺激的具体类型及全部字段；快照具体类型、全部字段、pending 的顺序及每条刺激的完整值。包括 schema_version、source、目标角色、user、ephemeral、正文与媒体引用、interaction revision、now、timezone、supported_outputs、deadline、连接或设备或世界状态。request_id 是唯一键；可变 CancellationToken 的对象身份、取消状态和原因均不参与 fingerprint。

编码必须确定且带版本。元组保留顺序，集合按稳定顺序编码；datetime 保留有时区的值，ZoneInfo 使用 key，枚举使用类型和值，具体 dataclass 类型必须区分。等价重建的领域对象具有相同 fingerprint，Python hash 或对象 repr 不能充当持久协议。

同角色相同 request_id 但 fingerprint 不同，返回 `FAILED / CONTRACT_SNAPSHOT_MISMATCH / retryable=False`：根据此次输入保留全部 pending，consumed 和 emitted_plan_ids 为空，不调用 Handler 或 sink，也不覆盖原账本。改变 interaction_id 同样属于冲突。不同角色可独立使用相同 request_id；不同 request_id 独立处理。

## 首次处理与重投

参数类型、目标角色和运行时接受状态检查先于账本；拒绝时不占用请求。之后进行 fingerprint 查找或原子登记，再检查首次调用的取消令牌与刺激路由。已存在终态时，即使此次传入新的已取消令牌，也返回原终态报告，不重新交付、不重新消费。运行时停止接受后仍按既有规则拒绝新调用，不能借重投绕过关闭。

获得处理权后，原有处理器路由、计划交付及报告校验继续适用。没有可恢复计划的正常返回、业务失败、协作取消、预取消和未支持刺激均保存完整终态；有待重投计划时保存可信 provisional report，按 [PlanEmitter](plan-emitter.md) 的恢复规则结算。必须在提交成功后才向调用方返回该报告；后续相同请求读取同一值，包括状态、逐 ID 消费、计划 ID 顺序、reconsider_at、错误码和 retryable。已终态报告的 retryable 不授权重新执行 Handler；可恢复报告的 retryable=True 仅授权重投持久计划。

同一 Agent 的并发相同请求等待同一次处理并获得相同报告；不同 fingerprint 立即冲突，不等待错误请求。等待者自己的 task 取消只取消等待，不能取消拥有处理权的调用或其他等待者，也不能更改其令牌。拥有处理权的调用 task 取消沿用门面清理后传播规则，不能让等待者接管并重新运行 Handler；未形成终态的等待者获得下述占用拒绝。

没有本地在途拥有者、且数据库仅有处理或恢复占用而没有可领取的恢复状态时，返回 `FAILED / DEPENDENCY_UNAVAILABLE / retryable=False`，不运行 Handler、不调用 sink、不删除或覆盖占用。此规则也适用于另一个 Agent/Runtime/进程争用同一未结算请求。占用者完成后，再次重投可读取其终态。进程重启不能凭时间或内存为空推断旧请求没有产生外部效果；缺少终态时的拒绝报告只表达无法安全继续，不证明历史上没有计划被接收。

所有已进入账本的调用，包括等待同一次结果的调用，都计入 AgentRuntime 的在途所有权。关闭期间已登记等待者可以取得既有结果；未完成前不得释放数据库依赖。关闭超时、调用方反复取消及重试保持原关闭契约。

## 存储失败与日志

登记或读取失败返回 `FAILED / DEPENDENCY_UNAVAILABLE / retryable=False`，不开始 Handler。结算写入失败时保留占用并返回同名依赖失败，保留本次已经确认的计划 ID，但不宣称原成功报告已持久化。重复请求不能绕过存储故障重新执行。损坏或未知版本记录按依赖不可用处理，不丢弃后重建。

通过 `utils/logger.py` 记录角色、请求、交互、稳定错误码及异常类型和无局部变量的栈位置，省略异常原文、刺激正文、完整 fingerprint 输入和数据库连接内容。

## 公开验收

测试从 `handle_stimulus` 和 `AgentRuntime.shutdown` 观察；使用临时 SQLite、真实 SQLAlchemy Session、真实路由及受控处理器和 sink，不断言表名、SQL语句或私有调用次数。

- 零计划与已接收计划的成功、部分消费、失败及取消报告在同实例和重建实例后保持相同值，sink 不重复交付。
- revision、触发锚点、pending 正文/顺序、interaction、时间及场景字段变化逐项冲突；新取消令牌不改变身份；集合构造顺序不改变身份。
- 同 Agent 并发重复只交付一次，取消等待者不影响拥有者；冲突请求不阻塞；不同请求可以同时处理。
- 两个独立 Agent/Runtime 共用数据库，同一未完成请求至多一方交付；完成后另一方读取终态；角色键独立。
- task 取消留下未结算占用时，重建实例拒绝接管；存储不可用、损坏或提交失败均不静默回退。
- 重复等待中的关闭超时保留依赖，原处理完成后等待者正常结算，关闭重试成功；原兼容查找和两个业务方法不变。
