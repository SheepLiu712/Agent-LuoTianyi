import os

import pytest


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
    if run_real_llm:
        return

    skip_real_llm = pytest.mark.skip(reason="真实 LLM 测试默认跳过；使用 --run-real-llm 或 RUN_REAL_LLM_TESTS=1 开启")
    for item in items:
        if "real_llm" in item.keywords:
            item.add_marker(skip_real_llm)
