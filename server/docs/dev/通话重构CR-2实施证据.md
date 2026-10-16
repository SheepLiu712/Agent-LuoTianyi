# 通话重构 CR-2 实施证据

> 基线：CR-1 checkpoint `b1e9672f6b237db2f97fdbbce05184d06dd6013d`
>
> 状态：隔离分支候选实现，等待 Oracle Gate A2；不代表人类批准、合入或发布

## 接口与所有权

- `StageManager.open_call(CallOpenRequest, CallOpenTransport) -> CallControl`
- `CallControl` 只暴露 identity、disconnect、resume、terminate 与完成等待，不暴露 claim、generation、Task、provider 或账本
- `CallWebSocketAdapter.open/receive_text/receive_binary/next_output/disconnect/close` 封装 Hub、Session、Binding、Queue 及有限终止排空
- `call_ws` 仅做认证、物理帧接收/发送和稳定错误关闭

首接入顺序：Manager 建立 PREPARING identity → Adapter 注册 Session/Binding → 队列写入 PREPARING → `receive_start` 写入 ACK(seq=1) → 放行 Stage 后续输出 → 后台创建 Context/provider/请求接听。

## 验证

### N4 + N6 bounded remediation（2026-10-14 +08:00）

- Adapter 把每次 `open()` 的内部操作列为自身 owned task；调用方取消仅取消等待，Adapter/Manager 仍等待该操作并在 `prepare` 后、`receive_start`/ACK 前执行 unregister、pending claim fail、lease release 与 FAILED ledger 收敛。`close()` 先标记这些 operation 取消并排空，之后才关闭 Hub，避免晚到注册。
- Manager 的 request open task 完成后从 in-flight 索引删除，但接受中的 control 仍按 request 保存；终态或失败 ledger 可从 repository 重新定位，重复 start 返回原 `call_id` 的稳定 `CALL_START_FAILED`，不创建新 ledger。跨身份 request 查找仍只归一化成 `CALL_START_REJECTED`，不泄露 call identity。
- 初始 ACK 成功前不启动 Stage establishment；ACK 后才 `release()` control，因此取消不会遗留 bound Session 或被释放的 business gate。
- N6：`find_call_by_request`、source 推断与 existing attach 都在完整 start 归一化边界内，正式 endpoint 可得到既有 `request_id`、`request_seq`、`retryable` 与 close code 字段。

先新增/运行的公开 Adapter 组合测试当前观察到红灯：取消后 Hub Session 仍残留；并发同 request 的第二请求出现 `CALL_BINDING_UNAVAILABLE`。修复后以下聚焦范围为绿：

```powershell
& .\.venv\Scripts\python.exe -m pytest server/tests/integration/websocket/test_call_websocket_adapter.py server/tests/integration/stage/test_call_stage.py server/tests/integration/stage/test_call_stage_binding.py -q --tb=short
# 48 passed in 7.94s

ruff check server/src/adapter/websocket/call_v1/adapter.py server/src/stage/stage_manager.py server/tests/integration/websocket/test_call_websocket_adapter.py
# All checks passed

& .\.venv\Scripts\python.exe -m black --check server/src/adapter/websocket/call_v1/adapter.py server/src/stage/stage_manager.py server/tests/integration/websocket/test_call_websocket_adapter.py
# 3 files would be left unchanged

git diff --check
# passed; only pre-existing CRLF conversion warnings
```

新增公开场景：prepare 后取消无 Hub/claim/lease/task 孤儿且同 request retry 稳定原身份；同 request 并发只注册一个 transport、另一连接稳定拒绝；跨身份 request 错误含正式帧字段且不带 call id；Adapter close 在被阻塞的 prepare 注册完成补偿前不返回。Stage/Adapter 现有 handshake、初始化取消、接通前断线和 resume 相关测试同次运行。

未关闭：N3（resume 提交后失败的不可逆业务恢复、buffer overflow/payload 重放）仍严格留给后续唯一 writer；本次未修改 resume 事务，也未运行真网/供应商/全套回归。N4 的 SQLite repository 覆盖沿用已有 `InMemoryCallSessionRepository` 组合入口，SQLite 故障注入不在本次 bounded scope。

