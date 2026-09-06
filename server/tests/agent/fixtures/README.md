# 执行账本版本一夹具

`execution_v1_outputs.sql` 在 PR117 合并点 `a866f521af1d59d707532c0c750276bafd7f8b69` 的产品实现上生成，只有测试角色与固定领域样例。先通过 Agent 构造真实临时 SQLite 表，再通过公开 `realize_action_plan` 执行以下四次调用，最后从 SQLite 导出其真实建表语句与数据；没有自行复写账本 JSON 编码。

| execution_id | 受控处理器/接收器行为 | 公开结果 |
| --- | --- | --- |
| legacy_terminal | 两项行动各发送一次并完成 | COMPLETED，output_started=True |
| legacy_partial | 第一项发送并完成，第二项无输出可信失败 | FAILED，output_started=True，retryable=True |
| legacy_no_output | 第一项未输出即可信失败 | FAILED，output_started=False，retryable=True |
| legacy_unknown | 首次投递超时，处理器返回可信无效果失败 | FAILED，output_started=False，retryable=False |

计划与上下文采用 `routing_support.plan_and_context()`；只有 execution_id 按表中四值替换。发送采用旧 `routing_support.output(action_id, execution_id=...)`，可信失败使用 PROVIDER_TIMEOUT。真实作用仅为本地临时 SQLite 和 Fake sink，没有生产数据或网络。

测试在新 AgentRuntime 初始化前载入这份旧表，使其覆盖旧数据库的实际打开与兼容行为。该夹具固定旧事实，不能用升级后的 Agent 重新生成后仍称为版本一。
