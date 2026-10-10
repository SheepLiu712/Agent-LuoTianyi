# `call.v1` 呼叫账本 partial 验证

## 范围与状态

本增量只交付 CL-10a 的持久化基础：additive `call_sessions` schema、SQL repository、线程安全 fake 以及共享 repository contract。它不代表完整 CL-10、完整 F2 或生产账本接线已经完成。

依赖关系为堆叠开发历史：PR #269、PR #272 与 PR #284 提供骨架、认知维护和上下文 Store 前置；这些依赖不能被描述为已经合入 `dev`。

Oracle ledger gate 三轮历史均保留为 BLOCKED。最终等时 lifecycle CAS 缺口由独立 focused 验证确认 Fixed：81 个定向测试与 18 个真实 SQLite 探针检查。该证据用于允许 partial 提交，不是第四次架构 review，也不替代非作者开发者审核。

## 时间边界

- `CallSessionRecord` 六个 datetime 字段与 stale cutoff 必须 timezone-aware
- 其他 offset 显式归一化到固定 UTC+8 北京时间
- SQLite 写入 naive Beijing，读取时附回固定 `+08:00`
- naive 输入全部拒绝，不调用无参数 `astimezone()`，不依赖宿主时区
- 该边界不修改 CL-2 legacy naive 接口；未来 Stage 必须显式转换
- 有效通话时长仍由后续 Stage 的 monotonic clock 计算，不能由 wall clock 推导

## 并发和幂等

- `client_request_id` 并发创建收敛到数据库 winner
- request 与 call ID 两个 unique constraint 命中不同记录时拒绝 crossed identity
- lifecycle CAS 只允许严格更新的 `updated_at` 写入；等时不同 payload 只有一个 winner
- 完全相同 lifecycle payload 可在 expected state 已变化后读回为幂等成功
- lifecycle 幂等比较排除 summary/maintenance 独立字段和 settlement 推进的共享时间
- terminal lifecycle 不可复活
- summary / maintenance 使用独立、仅 `ENDED` 可执行的 status CAS
- 两 settlement lane 并发完成不会互相覆盖
- maintenance 失败不推进 turn seq，成功进度不倒退
- summary 成功要求 UUID conversation ID，失败必须不带 conversation ID

## 隐私与恢复查询

schema 字段严格等于 `CallSessionRecord` allowlist，不保存 PCM、转录、逐轮内容、概要正文、工作摘要或上下文。SQL 与 fake 共用 `STALE_RECOVERABLE_STATES`，terminal records 不进入 stale recovery 查询。owner 范围删除不会影响其他用户。

## 2026-10-11 验证证据

| 范围 | 结果 |
| --- | --- |
| repository unit + SQL ledger integration | 81 passed |
| persistence integration 扩大回归 | 131 passed, 2 skipped |
| 独立真实 SQLite focused probe | 18 checks passed，最终等时 CAS 缺口 Fixed |
| Black / Ruff | passed |
| 架构边界 | B1–B10 passed |
| `git diff --check` | passed，仅 Windows CRLF 提示 |

## 尚未实现或验证

- ServerRuntime / Stage 生产 repository 绑定
- 服务启动时 stale ledger 崩溃结算
- 通话概要生成与固定回退
- UUIDv5 Conversation 写入和历史投影
- 账户重置编排与关联记忆/画像清理
- 结算期限、指标、日志和完整 observability
- 完整 F2 e2e、真实供应商或设备测试
- 非作者开发者正式审核与人工验收
