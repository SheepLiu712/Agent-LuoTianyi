# Agent 单元测试

本目录从 Agent 深模块的公开接缝验证 handler、skill、计划与输出生成等局部行为。Agent 门面、Runtime、Stage、持久化或网络之间的跨组件契约位于 `tests/integration`，完整生产装配链位于 `tests/e2e`。

统一的分层定义、执行命令和覆盖率门禁见 [`tests/README.md`](../../README.md)，不变量证据见 [`tests/INVARIANTS.md`](../../INVARIANTS.md)。
