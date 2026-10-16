# 通话重构 CR-3 实施证据

> 基线：CR-2 checkpoint `8a424fd86f33f8a201c05f68fa346febaff19ae6`
>
> 状态：隔离分支候选实现，等待 Oracle Gate B1 与结构扫描；不代表人类验收、合入或发布

## 公开模块责任图

- `AgentRuntime.call_tts_character_ids/call_summary_character_ids`：分别按角色汇总 Agent 自有的通话 TTS（含预制致歉）和概要能力，组合根不读取 `skills` 对象树。
- `StageManager.initialize()`：构造后执行旧账本恢复；恢复成功前 `call_recovery_ready=False`，`open_call` 失败关闭。重复调用及并发等待共享同一个 owned 初始化任务，外部等待者取消不取消恢复。
- `StageManager.call_settlement_ready/call_recovery_ready`：公开业务模块实际就绪事实；恢复报告的失败或冲突由 Manager 解释为初始化失败。
- `CallWebSocketAdapter.capability_status`：合并配置开关、单进程宿主、供应商、Agent 角色能力、Manager 结算/恢复和 Adapter 生命周期；`supports_call_character` 与 `open` 使用相同事实。
- `ServerRuntime`：仅注入明确依赖并调用 `StageManager.initialize()`；不构造 Hub/Binding/Session，不构造恢复服务，不解释恢复 report，不遍历 Skill。

## Issue #320 验收映射

1. **恢复前不能接入**：阻塞 recovery 时 `StageManager.open_call` 返回 `CALL_INGRESS_UNAVAILABLE`；恢复完成后 ready 才置真。
2. **失败与冲突保持初始化失败**：Manager 将 recovery report 的 `failed/conflicted` 转为 `RuntimeError`，ServerRuntime 既有初始化回滚负责依赖排空；未改为仅禁用通话。
3. **开关关闭仍执行恢复**：ServerRuntime 无条件调用 Manager initialize；开关只参与 Adapter capability，不跳过持久账本收敛。
4. **能力查询与接入同源**：HTTP 投影读取 Runtime 的 Adapter capability，正式 call endpoint 和 Adapter open 同样检查 Adapter capability；角色判断由 TTS 与概要公开角色集合的交集驱动。
5. **关闭与回滚顺序**：沿用 CR-1/CR-2 的 Manager/Adapter 排空后再关闭 Agent/数据库；未新增准入锁、收尾表或 CallRuntime locator。
6. **架构边界**：结构测试禁止 `server_runtime.py` 出现 `agent_runtime.skills`、`CallTransportHub`、`CallStageBinding`、`StaleCallRecoveryService` 或直接 `reconcile`。

## 验证

```powershell
& .\.venv\Scripts\python.exe -m pytest server/tests/unit/test_call_transport_capability.py server/tests/unit/web/test_call_capability.py server/tests/integration/runtime/test_runtime_initialization_rollback.py server/tests/integration/runtime/test_runtime_shutdown.py -q --tb=short
# 38 passed, 2 warnings in 4.47s

& .\.venv\Scripts\python.exe -m pytest server/tests/integration/stage/test_stale_call_recovery.py server/tests/integration/websocket/test_call_websocket_adapter.py server/tests/integration/stage/test_call_stage.py server/tests/integration/stage/test_call_stage_binding.py server/tests/integration/application/test_user_data_reset.py -q --tb=short
# 69 passed, 2 warnings in 15.65s
```

静态范围使用 Ruff 0.14.10、Black 26.5.1、`check_architecture_boundaries.py` 与 `git diff --check`。以上两条命令分别报告，不累加为单一测试总数。

最终将上述 Python 影响范围合并复跑，避免把重叠子集相加：

```powershell
& .\.venv\Scripts\python.exe -m pytest server/tests/unit/test_call_transport_capability.py server/tests/unit/web/test_call_capability.py server/tests/integration/runtime/test_runtime_initialization_rollback.py server/tests/integration/runtime/test_runtime_shutdown.py server/tests/integration/stage/test_stale_call_recovery.py server/tests/integration/websocket/test_call_websocket_adapter.py server/tests/integration/stage/test_call_stage.py server/tests/integration/stage/test_call_stage_binding.py server/tests/integration/application/test_user_data_reset.py -q --tb=short
# 113 passed, 2 warnings in 19.01s
```

正式启动与能力改动影响网络 harness，因此使用显式 lane 源码与 Python 运行最小真实 JS↔FastAPI 回环：

```powershell
$env:CALL_E2E_SERVER_SOURCE='C:\Agent-LuoTianyi\.slim\worktrees\call-refactor-cr'
$env:CALL_E2E_PYTHON='C:\Agent-LuoTianyi\.slim\worktrees\call-refactor-cr\.venv\Scripts\python.exe'
npx jest __tests__/call_real_network.test.ts --runInBand --detectOpenHandles
# 1 suite / 2 tests passed, 0 skipped in 95.365s
```

首次网络运行暴露旧 test-support 仍向 `ServerRuntime` 传入已删除的 `call_transport_hub/call_capability` 内部装配字段，服务以 `TypeError` 退出；修复 harness 改为构造正式 `CallWebSocketAdapter` 并通过其公开 capability 后复跑通过。该失败是 CR-3 公开模块边界迁移遗漏，不是外部环境或供应商故障。

## Gate B1 attempt 1 remediation

