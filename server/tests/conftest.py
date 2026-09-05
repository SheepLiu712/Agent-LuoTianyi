import os
from pathlib import Path

import pytest


_ACTIVE_TEST_FILES = {
    (Path(__file__).parent / "domain" / "test_stimulus_text_message_contract.py").resolve(),
    (Path(__file__).parent / "domain" / "test_stimulus_registered_types_contract.py").resolve(),
}
_DEFERRED_TEST_REASON = "现有 Server 测试暂由项目负责人统一处理"


def pytest_addoption(parser):
    parser.addoption(
        "--run-real-llm",
        action="store_true",
        default=False,
        help="运行会发起真实 LLM 请求的测试；默认跳过。",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "real_llm: 需要真实 LLM 请求的测试，默认跳过")


def pytest_collection_modifyitems(config, items):
    run_real_llm = config.getoption("--run-real-llm") or os.getenv("RUN_REAL_LLM_TESTS") == "1"
    skip_real_llm = pytest.mark.skip(reason="真实 LLM 测试默认跳过；使用 --run-real-llm 或 RUN_REAL_LLM_TESTS=1 开启")
    skip_deferred_test = pytest.mark.skip(reason=_DEFERRED_TEST_REASON)

    for item in items:
        if Path(str(item.path)).resolve() not in _ACTIVE_TEST_FILES:
            item.add_marker(skip_deferred_test)
        elif not run_real_llm and "real_llm" in item.keywords:
            item.add_marker(skip_real_llm)
