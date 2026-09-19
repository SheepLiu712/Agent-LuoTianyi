# World 单元测试

本目录验证 World 时钟、Runtime 配置和单个任务的局部行为；公网、生产凭据和真实模型均不属于单元测试。连接数据库、Stage、Agent 或结算路由的场景位于 `tests/integration/world`，真实 VCPedia/B 站探测位于 `tests/e2e/external`。

统一的分层定义、执行命令和覆盖率门禁见 [`tests/README.md`](../../README.md)，不变量证据见 [`tests/INVARIANTS.md`](../../INVARIANTS.md)。