Gate A2 attempt 1 remediation 后，Python 聚焦协议与业务边界：

```text
293 passed, 14 skipped, 2 warnings in 19.16s
```

14 个 skip 逐项分类：角色不可用与 FINALIZING 正式 endpoint 行为已恢复；旧 `cleanup_failed_start`、`handshake_ownership`、`release_terminal_session` 等私有函数断言不再对应生产符号；混合帧、seq 冲突、连接抢占、resume 重放和 NACK 仍由公开 Adapter 测试及 Session/Hub/Binding 测试覆盖。skip 本身不计作通过，彻底删除过渡测试留给 CR-6。

真实 JavaScript ↔ FastAPI 回环：

```powershell
$env:CALL_E2E_SERVER_SOURCE='C:\Agent-LuoTianyi\.slim\worktrees\call-refactor-cr'
$env:CALL_E2E_PYTHON='C:\Agent-LuoTianyi\.slim\worktrees\call-refactor-cr\.venv\Scripts\python.exe'
npx jest __tests__/call_real_network.test.ts --runInBand --detectOpenHandles
```

Gate remediation 后运行三条具名真实网络路径：

```text
call_failure_close_network.test.ts
call_resume_race_diagnostic.test.ts
call_real_network.test.ts
```

N3 最终工作包与 test-support 地址文件原子发布后结果：`3 suites / 4 tests passed`、`0 skipped`，121.099 秒；`call_resume_race_diagnostic` 恢复低于三秒，服务在既有 12 秒 stop 预算内以 exit code 0 退出。Native 音频、模型、TTS 和实时语音供应商仍为离线替身。

### N3 确定性组合测试

- `test_stage_none_resume_precheck_is_read_only`：Stage 未创建时预检不写 `_connected`
- `test_concurrent_resume_reservation_has_one_winner_without_cursor_side_effect`：reservation token 排他，败者不推进 cursor
- `test_failed_business_resume_keeps_cursor_and_allows_later_resume`：业务预检失败后原 cursor/replay 保留，下一次合法恢复成功
- `test_resume_buffers_stage_output_without_blocking_and_flushes_after_resumed`：Stage 发布不会等待 Adapter gate，`call.resumed` 先于新业务输出
- `test_pending_resume_buffer_overflow_aborts_before_business_commit`：256 帧上限在 business commit 前失败，状态/cursor/pending buffer 不变
- `call_resume_race_diagnostic.test.ts`：真实取消/重连/服务关闭链路无死锁，resume 与 stop 都在原预算内完成

### N3 post-business 单向故障收敛（2026-10-14 +08:00）

- Adapter 在 Hub binding 已提交、调用 `StageManager.commit_call_resume` 前标记 `business_started`；该调用可能先把真实 Stage 从 RECONNECTING 推进到 ACTIVE 再在输出路径抛错，因此边界不能以 await 是否正常返回判断。
- business 开始后的 cursor、replay enqueue、pending flush、buffer overflow 或外部等待者取消，不再伪回滚为可恢复的 ACTIVE 无绑定状态。Adapter 先丢弃隔离中的 pending 输出，再通过 Manager-owned `CallControl.terminate(SYSTEM_FAILURE)` 完成实时停止、SQLite 终态和收尾接管，最后有界注销 Hub Session；补偿失败仅记录清理种类及异常类型，原始恢复错误保持不变。
- business 开始前的预检失败仍只释放 resume reservation，cursor/replay 不变；正常路径顺序仍为业务恢复提交 → cursor 提交 → `call.resumed`/replay 入队 → 新业务输出 flush。

真实 Stage + file SQLite 组合覆盖：

- cursor commit fault：故障前已真实 ACTIVE；最终 Stage/ledger 均为 ENDED + SYSTEM_FAILURE，provider 已关闭、Context 已释放、lease/ownership/Hub Session 收敛，request identity 唯一。
- replay enqueue 与 pending flush fault（参数化）：均在 business 恢复后注入，使用相同终态和资源收敛断言。
- 真实 Stage 恢复发布期间 buffer overflow：将 pending frame 上限降为 0，由 `commit_call_resume` 实际发布 ACTIVE 触发，不在 business 前人工填充；即使业务 await 抛出背压，仍完成终态收敛。
- 外部 `open()` waiter 在 business 开始后取消：owned resume/termination 不被等待者取消，不遗留 Adapter open task、Hub Session、lease 或 ownership。

