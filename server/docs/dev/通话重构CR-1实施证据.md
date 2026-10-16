# 通话重构 CR-1 实施证据

> 时间：2026-10-13（UTC+8）
>
> 基线：`650fa6359c5ffcd0d491160afd4c9fa340856d1b`
>
> 状态：实现与原始验证完成，等待独立 Oracle Gate A1；不代表人类验收、合入或发布

## 变更边界

- `StageManager` 通过既有 `FinalizationTasks` 同时持有一次通话的唯一终止任务与后续业务收尾任务
- `CallStage.terminate()` 首次调用固定原因，外部等待使用 `asyncio.shield`；重复调用复用同一任务
- 初始化成为 Stage 自有任务；初始化期间终止会取消并等待初始化，阻止 Context、供应商和普通 Agent 工作晚到
- 部分创建失败统一调用 `CallStage.abort_failed_start()`，Manager 不再读取 `_started` 或调用 `_cleanup()`
- `CallStateChanged` 携带协议转换所需的 `client_request_id` 与 `connected_at`，Binding 不再读取 Stage 私有账本或 ownership
- 未改变 wire 类型、错误码、close code、结算算法或 Context 选择

## 完成时点

```text
外部 terminate 等待者
  -> shield(Manager 唯一 termination task)
       -> 取消并排空初始化
       -> 停止 Agent/PCM/provider，确定终态
       -> 同一 FinalizationTasks 条目登记 settlement task
       -> 释放实时 ownership
  -> terminate 返回

Manager finalization task
  -> settlement / owned writes / finally 清理真实停止
  -> 释放 FINALIZING 准入限制
```

Adapter 的终止消息有限投递仍是独立传输事实，不作为业务收尾完成证据。

## 验证证据

基线专项范围：`38 passed, 2 warnings in 13.91s`。

最终受影响范围：

```powershell
..\.venv\Scripts\python.exe -m pytest `
  tests/integration/stage/test_stage_finalization.py `
  tests/integration/stage/test_call_stage_review.py `
  tests/integration/stage/test_call_failure_policy.py `
  tests/integration/stage/test_call_stage_binding.py `
  tests/integration/stage/test_call_stage.py `
  tests/integration/stage/test_call_handoff.py `
  tests/integration/runtime/test_runtime_initialization_rollback.py `
  tests/integration/application/test_user_data_reset.py `
  tests/unit/stage/test_call_lifecycle.py -vv --tb=short
```

结果：`111 passed, 2 warnings in 21.21s`；无 skip。警告为既有 `pkg_resources` 和 Starlette AnyIO alias 弃用警告。

专项新增事实：

- 首次终止等待者取消后，第二等待者仍等待同一底层任务；provider 只关闭一次，终态保持首次 `USER_HANGUP`
- Context 初始化阻塞期间终止后，不创建 Context、不创建供应商 Session、不注册运行中 Stage
- settlement 成功、失败、超时取消及 shutdown 期间均保持 `INTERACTION_FINALIZING` / `USER_INTERACTION_BUSY`
- Binding 只使用公开状态事件完成 RINGING/ACTIVE wire 转换
- 初始化回滚等待 StageManager 排空后才关闭 Agent 与数据库

静态门禁：

- Ruff 0.14.10：通过
- Black 26.5.1 changed paths：通过
- `scripts/check_architecture_boundaries.py`：PASS
- `git diff --check`：通过

## 未验证

- 未运行全仓测试
- 未运行真实供应商、付费模型、Android 真机或生产部署验证
- Adapter 门面迁移、组合根收口、Context/维护算法和存储门面属于 CR-2 至 CR-5，未在本次实施

## Gate A1 attempt 1 remediation

Oracle attempt 1 阻断后执行一次有界修复：

- N1：Stage 创建完成后的 reset generation 等待移到 Manager 主锁之外；主锁内只原子判断 `_closed` 与当前 ownership 并决定注册，锁外执行 `stage.close()`
- N2：`resume()` 和恢复期限任务不再在生命周期锁内直接调用 `_terminate_locked()`；锁内只固定超时判断，锁外进入同一 Manager-owned `terminate()` 操作。用户挂断先登记时，期限任务复用该任务且不能改写 reason
- E1：取消第二个重复等待者，首等待者继续；provider close、settlement admission 均恰好一次，终态 reason 保持首次值
- E2：settlement timeout 取消 consumer 时，consumer 正在 `complete_owned(asyncio.to_thread(...))`；线程释放前 Chat/Call admission、reset 与 `manager.close()` 均保持阻塞，线程实际退出后才解除占用
- E3：分别覆盖 Context 已创建后 provider create 阻塞、provider 已创建后 start 阻塞；终止等待取消清理，Context/provider 均实际关闭且不注册晚到 Stage

Remediation 聚焦命令：

```powershell
..\.venv\Scripts\python.exe -m pytest `
  tests/integration/stage/test_stage_finalization.py `
  tests/integration/stage/test_call_stage.py `
  tests/integration/stage/test_call_handoff.py `
  tests/integration/stage/test_call_settlement_execution.py -q --tb=short
```

结果：`79 passed in 15.87s`。

更新后的 CR-1 受影响范围加入 `test_call_settlement_execution.py`，最终结果：`122 passed, 2 warnings in 22.07s`，无 skip。线程证据是受控本地 `to_thread` 阻塞写，并非真实供应商、真机或进程崩溃恢复证据。
