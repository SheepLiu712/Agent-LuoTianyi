# 通话重构 CR-4 实施证据

> 基线：CR-3 checkpoint `28a4f048b92d5267b2b8f1bee9d85e2ced37eb4b`
>
> 状态：隔离分支候选实现，等待 Oracle Gate B2 与结构扫描；不代表人类验收、合入或发布

## 状态所有权

- `EphemeralCallConversationStore`：只读 `base_snapshot` 保存 e1/e2 历史背景；独立 working snapshot 保存本次 c1/c2、工作摘要与压缩结果。
- `ConversationContext`：持有本交互 call maintenance progress；压缩 covered 与 maintained progress 独立推进。
- `CallMaintenanceSkill`：删除 `_pending/_progress/_locks/_local_batches` 及 `release(call_id)`；每次调用仅使用不可变输入和持久 batch，多个 interaction 不共享交互状态。
- 持久 batch：继续负责冻结模型产出、部分写入重试和幂等；Context progress 仅在候选写入、画像应用和 batch 完成后推进。

## 正常收尾顺序

```text
CallStage 停止实时任务与 provider
  → 保留并移交原 InteractionContext
  → final maintenance（失败按既有降级/重试）
  → summary（读取维护后同 Context working summary/内容）
  → Conversation/ledger settlement
  → owned writes 实际退出
  → close 原 Context
  → 解除 FINALIZING/lease
```

接通前无 Context 与进程恢复缺失 Context 的路径仍按现有账本恢复；不重建转写或临时 working summary。

## 已覆盖行为

- seed e1/e2 可供回答，但不进入 working entries、维护输入或最终工作摘要；c1/c2 才进入维护。
- threshold compaction 只操作 working snapshot；维护失败不推进 Context progress且不压缩原文。
- 新建无状态 Skill 实例可从持久 frozen batch 恢复，部分写入不重新冻结候选。
- 同一 Skill 服务多个 interaction 时无按 call_id 字典、锁或本地 batch 泄漏。
- 正常 Stage 实时清理后 `stage.context is None`，Context 所有权已转给 Manager finalization；settlement 完成/失败后由 consumer 关闭。
- 最终维护严格早于 summary；summary handler可直接读取维护后同 Context 的 working summary。
- 删除 AgentRuntime/Settlement 外层维护缓存释放端口。

## 验证与边界

当前已运行子集：

```powershell
& .\.venv\Scripts\python.exe -m pytest server/tests/integration/agent/test_call_threshold_maintenance.py -q --tb=short
# 6 passed

& .\.venv\Scripts\python.exe -m pytest server/tests/integration/agent/test_call_threshold_maintenance.py server/tests/integration/stage/test_call_settlement_execution.py server/tests/integration/stage/test_call_settlement_consumer.py -q --tb=short
# 17 passed

& .\.venv\Scripts\python.exe -m pytest server/tests/integration/stage/test_call_stage.py server/tests/integration/stage/test_call_stage_binding.py server/tests/integration/stage/test_call_coherent_runtime.py server/tests/integration/persistence/test_call_maintenance_batches.py server/tests/unit/agent/test_call_settlement_skills.py server/tests/unit/agent/test_call_maintenance_owned_writes.py -q --tb=short
# 49 passed
```

最终合并测试、静态检查与真实 JS 结束→历史/聊天回环结果待完成后更新，不累加重叠子集。未实现 CR-5 持久化门面或进程中途失败深验证，未执行真实供应商、付费模型或 Android 真机。

最终 Python 影响范围合并复跑：

```powershell
& .\.venv\Scripts\python.exe -m pytest server/tests/integration/agent/test_call_threshold_maintenance.py server/tests/integration/stage/test_call_settlement_execution.py server/tests/integration/stage/test_call_settlement_consumer.py server/tests/integration/stage/test_call_stage.py server/tests/integration/stage/test_call_stage_binding.py server/tests/integration/stage/test_call_coherent_runtime.py server/tests/integration/stage/test_stage_finalization.py server/tests/integration/persistence/test_call_maintenance_batches.py server/tests/unit/agent/test_call_settlement_skills.py server/tests/unit/agent/test_call_maintenance_owned_writes.py -q --tb=short
# 83 passed, 0 skipped in 16.97s
```

真实 JS 网络回环使用显式 lane source/python 执行，但一次命令达到工具外层 180 秒超时且未留下 node/python 进程，未取得可计为通过的输出；未无界重试。此前 CR3 的 2 passed 不能冒充本轮正常收尾变更证据，因此网络范围当前保持未验证。

## Gate B2 attempt 1 remediation

