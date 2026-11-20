"""启动入口根据运行模式选择实际传给服务器的监听端口。"""

from unittest.mock import AsyncMock

import pytest

import server_main


@pytest.mark.parametrize("is_debug, expected_port", [(True, 24523), (False, 15673)])
def test_startup_selects_configured_mode_port(monkeypatch, capsys, is_debug, expected_port):
    config = {
        "is_debug": is_debug,
        "server": {"debug_port": 24523, "production_port": 15673},
    }
    monkeypatch.setattr(server_main, "config", config)
    monkeypatch.delenv("SERVER_PORT", raising=False)
    monkeypatch.setenv("SERVER_HOST", "127.0.0.1")
    run_server = AsyncMock()
    monkeypatch.setattr(server_main, "run_server", run_server)

    server_main.main()

    run_server.assert_awaited_once_with("127.0.0.1", expected_port)
    assert f"http://127.0.0.1:{expected_port}/admin" in capsys.readouterr().out


@pytest.mark.parametrize("is_debug, expected_port", [(True, 24523), (False, 15673)])
@pytest.mark.parametrize("environment_port", ["18080", "invalid-port"])
def test_environment_port_does_not_override_config(monkeypatch, is_debug, expected_port, environment_port):
    monkeypatch.setattr(
        server_main,
        "config",
        {
            "is_debug": is_debug,
            "server": {"debug_port": 24523, "production_port": 15673},
        },
    )
    monkeypatch.setenv("SERVER_HOST", "0.0.0.0")
    monkeypatch.setenv("SERVER_PORT", environment_port)
    run_server = AsyncMock()
    monkeypatch.setattr(server_main, "run_server", run_server)

    server_main.main()

    run_server.assert_awaited_once_with("0.0.0.0", expected_port)


@pytest.mark.parametrize("is_debug, port", [("false", 15673), (False, 0), (False, "15673")])
def test_invalid_startup_config_fails_before_starting_server(monkeypatch, is_debug, port):
    monkeypatch.setattr(
        server_main,
        "config",
        {
            "is_debug": is_debug,
            "server": {"debug_port": 24523, "production_port": port},
        },
    )
    monkeypatch.delenv("SERVER_PORT", raising=False)
    run_server = AsyncMock()
    monkeypatch.setattr(server_main, "run_server", run_server)

    with pytest.raises(ValueError):
        server_main.main()

    run_server.assert_not_called()
