# 通话重构 CR-6 实施证据

> 基线：CR-5 checkpoint `feb13a6935b7f817f5dc5ccc997e6779f12e55bb`
>
> 工单：#323
>
> 状态：隔离分支候选实现，未提交；等待 Gate C2 与结构扫描，不代表人类验收、合入、发布、Issue 关闭、Spec 非作者审批或 ADR Accepted

## Issue / AC claim owner

本阶段 owner 只承诺并验证以下 #323 范围：

以下是候选交付目标，不代表全部验收已闭合；未完成迁移与红灯见文末。

1. 正式 `chat_ws` / `call_ws` 经真实 FastAPI、`ServerRuntime`、`StageManager`、`CallWebSocketAdapter`、SQLite 完成 Chat ready → switch → PREPARING/ACK → ACTIVE → hangup → FINALIZING 拒绝 Chat/Call/reset → 收尾后恢复 Chat 与新 Call。
2. Web 不装配 claim、Stage、结算、Hub、Session 或 Binding；Runtime 不读取 Skill 树或解释恢复内部结构。
3. 删除无生产调用的 `stop_user_interactions`；claim、Stage 创建、失败 claim 与 ownership 释放变为 Manager 私有步骤；正式入口只使用完整门面。
4. `call_v1` 包根不再公开 Hub/Session/Binding/内部 receipt/config；协议单元测试从明确内部模块导入。
5. 旧 endpoint 私有 seam 的 13 个永久 skip 删除；两个仅存行为缺口迁移到公开 Adapter 测试，其余由现有 Adapter/Session/Binding 正式组合覆盖。

不宣称 #308 整单完成，也不实现 #324–335 专项需求。

## 唯一正式装配路径

```text
chat_ws
  → StageManager.connect
  → chat.ready
  → StageManager.prepare_call_transition

call_ws
  → CallWebSocketAdapter.open
  → StageManager.open_call
  → Manager 私有 claim / CallStage 创建 / ownership
  → Adapter 私有 Hub / Session / Binding
  → PREPARING → ACK → ACTIVE

hangup
  → CallControl.terminate
  → 实时资源停止与终态
  → Manager-owned finalization
  → maintenance → summary → SQLite → Context.close
  → FINALIZING/lease 释放
```

`server/src/web/websocket/call_endpoint.py` 只鉴权、物理收发、稳定错误帧和断线通知。结构测试禁止其出现内部装配符号。

## 过渡接口与引用结论

- 删除 `StageManager.stop_user_interactions`：`server/src` 无调用；旧测试仅用它清理手工 claim/ownership，现改为显式私有故障 seam 或正式 close。
- `take_call_claim`、`fail_pending_call_claim`、`create_call_stage`、`current_call_ownership`、`release_call` 改为私有；生产调用均在 Manager 内部，测试中的直接调用只保留状态机/故障注入价值。
- 删除 `current_call_stage`：无生产调用；测试改查私有 registry，明确属于内部断言。
- 既有 `release_call_maintenance` / `release_call_resources` 生产端口已不存在；删除测试 fake 残留与无效断言。
- `CallTransportHub`、`CallTransportSession`、`CallStageBinding`、`CallTransportBinding` 等从 `call_v1.__all__` 移除；内部协议测试从 `transport` / `stage_binding` 模块导入。
- 未删除 Context Store、call_sessions、maintenance batch 或 ledger CAS 接口：它们仍承担不同原子性与恢复契约，机械合层无收益。

## 旧 13 skip 迁移

原 `test_call_websocket_transport.py` 的 13 个旧 endpoint skip 已全部删除，skip 不计通过：

- `CALL_CHARACTER_UNAVAILABLE` 迁到 `test_unavailable_character_is_rejected_before_business_claim`，断言公开 Adapter 在账本/claim 前拒绝。
- Call FINALIZING 迁到 `test_call_start_during_finalization_returns_retryable_public_error`，断言公开错误身份和 retryable 字段。
- prepare/send failure、terminal release、resume reservation、handshake、late connection、seq/NACK/replay 已由 `test_call_websocket_adapter.py`、`test_call_v1_transport.py`、`test_call_stage_binding.py` 的公开门面或协议内部测试覆盖。
- 纯粹断言已删除的 `_cleanup_failed_start`、`_release_terminal_session`、`_handshake_ownership`、`_authenticate_and_attach` 实现细节不迁移为“通过”。