- N1 原红灯：非空 working summary 时 `CallSummarySkill` 直接返回 prefix，既忽略未压缩 tail，也没有把最终概要写回同 Context。
- 修复后 summary 输入由维护后的 working prefix 与全部未压缩 working entries 组成；base seed 不进入模型。模型成功且通过非空/200 字安全校验后，`update_call_working_summary` 只替换 working summary，保留全部 tail entries；返回值与后续 `CallContent.summary` 使用同一更新后概要。模型失败继续使用既有 `FAILED_CALL_SUMMARY` 降级。
- 新增直接测试断言输入包含 `maintained call prefix + uncompressed call tail`、不含 `old seed`，Context identity 未更换，summary 更新且 c2 tail 仍保留。
- N2 文档修复：AC-15 明确阈值维护只推进 Context progress，不推进 ledger；正常最终 settlement 成功后才把最终 progress 写入 ledger `maintenance_turn_seq`，保留其恢复与幂等语义。
- Context 关闭所有者收口：Consumer 不再关闭传入 Context；Manager finalization 是移交后唯一 primary close owner。AgentSettlement 仅在 `context=None` 的崩溃恢复 fallback 自建并关闭 Context。Stage admission 移交失败仍关闭自己尚未交付的 Context。
- Manager finally 在 settlement 成功、失败或取消后执行 mandatory close，再释放 ownership/FINALIZING；close failure 在无 settlement error 时传播，有原 settlement error 时仅记录异常类型，不覆盖原错误。
- partial-turn 边界继续按 whole/partial 集合处理：仅 user+agent 都在 covered 且位于首个 partial turn 前的完整轮次推进 progress；partial turn 的两半及后续原文留在 working entries，由 final maintenance 完整处理。

当前 remediation 后 Python 合并范围为上述 `83 passed, 0 skipped`；子集不与其累加。等待 Gate B2 attempt 2 与结构复核，不宣称 Gate PASS。

修复后使用当前源码、显式 lane source 与 `.venv` Python 复跑正式 JS 网络：

```powershell
$env:CALL_E2E_SERVER_SOURCE='C:\Agent-LuoTianyi\.slim\worktrees\call-refactor-cr'
$env:CALL_E2E_PYTHON='C:\Agent-LuoTianyi\.slim\worktrees\call-refactor-cr\.venv\Scripts\python.exe'
npx jest __tests__/call_real_network.test.ts --runInBand --detectOpenHandles
# 1 suite / 2 tests passed, 0 skipped in 100.23s
```

外层 shell 预算为 300 秒；未修改 Jest 90 秒、server stop 12 秒、恢复 3 秒或 reset 70 秒内部约束。Gate 前既有一次 1failed/1passed 与一次诊断 2passed/0skip 的 wall-clock 波动证据继续保留，不用本次绿色隐藏历史失败。

## Gate B2 attempt 2 remediation

- N3 原红灯：compaction 模型和实际删除仍使用配置前缀，若前缀包含 turn2 user 但不含 turn2 agent，progress 虽只推进 turn1，turn2 user 原文仍被删除。
- 修复将 compaction 拆为“计划前缀”与“安全提交前缀”：先计算首个 partial turn，只把其之前完整 whole turns 送入 summary model并提交删除。因此模型摘要范围、实际 covered IDs 和被删除原文完全一致；partial turn 两半及后续 tail 全部保留。
- 新增 `test_partial_turn_compaction_keeps_both_halves_and_finally_maintains_tail`：turn1 user+agent 完整 covered、turn2 仅 user 落在计划范围、turn3 未 covered；断言 progress=1、summary 输入只含 turn1、working entries 保留 turn2 user+agent 与 turn3 user+agent，final maintenance 随后完整处理2/3。
- N4 原红灯：finalization task/caller cancellation 可在 Context close owned work尚未结束时进入 ownership release。
- Manager 现在通过 `complete_owned(context.close())` 排空 mandatory close；一次或重复 cancellation 仅在 close 实际完成后传播。ownership、FINALIZING、call control清理均在 mandatory close 之后。
- 新增 `test_cancelled_finalization_waiter_keeps_context_close_and_admission_owned` 参数化一次/重复取消：真实 InteractionContext close 被线程门阻塞期间 finalization不完成、Context未关闭、reset仍返回busy；释放后 caller观察CancelledError、Context真实关闭清空，然后准入恢复。
- settlement/close错误优先级保持：仅close失败则传播close；settlement与close都失败时保留settlement错误并best-effort记录类型，logger普通异常不越过mandatory close。

修复后最终合并范围：

```powershell
& .\.venv\Scripts\python.exe -m pytest server/tests/integration/agent/test_call_threshold_maintenance.py server/tests/integration/stage/test_call_settlement_execution.py server/tests/integration/stage/test_call_settlement_consumer.py server/tests/integration/stage/test_call_stage.py server/tests/integration/stage/test_call_stage_binding.py server/tests/integration/stage/test_call_coherent_runtime.py server/tests/integration/stage/test_stage_finalization.py server/tests/integration/persistence/test_call_maintenance_batches.py server/tests/unit/agent/test_call_settlement_skills.py server/tests/unit/agent/test_call_maintenance_owned_writes.py -q --tb=short
# 86 passed, 0 skipped in 46.20s
```

