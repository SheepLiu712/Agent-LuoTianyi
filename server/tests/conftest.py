import os
import sys
from pathlib import Path

import pytest

TEST_ROOT = Path(__file__).resolve().parent
SERVER_ROOT = TEST_ROOT.parent
for import_root in (TEST_ROOT, SERVER_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from support.agent_runtime_support import runtime, runtime_dependencies  # noqa: E402,F401
from support.routing_support import routed_runtime  # noqa: E402,F401
from src.utils.logger import get_logger  # noqa: E402


@pytest.fixture
def capture_project_log(caplog):
    """把指定项目 logger 临时接到 pytest 捕获处理器，保持生产 propagate 配置不变。"""
    attached = []

    def capture(name: str):
        logger = get_logger(name)
        logger.addHandler(caplog.handler)
        attached.append(logger)
        return logger

    yield capture
    for logger in attached:
        logger.removeHandler(caplog.handler)


def pytest_addoption(parser):
    parser.addoption(
        "--run-real-llm",
        action="store_true",
        default=False,
        help="运行会发起真实 LLM 请求的测试；默认跳过。",
    )
    parser.addoption(
        "--run-external",
        action="store_true",
        default=False,
        help="运行需要真实网络或凭据的端到端测试；默认跳过。",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "unit: 单一顶层模块的快速离线测试")
    config.addinivalue_line("markers", "integration: 多个模块在进程内协作的测试")
    config.addinivalue_line("markers", "e2e: 从生产入口观察完整业务链路的端到端测试")
    config.addinivalue_line("markers", "external: 需要真实网络、凭据或外部服务")
    config.addinivalue_line("markers", "real_llm: 需要真实 LLM 请求的测试，默认跳过")


def pytest_collection_modifyitems(config, items):
    run_real_llm = config.getoption("--run-real-llm") or os.getenv("RUN_REAL_LLM_TESTS") == "1"
    run_external = config.getoption("--run-external") or os.getenv("RUN_EXTERNAL_TESTS") == "1"
    skip_real_llm = pytest.mark.skip(reason="真实 LLM 测试默认跳过；使用 --run-real-llm 或 RUN_REAL_LLM_TESTS=1 开启")
    skip_external = pytest.mark.skip(reason="真实外部依赖测试默认跳过；使用 --run-external 或 RUN_EXTERNAL_TESTS=1 开启")

    for item in items:
        relative = Path(str(item.path)).resolve().relative_to(TEST_ROOT)
        layer = relative.parts[0]
        item.add_marker(getattr(pytest.mark, layer))
        if layer == "e2e" and len(relative.parts) > 1 and relative.parts[1] == "external":
            item.add_marker(pytest.mark.external)
        if not run_external and "external" in item.keywords:
            item.add_marker(skip_external)
        if not run_real_llm and "real_llm" in item.keywords:
            item.add_marker(skip_real_llm)