当前源码聚焦验证：

```powershell
& .\.venv\Scripts\python.exe -m pytest server/tests/integration/websocket/test_call_websocket_adapter.py server/tests/integration/websocket/test_call_websocket_transport.py server/tests/integration/stage/test_call_stage.py server/tests/integration/stage/test_call_stage_binding.py -q --tb=short
# 59 passed, 14 skipped, 2 warnings in 15.12s

$env:CALL_E2E_SERVER_SOURCE='C:\Agent-LuoTianyi\.slim\worktrees\call-refactor-cr'
$env:CALL_E2E_PYTHON='C:\Agent-LuoTianyi\.slim\worktrees\call-refactor-cr\.venv\Scripts\python.exe'
npx jest __tests__/call_resume_race_diagnostic.test.ts --runInBand --detectOpenHandles
# 1 suite / 1 test passed, 0 skipped; resume 76.8 ms; server stop exit code 0 under unchanged 12 s budget
```

本节是实施者红绿与回归证据，不宣称 Gate A2 PASS；后续由独立 Oracle attempt 6 复核。冻结 wall clock 造成 ENDING/ENDED `updated_at` 同值 CAS 拒绝已作为另项观察风险记录，本工作包测试使用每次至少递增 1 微秒的 clock，未降低 repository CAS 约束。

### Attempt 6 日志观测补强（2026-10-14 +08:00）

- 独立 Gate A2 attempt 6 已确认 N3 真实 Stage/file SQLite 一致性场景 Closed；仅发现二次取消与 termination 自身失败重叠时，外层 `complete_owned` 的 `CancelledError` 会被误记为 cleanup 类型，掩盖 termination 的真实 `RuntimeError`。
- `_abort_started_resume` 现以局部 owned wrapper 捕获 termination 自身的 `BaseException`；wrapper 仍由既有 `complete_owned` 排空。排空后收到的外层 `CancelledError` 不再冒充 termination 失败，真实 cleanup 类型只记录一次。
- 未改变全局取消语义：原 resume 异常继续由 `_commit_resume` 向调用者传播；termination 实际执行至完成；pending output 清理和 Hub unregister 继续执行；日志仅包含 original/cleanup 异常类型，不包含异常消息或业务内容。

红灯：新增确定性测试在旧实现下观察到 `cleanup_type=CancelledError`，未记录真实 termination `RuntimeError`。修复后最小范围结果：

```powershell
& .\.venv\Scripts\python.exe -m pytest server/tests/integration/websocket/test_call_websocket_adapter.py::test_second_cancel_preserves_resume_error_and_logs_owned_termination_failure -q --tb=short
# 1 passed in 1.25s

& .\.venv\Scripts\python.exe -m pytest server/tests/integration/websocket/test_call_websocket_adapter.py -k "failed_business_resume_keeps_cursor or resume_buffers_stage_output or real_stage_resume_pending_overflow or resume_commit_failure_after_active or resume_post_business_output_failure or cancelled_resume_after_business_commit or second_cancel_preserves" -q --tb=short
# 8 passed, 10 deselected in 2.86s
```

该结果不与前述 59 项或 Oracle 7 项累加，也不宣称 Gate A2 PASS；等待独立 attempt 7 聚焦复审。

### Attempt 7 日志故障隔离（2026-10-14 +08:00）

- 独立 attempt 7 前置探针确认：termination 次级失败进入日志时，若 logger handler 或 `_log_resume_cleanup_failure` 自身抛出普通 `Exception`，旧控制流会跳过 Hub unregister，并用日志异常覆盖原 resume cursor fault。
- post-business 补偿现在以 `finally` 保证 Hub unregister 必经，不依赖 termination 或其诊断日志成功；termination 和 registry 次级失败仍只记录 original/cleanup 异常类型，不记录异常消息或业务内容。
- `_log_resume_cleanup_failure` 对日志系统普通 `Exception` best-effort；调用方同样防御被 monkeypatch 后抛出的普通日志异常。`KeyboardInterrupt`、`SystemExit` 等非 `Exception` 的进程级 `BaseException` 不被静默吞掉，但 unregister 仍先通过 `finally` 执行。
- 原 resume 异常继续保持；owned termination 与 second-cancel 行为未改变；不引入通用日志框架、重试或全局取消语义修改。