## #308 覆盖与剩余

已覆盖：`ContextFactory.create(..., mode=CALL)`、Store 私有化、call base/working 分离、原 Context 顺序收尾、无生产调用的维护资源 release 端口清理。

保留结论：`ConversationContext` 与私有 `_conversation_store.py` 不机械合层；聊天批次/原子维护 Store 仍内部化；本阶段未重新审计 #308 所有历史 AC，不能自动关闭 #308。

## B3 公开组合证据与旧 skip 映射

本节不把 Hub/Session 私有状态机断言冒充为公开链路覆盖。新增
`test_call_endpoint_failure_lifecycle.py` 以真实 `StageManager`、
`CallWebSocketAdapter`、SQLite 与正式 endpoint 的 `_serve_call` 收发泵执行；物理
WebSocket 仅是确定性替身。认证已在此测试外建立 call，因此此处验证的是认证之后的
生产收发、异常归一化与 finally 释放，而不是重复认证实现。

| CR-5 旧 skip / 行为 | 当前测试 | 层级 | 结论 |
| --- | --- | --- | --- |
| 角色不可用 | `test_unavailable_character_is_rejected_before_business_claim` | Adapter | 公开错误、request id、无业务 claim |
| FINALIZING retryable | `test_call_start_during_finalization_returns_retryable_public_error` | Adapter | `INTERACTION_FINALIZING` 与 retryable |
| prepare 注册前/后失败 | `test_cancelled_open_after_prepare_has_no_session_lease_or_request_task`、`test_adapter_close_waits_for_cancelled_open_compensation_before_closing_transport` | Adapter | 注册后取消、claim/lease/会话清理；注册前由 character rejection 覆盖 |
| physical send pump 失败 | `test_physical_send_failure_cancels_receive_disconnects_and_allows_resume` | endpoint + Adapter | send failure 关闭 1011、唤醒/取消 receive、旧 handle stale、同一 call_id 可恢复 |
| terminal release wait/timeout | `test_terminal_timeout_unregisters_only_expected_session_and_shutdown_leaves_no_tasks` | unit | 有界 timeout 与 expected-session unregister；尚无完整公开 endpoint 组合替身 |
| failed resume cursor/send | `test_resume_commit_failure_after_active_uses_sqlite_stage_termination`、`test_resume_post_business_output_failure_terminates_real_sqlite_stage` | Adapter + SQLite | cursor/enqueue/flush fault 终止并释放；失败后成功重试仅由 pre-business `test_failed_business_resume_keeps_cursor_and_allows_later_resume` 覆盖 |
| cancelled handshake / old generation | `test_cancelled_resume_after_business_commit_terminates_and_releases_owned_state`、`test_late_old_disconnect_cannot_release_the_resumed_generation` | Adapter、unit | 取消清理与旧代际不释放新 binding；后者仍是 transport unit |
| mixed/gap/NACK/seq/replay | `test_mixed_control_and_audio_share_one_client_sequence` 等 `test_call_v1_transport.py` | unit | 协议状态机覆盖，不宣称 endpoint 组合 |
| active connection | `test_unknown_resume_and_active_connection_takeover_are_rejected_without_new_identity` | Adapter | 公开拒绝与同一 facade 接入 |

仍未覆盖的最小边界：terminal release 的 2 秒 output-drain timeout 目前只能确定性地在
transport unit 层触发；要变为完整 endpoint 组合证据，需要不改生产超时的可控 output
consumer/clock 端口。failed resume 的 cursor/send fault 后“同一会话继续 retry”与当前
产品策略冲突：business commit 后的 fault 按契约终止 call，而不是继续 resume；仅
business commit 前的 resume fault 可重试，已如上覆盖。B4 文档治理与 CR1 五个
transport-abort cancellation 红灯不属于本 lane，未修改。

本 B3 lane 的当前具名执行结果（新增 endpoint 文件 + 既有 Adapter/transport 相关范围）：

```powershell
& .\.venv\Scripts\python.exe -m pytest `
  server/tests/integration/websocket/test_call_endpoint_failure_lifecycle.py `
  server/tests/integration/websocket/test_call_websocket_adapter.py `
  server/tests/integration/websocket/test_call_websocket_transport.py `
  server/tests/unit/adapter/websocket/test_call_v1_transport.py -q --tb=short
# 83 passed, 0 skipped, 3 warnings in 11.07s
```

