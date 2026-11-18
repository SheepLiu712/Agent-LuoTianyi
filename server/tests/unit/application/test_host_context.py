from src.application.host_context import ServerHostContext


def test_only_explicit_supported_launcher_proves_single_process_calls():
    assert ServerHostContext._single_worker_launcher().supports_single_process_calls is True
    assert (
        ServerHostContext(
            launcher="server_main.run_server", worker_count=1, reload_enabled=False
        ).supports_single_process_calls
        is False
    )
    assert (
        ServerHostContext(launcher="uvicorn", worker_count=1, reload_enabled=False).supports_single_process_calls
        is False
    )
    assert (
        ServerHostContext(
            launcher="server_main.run_server", worker_count=2, reload_enabled=False
        ).supports_single_process_calls
        is False
    )
    assert (
        ServerHostContext(
            launcher="server_main.run_server", worker_count=1, reload_enabled=True
        ).supports_single_process_calls
        is False
    )
