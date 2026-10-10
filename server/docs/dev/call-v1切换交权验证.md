# `call.v1` ChatStage 切换交权验证

## 范围

本阶段在 StageManager 中接入进程内 `(user_id, character_id)` 租约、当前聊天绑定验证、10 秒一次性 `CallTransitionIntent`、PREPARING SQL 账本和 `SWITCH_TO_CALL` 结束维护。

成功顺序固定为：

1. 当前已绑定 chat connection 登记 intent
2. `call.start` 先按 `client_request_id` 查询账本
3. 首次请求原子消费 intent，并将 CHAT lease 替换为 CALL_TRANSITION
4. 建立 PREPARING 账本
5. ChatStage 从可复用集合移除并停止接收普通输入
6. 取消普通工作，执行 `InteractionEnding(SWITCH_TO_CALL)` 认知维护
7. 关闭旧 InteractionContext
8. 将 lease 从 CALL_TRANSITION 切换为稳定 call ID 的 CALL
9. 返回 `CallStartClaim`

当前没有 CallStage 生产实现，因此 claim 不创建新的 InteractionContext。CL-6 后续 factory 只能在该 claim 之后创建通话 Context，确保两个 Context 不同时存活。

## 失败和幂等

- intent 只允许当前绑定 connection 创建；其他设备、角色、source interaction 或 request 不匹配均不能抢占
- 相同 intent 重复 prepare 幂等，不同 request 被拒绝
- 同 request 并发 start 共享一个 owned handoff task，账本只有一个 winner
- 已完成 start 重试按账本和 CALL lease 返回同一 call ID，不要求 intent 仍存在
- 结束维护失败或超时：旧 Context 仍关闭、transition lease 释放、账本转 FAILED，不授予 CALL
- 调用者取消：已经开始的 handoff 完成后才传播取消，不留下半交权
- 普通 chat disconnect 仍保留 60 秒并可重连同一 ChatStage
- shutdown/离线 retirement 释放对应 CHAT lease
- prepare 成功后 Adapter 暂停该 connection 的业务输入；text/image/voice/coordination 返回稳定、可重试的 `CALL_SWITCH_PENDING`，不进入 Stage 或普通去重表。heartbeat/auth 等 transport 事件不受影响
- intent 到期或 ledger create 失败时恢复原 chat binding 的业务输入，但清除旧 intent，客户端必须重新 prepare
- ledger 建立前失败：CALL_TRANSITION 原子回滚到原 CHAT lease，ChatStage/binding/context 均保持；不写 FAILED ledger
- ledger 建立后失败：旧 Stage 必须 terminate/close，transition 释放，PREPARING ledger 转 FAILED，旧 binding 不恢复
- 进行中 handoff 以 `(request_id, user, character, source interaction)` 固定身份；相同四元组共享 owned task，request 相同但 owner/character/source 不同稳定拒绝
- manager close 先标记 closed，再等待所有 owned handoff task；shutdown 中不得授予 CALL，已存在 PREPARING 账本转 FAILED，旧 Context 关闭后才返回
- `source_interaction_id=None` 只在 lease 空闲时允许 direct start：原子 claim CALL_TRANSITION、写 PREPARING、再转 CALL；offline retained CHAT、现有 CALL 或另一 transition 均不可抢占
- 整个首次 start 使用单一 monotonic deadline（默认 10 秒），ledger lookup/create、chat unbind、termination 与 finish 都消耗同一剩余预算，不为每步重置
- 同步 repository lookup/create/update 通过 `asyncio.to_thread` 与 owned completion 执行；调用超时/取消或 shutdown 不会遗留无人清理的 late-created PREPARING ledger
- 已创建 ledger 后超时或 shutdown：direct/chat transition 均释放，旧 chat Context owned 关闭，账本尝试转 FAILED；数据库 cleanup 异常记录但不阻止 ownership finally 清理
- 同步数据库线程已经开始后无法由 asyncio 强制中断；deadline 约束的是业务交权结果，线程完成后再依据实际结果做 cleanup

## 时间边界

账本写入使用 aware 北京时间。StageManager 的技术时间戳保证每次新 lifecycle 写入严格晚于本进程上一条 call timestamp：若 wall clock 相同或回退，则使用上一时间加一微秒。该时间仅用于 SQL CAS，不用于有效通话 elapsed；elapsed 仍归 monotonic clock。

## 限制

- 生产 `call_transport_available` 仍为 false
- 没有 CallStage、provider、call Context factory attach 或完整 `/call_ws` start 接线
- 当前集成测试使用真实 ChatStage / Agent termination / Context close 与 repository contract；CallStage future seam 不以 fake 冒充生产能力
- 多 worker 拓扑没有权威 attestation，call 保持禁用，chat 不受影响

## 阶段 2 当前验证

- 最后 bounded remediation 后 handoff/chat/lease/Adapter：86 passed
- Stage integration 扩大回归：142 passed
- Call Context、结束维护和 ledger 相关目标：109 passed
- Black、Ruff、架构边界与 `git diff --check`：passed
- 测试中的未来 CallStage consumer 只表现为 `CallStartClaim` 后置 seam，没有生产 fake CallStage
- handoff 持久化包含真实 SQLite repository；认证 connection 与 Agent/Context 是离线测试装配，不冒充完整 `/call_ws` 或 CallStage e2e
- Oracle gate attempt 1/2/3 历史结论均为 `BLOCKED`，review budget 已耗尽；本记录只陈述 bounded remediation 和测试事实，不宣称 gate、人类审核或完整 CL-5 已通过
- setup deadline 触发后，已启动的 `ChatStage.terminate` 不会被取消或重复启动；handoff 继续 owned 等待 termination maintenance 与 Context finally close，期间 lease 保持 CALL_TRANSITION，新 chat/direct call 都不能获得 ownership
- termination 完成后才释放 transition、写 FAILED ledger 并传播 timeout/cancellation。setup timeout 使用 `SETUP_TIMEOUT`；shutdown、maintenance 和其他系统失败使用 `SYSTEM_FAILURE`
- 最后 bounded remediation 后：handoff/chat/lease/Adapter 86 passed，Stage integration 142 passed，Context/ending maintenance/ledger 109 passed