静态验证：固定 `C:\Users\Administrator\.conda\envs\agent\Scripts\ruff.exe`
的 Ruff `0.14.10` 检查上述四个文件通过；同目录 Black `26.5.1` 以
`--config server/pyproject.toml --check` 通过；architecture B1-B10 与
`git diff --check` 通过。worktree `.venv` 缺失 `ruff.exe`/`black.exe`，故未把
解释器模块的启动失败误记为 lint 失败。未运行长 JS、全量网络、真实供应商或真机。

## 原始验证证据

Python 正式入口、边界、生命周期与恢复影响范围：

```powershell
& .\.venv\Scripts\python.exe -m pytest <17个具名文件> -q --tb=short
# 222 passed, 0 skipped, 3 warnings in 45.41s
```

具名范围包括：新增 architecture boundary、公开 Adapter、Web transport、handoff/finalization/real graph、runtime rollback/shutdown、协议单元测试、正式 FastAPI E2E、reset、chat.ready admission、stale recovery。警告为既有 ffmpeg、Starlette AnyIO alias 与 pkg_resources 警告。

正式 FastAPI 新增完整 FINALIZING 链：

```powershell
& .\.venv\Scripts\python.exe -m pytest `
  server/tests/e2e/call/test_call_network_success.py::test_production_entry_finalization_blocks_then_restores_chat_and_call `
  -q --tb=short
# 1 passed, 0 skipped in 13.25s
```

完整正式 call network Python 文件：`2 passed, 0 skipped in 13.90s`。受控 barrier 阻塞真实 `ConversationService.add_call_conversation` 的下一次写入，证明写阻塞期间 Chat/Call/reset 均被拒，释放后历史出现、Chat ready 恢复并可建立第二个 Call。

真实 JS ↔ FastAPI（显式 lane source/python，未修改 Jest 90 秒、server stop 12 秒、恢复 3 秒或产品时限）：

```powershell
$env:CALL_E2E_SERVER_SOURCE='C:\Agent-LuoTianyi\.slim\worktrees\call-refactor-cr'
$env:CALL_E2E_PYTHON='C:\Agent-LuoTianyi\.slim\worktrees\call-refactor-cr\.venv\Scripts\python.exe'
npx jest __tests__/call_failure_close_network.test.ts `
  __tests__/call_resume_race_diagnostic.test.ts `
  __tests__/call_real_network.test.ts --runInBand --detectOpenHandles
# 3 suites passed, 4 tests passed, 0 skipped, 116.784s
```

首次网络运行真实失败：`call_disconnect_evidence_server.py` 仍从 `src.server_runtime` 导入已不公开的 `CallTransportHub`，服务 exit 1；这是过渡测试接线遗漏，改为从 Adapter 内部模块导入后同三套件复跑通过。未靠增加 timeout 或重复到绿掩盖失败。

静态门禁：

- Ruff `0.14.10` changed Python paths：PASS
- Black `26.5.1` changed Python paths：PASS
- `server/scripts/check_architecture_boundaries.py`：PASS
- `git diff --check`：PASS
- 新增 `test_call_public_boundaries.py`：Manager 无过渡公开方法、call_v1 包根无内部导出、Web 无内部装配符号

CR-5 的具名三进程恢复测试未重跑：本阶段未改变恢复查询/算法或 process harness bootstrap；保留当前源码 CR-5 `1 passed, 0 skipped in 79.07s`、三进程 exit 0 的有效证据与 cold-import 波动历史。CR-6 仍运行了 `test_stale_call_recovery.py` 相关进程内恢复范围。

## 文档同步

- 代码地图改为唯一 `CallWebSocketAdapter → StageManager.open_call` 正式链，并明确包根稳定导出。
- Spec 的“没有 CallStage / 扩展旧 Adapter”客观冲突更新为当前并列 Adapter 与正式 CallStage 接线。
- 交接保留早期审查快照，但当前 Context/Skill/过渡接口状态已校准。
- CL-05 与早期切换验证标记为历史切片，不再作为当前能力清单。

## 非目标与未验风险