- 原红灯确认：恢复内部 `to_thread` 阻塞时，旧 `StageManager.close()` 会先返回；Runtime rollback 随后关闭 Agent/数据库，而恢复线程仍运行，晚到成功还会把已关闭 Manager 的 `call_recovery_ready` 置为真。
- Manager 继续持有唯一 `_initialization` owner：`close()` 先设置 `_closed=True` 与 ready=false 围栏，再等待该任务及其 owned thread 实际收敛；不在 Manager 锁内等待数据库恢复。初始化成功提交 ready 前再次检查 closed，关闭竞态下原 initialize waiter得到 `stage manager closed during initialization`。
- 初始化任务增加完成观察，close 使用 `gather(..., return_exceptions=True)`，恢复异常不会跳过其余 Stage/收尾清理，也不会产生未观察 Task exception；原 initialize waiter仍观察 recovery exception。
- 新增 production-shaped blocking `to_thread` 测试证明 close 在真实线程释放前不完成；Runtime rollback 使用真实 StageManager，证明 Agent/数据库 shutdown 晚于 recovery thread 退出。重复或取消 initialize waiter不取消 owner，close 接管并排空。
- recovery report 的 `failed` 与 `conflicted` 分支分别参数化；两者都保持 ready=false并使初始化失败。
- Adapter 默认构造改为 fail-closed：`enabled=False`、无角色能力集合时 capability/接入均不可用。协议测试显式启用 legacy test capability，正式 Runtime 仍显式传入默认关闭的产品配置。
- 角色能力负向恢复：TTS、预制致歉、概要分别由 AgentRuntime 公开集合决定，Adapter 使用两类集合交集，任一缺失时能力查询与实际接入共同失败关闭。

新增竞态与默认能力测试先在旧实现观察到 3 个红灯：默认 capability 意外 available、close 后 initialize 不报 closed、late recovery 将 ready 置真。修复后聚焦测试 `49 passed`，最终受影响 Python 合并范围为上述 `113 passed, 0 skipped`。

真实 JS 网络命令首次执行达到工具 120 秒外层超时，进程已退出且未留下 node/python；按同一 source/python 和未变测试预算重跑一次得到上面的 2 passed/0 skipped。此处不把第一次工具超时记作绿色，也未修改测试内部时限。

## Gate B1 attempt 2 remediation

- 原红灯确认：`ServerRuntime._rollback_failed_initialization` 在 rollback waiter 被取消时，把 `CancelledError` 当作普通 step failure 记录后继续下一步；Manager 的 shielded close 仍等待真实 recovery thread，但 Agent/数据库已经被提前关闭。
- 完整初始化 rollback 现在由单一 `server-runtime-initialization-rollback` owned task 执行。外部 waiter 一次或重复取消只记录取消请求并继续等待 owned rollback 完成；所有资源步骤完成后向原 caller 传播 `CancelledError`，不把取消吞成成功。
- 内部普通 step failure 继续聚合并执行后续清理；日志只记录步骤名和异常类型，不包含异常消息或业务内容。内部 owned rollback 的意外 cancellation 仍传播，不被当作普通错误吞掉。
- `ServerRuntime.initialize` 的异常路径通过既有 `complete_owned` 等待 rollback，保证原初始化异常仅在完整清理后重新抛出；未改变正式 `shutdown()` 的取消语义。
- 新增 production-shaped 测试使用真实 StageManager 与阻塞 `asyncio.to_thread` recovery：rollback waiter 一次/重复取消后，线程释放前 rollback 不完成且 Agent/数据库未关闭；释放后顺序为 `recovery_stopped < agent < database`，caller 最终观察 `CancelledError`，原 initialize waiter观察 closed/recovery 原异常，无未观察 task warning。
- recovery 自身异常与后续 world stop 普通异常叠加 cancellation 时，rollback 仍关闭 Agent/数据库；日志不泄漏两条注入的异常消息。

红灯阶段三项测试均失败：rollback 在 thread 释放前已完成、依赖已提前关闭或 cancellation 被吞成成功。修复后：

```powershell
& .\.venv\Scripts\python.exe -m pytest server/tests/integration/runtime/test_runtime_initialization_rollback.py -k "cancelled_runtime_rollback" -q --tb=short
# 3 passed, 5 deselected, 1 warning in 3.78s

& .\.venv\Scripts\python.exe -m pytest server/tests/integration/runtime/test_runtime_initialization_rollback.py server/tests/integration/runtime/test_runtime_shutdown.py server/tests/unit/test_call_transport_capability.py server/tests/unit/web/test_call_capability.py server/tests/integration/stage/test_stale_call_recovery.py -q --tb=short
# 54 passed, 0 skipped, 2 warnings in 7.59s
```

本轮仅修改初始化 rollback 取消边界及其真实 Manager/thread 测试；未重复 95 秒 JS 网络或 63.9 秒进程重启测试，因为能力、正式 endpoint 和恢复算法未改变。等待 Gate B1 attempt 3，不宣称 Gate PASS。

## Gate B1 attempt 3

- 独立复审结论：PASS，初始化恢复、关闭排空、rollback 取消边界、能力同源及组合根边界全部 Closed。
- 该结论是自动化独立门禁结果，不代表人类验收、ADR Accepted、合入或发布。

## 边界与未验证范围

- 未迁移 CR-4 的 Context 最终维护顺序，未实现 CR-5 持久化门面，未清理 CR-6 兼容入口。
- 启动恢复继续使用既有真实 SQLite 集成测试；本工单不宣称进程重启后的深层跨存储故障已完成 CR-5 验收。
- 默认通话开关、call.v1 wire、错误帧及产品行为未改变。
- 尚未运行真实供应商、付费模型或 Android 真机。