新增测试参数化覆盖真实失败 logger handler 与直接 monkeypatch helper 抛错。旧实现两项均红灯为 `logger failed` 覆盖 `original cursor fault`；修复后：

```powershell
& .\.venv\Scripts\python.exe -m pytest server/tests/integration/websocket/test_call_websocket_adapter.py::test_logger_failure_cannot_replace_resume_error_or_skip_unregister -q --tb=short
# 2 passed in 0.94s

& .\.venv\Scripts\python.exe -m pytest server/tests/integration/websocket/test_call_websocket_adapter.py -k "failed_business_resume_keeps_cursor or resume_buffers_stage_output or real_stage_resume_pending_overflow or resume_commit_failure_after_active or resume_post_business_output_failure or cancelled_resume_after_business_commit or second_cancel_preserves or logger_failure_cannot_replace" -q --tb=short
# 10 passed, 10 deselected in 3.09s
```

测试断言包括：原 cursor `RuntimeError` 保持、termination 实际完成、pending buffer 清空、Hub unregister 执行、Adapter open task 无残留；second-cancel 仍记录真实 termination `RuntimeError` 类型。未重复长网络或更大全量范围，等待独立 attempt 8 聚焦复审，不宣称 Gate A2 PASS。

### Gate A2 attempt 8

- 独立复审结论：PASS，N1–N6 全部 Closed。
- 独立证据：10 项聚焦测试、静态检查及进程级异常 finally/传播探针通过；确认日志故障不覆盖原 resume 异常，Hub unregister 必经，非 `Exception` 的进程级异常不被静默吞掉。
- 此结论是自动化独立门禁结果，不代表人类验收、ADR Accepted、合入或发布。

## Gate A2 attempt 1 remediation

- N1：`CallControl` 公开面仅保留不可变 identity 与 disconnect/resume/terminate/完成等待；连接句柄改为 opaque token，Binding/Session/Queue/Control 只存于 Adapter 私有 registry
- N2：Control 记录物理连接事实；Stage 在 RINGING 无连接时保存接听决定，不进入 ACTIVE/CallStarted，resume 后只应用一次
- N3：resume 拆为 preview 与 commit；preview 只验证 cursor/生成输出计划，不推进 ACK；Manager 业务恢复成功且 generation 仍 current 后才 commit cursor 并放行 resumed/replay
- N4：同 request 的 `open_call` 由 Manager-owned task 统一；外部等待者取消不能丢请求索引；prepare 失败调用正式 pending-claim failure 收敛 ledger/lease。Adapter 负责清理未交付 transport 半成品
- App reset 重试只接受预期 HTTP 409 `USER_INTERACTION_BUSY`；任意其他非成功状态立即失败，并断言首次确实经历 busy

### N5 根因与修复

- 根因是 resume commit 持 Stage lifecycle lock 发布 ACTIVE 时，Adapter `_deliver()` 等待仅由外层 resume finally 打开的 gate，形成循环等待
- 修复为 Adapter 私有有界 pending buffer：生产者只追加、不等待 gate；transport/business commit 后先入 `call.resumed`/replay，再 flush 新业务输出；失败丢弃该 reservation 的 pending 输出
- Hub reservation 增加排他 token；失败显式 release，两个 reservation 不能同时提交
- owned resume commit 使用 `complete_owned` 隔离外部等待者取消，并由 Adapter/Hub close 排空
- 临时 `[DEBUG-call-shutdown]` 任务栈诊断已从 test support 删除；修复后原始 loop 重新执行通过

## 限制

- ADR-0001 仍为 Proposed
- 旧分步 Manager/Hub API 为 CR-6 兼容路径，正式 `call_ws` 不再使用
- CR-3 的恢复初始化/能力收口、CR-4 Context 维护、CR-5 存储门面未提前实施
- 未执行真实供应商、付费模型、Android 真机或生产部署验证