- 未使用真实供应商、付费模型、生产 vector 服务、Android 真机、设备音频、P95 或生产部署。
- call.v1 wire、错误码、close code、ACK/重放语义未改；没有实现 #324–335。
- ADR-0001 仍 Proposed；Spec 非作者审批与治理验收仍是维护者合入门禁。
- `StageManager.open_call` 现在负责来源推断、请求幂等查找与完整 claim/prepare 操作；Adapter 不再调用 `start_call`、`infer_call_source_interaction` 或 `find_call_by_request`，claim 仅存在于 Manager 内部。
- 测试 barrier 是 test-only verification affordance，不进入生产 endpoint，不记录 token、PCM、transcript 或 summary。

## 重启恢复后的最终状态校准

此前 `222 passed in 45.41s` 与三套 JS 网络绿色属于重启前候选快照；期间尝试清理格式 diff 时发生了错误的 PowerShell 文本重建，随后从 Git 原始 bytes 恢复并重新实施必要变更。此记录保留历史结果，但不把历史 Python 合并绿色冒充当前最终快照。

当前最终快照实际命令与结果：

```powershell
& .\.venv\Scripts\python.exe -m pytest server/tests/integration/architecture/test_call_public_boundaries.py server/tests/integration/websocket/test_call_websocket_adapter.py server/tests/integration/websocket/test_call_websocket_transport.py server/tests/integration/stage/test_call_handoff.py server/tests/integration/stage/test_stage_finalization.py server/tests/integration/runtime/test_runtime_initialization_rollback.py server/tests/integration/runtime/test_runtime_shutdown.py server/tests/e2e/call/test_call_network_success.py -q --tb=short
# 97 passed, 0 skipped, 3 warnings in 21.97s

& .\.venv\Scripts\python.exe -m pytest server/tests/integration/stage/test_call_finalization_real_graph.py server/tests/integration/stage/test_call_settlement_consumer.py server/tests/integration/stage/test_call_stage_binding.py server/tests/unit/adapter/websocket/test_call_v1_transport.py server/tests/unit/test_call_transport_capability.py server/tests/integration/application/test_user_data_reset.py server/tests/integration/websocket/test_chat_ready_admission.py server/tests/integration/stage/test_stale_call_recovery.py -q --tb=short
# 124 passed, 0 skipped, 3 warnings in 7.53s

& .\.venv\Scripts\python.exe -m pytest server/tests/integration/stage/test_call_coherent_runtime.py -q --tb=short
# 1 passed in 0.86s
```

上述命令分别报告，不累加为一条全套执行。coherent-runtime 在组合范围曾 `1 failed / 124 passed`：召回池在观察时尚为空；单独复核通过。没有更改产品超时或通过无界复跑掩盖该时序波动。

`test_call_transport_failures.py` 的 CR4 遗留 fixture 已适配正式两参 `Settlement.emit(snapshot, settlement_context)` 契约，并记录传入的 settlement context。早期复核的 `1 passed, 5 failed` 是历史中间快照：其中五项失败来自 CR1 owned termination 下 transport-abort 任务被 cleanup 取消。依据 CR1 已确认的方案 A，公共契约验证终态、账本、资源释放、ownership、closed 和无活跃任务，不要求触发终止的内部 abort task 以 success 完成；当前复核结果为 **6 passed, 1 warning**。生产代码未修改，五项不再作为 CR-6 阻断。

CR-6 当前证据状态已更新：部分 Stage 组合测试仍直接使用 Manager 私有 claim/create seam，属于内部故障注入或组合测试边界；公开接入路径已由 `open_call`、Adapter 和新增 endpoint 失败测试覆盖。旧 14 skip（13 个函数，其中 handshake 参数化为两项）已删除并按层级映射到公开 Adapter、endpoint 或 transport unit 测试；terminal output-drain timeout 仍明确只有 unit-level 证据，不能宣称公开 endpoint 全链覆盖。公开 Adapter send-pump、失败握手、旧 generation、取消恢复和终态身份已有组合证据。仅将 imports 或方法改为私有名不等于完成深封装，因此当前最终快照仍保留真实未验证边界，不把它们写成生产全覆盖。

当前静态检查使用 Ruff 0.14.10、Black 26.5.1，Black 显式 `--config server/pyproject.toml`，避免根目录运行默认 88 列造成无关重排；architecture 与 diff-check 通过。新结构测试同时纳入检查。