本轮不重复100秒网络；改动只涉及Context数据完整性与finalization mandatory close，已有当前CR4源码网络绿色仅支持未变wire正常路径，不作为N3/N4证明。等待Gate B2 attempt3，不宣称Gate PASS。

## Gate B2 attempt 3 独立真实组合证据补强

新增 `tests/integration/stage/test_call_finalization_real_graph.py::test_stage_handoff_uses_one_context_until_real_sqlite_settlement_finishes`，贯通以下正式组件：

```text
CallStage
  → CallFinalizationSink
  → StageManager._finalize_call
  → CallSettlement
  → CallSettlementConsumerImpl
  → CallAgentSettlement
  → SqlCallSessionRepository / file SQLite
  → ConversationService
  → StageManager mandatory InteractionContext.close
```

测试未替换 `CallSettlementConsumerImpl.settle`、未替换 Manager 内部 consumer，也未由 fake consumer 主动关闭 Context。仅包装真实维护、总结、ConversationService 写入和 Context close 以记录顺序，包装后均调用原实现；外部 LLM、实时语音、TTS 与 vector backend 使用确定性离线替身。`StageManager`、`CallStage`、Agent、ContextFactory、CallSettlement、Consumer、AgentSettlement、SQLite repository 与 ConversationService 均为正式实现。

组合断言包括：

- CALL `ContextFactory.create` 恰好一次，Stage、维护和总结收到同一个 Context；`interaction_id` 等于 `call_id`，没有结算期第二 Context
- 模型总结输入含维护后的 working prefix 与未压缩 tail，不含聊天 seed；SQLite `CallContent.summary` 与写入阻塞期间同 Context 的更新后 summary 一致
- 顺序为 `maintenance < summary < real SQLite write < real Context close < FINALIZING release`
- 真实 `ConversationService.add_call_conversation` 在线程 Event 处阻塞时，实际 SQLite 写尚未执行；原 Context 仍 open 且 `read_working()` 可读，Chat、Call 与 reset 均保持 busy
- 释放 Event 后执行真实 SQLite 写；Manager 调用真实 Context `close()` 恰好一次，关闭后读取抛错，Ephemeral store 的 working/base 内容清空，之后 Chat 与 reset 准入恢复
- 测试使用每次至少前进 1 微秒的 wall clock，避免同 timestamp CAS 伪红；Event 在 `finally` 释放，避免测试挂起或遗留进程

真实压缩组合证据更新 `test_partial_turn_compaction_keeps_both_halves_and_finally_maintains_tail`：使用正式 `ConversationCompactionSkill`、`CallMaintenanceSkill`、`ConversationContext` 与 `EphemeralCallConversationStore`，仅替换 LLM 端口。配置计划边界落在 turn2 user 后；实际模型只接收 turn1 user+agent，store 实际删除范围与 safe covered IDs 一致，turn2 两半与 turn3 全部保留，progress 只推进完整 turn1，final maintenance 再处理完整 tail。新增 `test_real_compaction_failure_keeps_progress_and_every_unmaintained_entry` 证明真实 compaction 模型失败时 progress 不推进、原 working entries 不删除、维护模型不被调用。

验证命令：

```powershell
& ..\.venv\Scripts\python.exe -m pytest `
  tests/integration/stage/test_call_finalization_real_graph.py `
  tests/integration/agent/test_call_threshold_maintenance.py -q --tb=short
# 9 passed in 9.01s

& ..\.venv\Scripts\python.exe -m pytest `
  tests/integration/stage/test_call_finalization_real_graph.py `
  tests/integration/agent/test_call_threshold_maintenance.py `
  tests/integration/stage/test_call_settlement_consumer.py `
  tests/integration/stage/test_call_settlement_execution.py `
  tests/integration/stage/test_stage_finalization.py -q --tb=short
# 38 passed, 0 skipped in 12.71s
```

测试文件静态门禁：`ruff check` 通过；Black 26.5.1 格式化后 `--check` 通过。`scripts/check_architecture_boundaries.py` 与上述路径的 `git diff --check` 均通过。

本节是独立测试交付证据，尚待 Oracle Gate B2 attempt 4；不宣称 Gate PASS、人类批准、合入或发布完成。未修改生产源码、产品时限或既有断言，也未重复长网络测试。

## Gate B2 attempt 4

- 独立复审结论：PASS，N1–N4 与结构/证据要求全部 Closed。
- 该结论是自动化独立门禁结果，不代表人类验收、ADR Accepted、合入或发布。
