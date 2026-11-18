# 服务端测试分层与门禁

测试按验证边界分为三层。测试文件只能放在 `unit/`、`integration/` 或 `e2e/`；跨目录复用的测试构造器、fake 与 fixture 放在 `tests/support/`，由测试通过 `from support.<模块> import ...` 导入。

## 分层规则

- `unit/<module>/`：围绕一个顶层模块的公开接缝验证行为，外部系统使用轻量 fake。目录按 `src` 子模块划分；不要求一一镜像内部包结构。
- `integration/<boundary>/`：在同一进程内连接两个或以上组件，允许临时 SQLite、真实文件系统和 FastAPI TestClient，但不依赖公网、生产凭据或真实模型。
- `e2e/chat/`：从生产装配或真实入口贯穿完整离线业务链。
- `e2e/external/`：需要公网、凭据、模型、GPU、生产资源或其他非确定性依赖的探测；默认跳过，必须显式启用。

根 `conftest.py` 根据首层目录自动添加 `unit`、`integration`、`e2e` 标记。`e2e/external` 还会添加 `external` 标记。除下述明确的平台选择外，测试不得通过文件白名单或目录级 fixture 隐式跳过。

## 标准命令

以下命令均在 `server` 目录运行：

先安装开发依赖和真实语言分段测试使用的两个轻量包，与离线 CI 保持一致：

```bash
python -m pip install -e '.[dev]' httpx
python -m pip install --no-deps gsv-tts-lite==0.4.7 py3langid==0.4.0
```

语言分段测试直接加载 `LangSegment.py`，不导入 gsv 的音频入口、不加载声学模型，也不需要 GPU。
`numpy>=2` 由服务端基础依赖提供。这里的 `--no-deps` 仅用于分段测试；完整语音服务仍须使用正式部署环境。
缺少测试依赖会报告错误，不会以跳过测试代替验收。

### Ubuntu 与 CI

Ubuntu 执行完整离线范围，包括 `integration/deployment/`。该目录验证 Linux 版本化部署，依赖 Unix 文件锁、用户库、Bash 与 systemd；Windows 安装和启动脚本的存在不代表这些部署能力已跨平台实现。

```bash
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

### Windows 本地

本地优先运行受影响范围。根 `conftest.py` 在 Windows 收集测试之前排除 `integration/deployment/`，避免模块级 `fcntl` 导入导致整层中断，并在结果末尾打印平台范围说明；不使用 `skipif`、`importorskip` 或忽略收集错误。Ubuntu 不应用此排除。

```powershell
# 按改动选择集成场景
python -m pytest tests/integration/stage/test_call_opening_readiness.py -q --tb=short

# Windows 可收集的集成范围，自动排除 Linux 部署目录
python -m pytest tests/integration -q --tb=short
```

`python -m pytest tests` 和下述分层调度器也应用相同的平台选择。Windows 结果只代表本地已选择范围，不能写成 Linux 部署验收或全平台全量通过；其他测试的缺依赖或失败仍照常报错。完整离线门禁以 Ubuntu CI 为准。

## 离线 CI 的并行方式

CI 在同一环境中分别启动 unit 与 integration 两个独立 pytest 进程，二者结束后再运行离线 e2e。
真实网络与进程重启测试不与其他测试进程争用资源，继续保留原有等待上限。
测试目录、外部测试排除规则及断言不因分组而减少；每组单独生成 XML 和日志，合并报告仍检查零跳过、零失败。

在具备上述测试依赖和离线配置的环境中运行：

```bash
python ../.github/scripts/run_server_tests.py
python ../.github/scripts/check_pytest_results.py test-results.xml
```

每组输出最慢 30 个 setup/call/teardown 阶段，脚本报告分组及总墙钟时间。
本机测试应保证 localhost/127.0.0.1 不经过代理；测试服务使用临时实例，不要指向生产配置和数据库。

## 覆盖率口径

覆盖率只统计首阶段 Agent 重构范围：

- `src/agent`
- `src/agent_runtime`
- `src/domain/agent`
- `src/stage`

最低行覆盖率为 40%，且必须由 `tests/unit` 单独达到。覆盖率不是不变量验收的替代品；不变量的集成/E2E 证据见 [INVARIANTS.md](INVARIANTS.md)。

2026-09-19 本地基线（Windows、Python 3.10.19）：单元测试 `878 passed`，重构范围行覆盖率 `66.52%`；集成测试 `424 passed / 2 skipped`（可选真实 LLM）；离线 E2E `4 passed`，外部 E2E 默认 `15 skipped`。完整默认套件为 `1306 passed / 17 skipped`。
