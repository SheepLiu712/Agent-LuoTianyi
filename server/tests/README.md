# 服务端测试分层与门禁

测试按验证边界分为三层。测试文件只能放在 `unit/`、`integration/` 或 `e2e/`；跨目录复用的测试构造器、fake 与 fixture 放在 `tests/support/`，由测试通过 `from support.<模块> import ...` 导入。

## 分层规则

- `unit/<module>/`：围绕一个顶层模块的公开接缝验证行为，外部系统使用轻量 fake。目录按 `src` 子模块划分；不要求一一镜像内部包结构。
- `integration/<boundary>/`：在同一进程内连接两个或以上组件，允许临时 SQLite、真实文件系统和 FastAPI TestClient，但不依赖公网、生产凭据或真实模型。
- `e2e/chat/`：从生产装配或真实入口贯穿完整离线业务链。
- `e2e/external/`：需要公网、凭据、模型、GPU、生产资源或其他非确定性依赖的探测；默认跳过，必须显式启用。

根 `conftest.py` 根据首层目录自动添加 `unit`、`integration`、`e2e` 标记。`e2e/external` 还会添加 `external` 标记。测试不得再通过文件白名单或目录级 fixture 隐式跳过。

## 标准命令

以下命令均在 `server` 目录运行：

```powershell
# 快速单元测试
python -m pytest tests/unit -q --tb=short

# Agent 重构范围的单元测试行覆盖率门禁（pyproject.toml: fail_under = 40）
python -m pytest tests/unit -q --tb=short --cov --cov-report=term-missing

# 多组件集成测试，包含静态架构边界检查
python -m pytest tests/integration -q --tb=short

# 离线端到端测试；外部探测仍会跳过
python -m pytest tests/e2e -q --tb=short

# 默认全套确定性测试
python -m pytest tests -q --tb=short

# 显式运行真实外部依赖探测
python -m pytest tests/e2e/external -q --run-external --tb=short
```

真实 LLM 的可选测试仍需额外传入 `--run-real-llm`。CI 的强制门禁只包含可重复的单元、集成和离线 E2E；外部 E2E 用作具备相应环境时的人工/专项验收证据。

## 覆盖率口径

覆盖率只统计首阶段 Agent 重构范围：

- `src/agent`
- `src/agent_runtime`
- `src/domain/agent`
- `src/stage`

最低行覆盖率为 40%，且必须由 `tests/unit` 单独达到。覆盖率不是不变量验收的替代品；不变量的集成/E2E 证据见 [INVARIANTS.md](INVARIANTS.md)。

2026-09-19 本地基线（Windows、Python 3.10.19）：单元测试 `878 passed`，重构范围行覆盖率 `66.52%`；集成测试 `424 passed / 2 skipped`（可选真实 LLM）；离线 E2E `4 passed`，外部 E2E 默认 `15 skipped`。完整默认套件为 `1306 passed / 17 skipped`。
