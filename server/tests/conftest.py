import os
from pathlib import Path

import pytest


_ACTIVE_TEST_FILES = {
    (Path(__file__).parent / "agent" / "test_output_sequences.py").resolve(),
    (Path(__file__).parent / "agent" / "test_output_delivery_recovery.py").resolve(),
    (Path(__file__).parent / "agent" / "test_output_storage_recovery.py").resolve(),
    (Path(__file__).parent / "agent" / "test_execution_idempotency.py").resolve(),
    (Path(__file__).parent / "agent" / "test_execution_storage_recovery.py").resolve(),
    (Path(__file__).parent / "agent" / "test_plan_emission.py").resolve(),
    (Path(__file__).parent / "agent" / "test_plan_logging.py").resolve(),
    (Path(__file__).parent / "agent" / "test_plan_delivery_recovery.py").resolve(),
    (Path(__file__).parent / "agent" / "test_request_idempotency.py").resolve(),
    (Path(__file__).parent / "agent" / "test_request_storage_recovery.py").resolve(),
    (Path(__file__).parent / "system" / "test_system_runtime_shutdown.py").resolve(),
    (Path(__file__).parent / "agent" / "test_handler_registration.py").resolve(),
    (Path(__file__).parent / "agent" / "test_handler_dispatch.py").resolve(),
    (Path(__file__).parent / "agent" / "test_facade_inflight_shutdown.py").resolve(),
    (Path(__file__).parent / "agent" / "test_facade_contract.py").resolve(),
    (Path(__file__).parent / "agent_runtime" / "test_agent_lookup.py").resolve(),
    (Path(__file__).parent / "agent_runtime" / "test_legacy_agent_access.py").resolve(),
    (Path(__file__).parent / "world" / "test_world_task_citywalk.py").resolve(),
    (Path(__file__).parent / "world" / "test_world_task_proactive_topic_check.py").resolve(),
    (Path(__file__).parent / "world" / "test_world_task_event_cleanup.py").resolve(),
    (Path(__file__).parent / "world" / "test_world_task_vcpedia_new_songs.py").resolve(),
    (Path(__file__).parent / "world" / "test_world_task_bili_event_update.py").resolve(),
    (Path(__file__).parent / "world" / "test_world_task_learn_sing_songs.py").resolve(),
    (Path(__file__).parent / "world" / "test_world_task_diary.py").resolve(),
    (Path(__file__).parent / "world" / "test_world_task_dynamics.py").resolve(),
    (Path(__file__).parent / "world" / "test_world_clock.py").resolve(),
    (Path(__file__).parent / "world" / "test_world_runtime.py").resolve(),
    (Path(__file__).parent / "domain" / "test_realization_contract.py").resolve(),
    (Path(__file__).parent / "domain" / "test_stimulus_text_message_contract.py").resolve(),
    (Path(__file__).parent / "domain" / "test_stimulus_registered_types_contract.py").resolve(),
    (Path(__file__).parent / "domain" / "test_stimulus_value_types_contract.py").resolve(),
    (Path(__file__).parent / "domain" / "test_handle_input_contract.py").resolve(),
    (Path(__file__).parent / "domain" / "test_handling_report_contract.py").resolve(),
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
