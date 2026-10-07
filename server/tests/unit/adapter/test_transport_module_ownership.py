"""Network hosts, application use cases, and adapters keep distinct ownership."""

from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[3]


def test_http_and_websocket_hosts_belong_to_web() -> None:
    http = SERVER_ROOT / "src" / "web" / "http"
    websocket = SERVER_ROOT / "src" / "web" / "websocket"

    assert (http / "project_plan.py").is_file()
    assert (http / "runtime_access.py").is_file()
    assert (websocket / "service.py").is_file()
    assert (websocket / "messages.py").is_file()


def test_admin_routes_and_use_cases_have_separate_owners() -> None:
    assert (SERVER_ROOT / "src" / "web" / "admin" / "admin_interface.py").is_file()
    assert (SERVER_ROOT / "src" / "application" / "admin" / "runtime_supervisor.py").is_file()
    assert (SERVER_ROOT / "src" / "application" / "user" / "account.py").is_file()
    assert (SERVER_ROOT / "src" / "web" / "http" / "user_interface.py").is_file()


def test_adapter_keeps_only_channel_translation_and_binding() -> None:
    adapter = SERVER_ROOT / "src" / "adapter"
    websocket = adapter / "websocket"

    assert (websocket / "adapter.py").is_file()
    assert (websocket / "_input.py").is_file()
    assert (websocket / "_delivery.py").is_file()
    assert not (websocket / "service.py").exists()
    assert not tuple((adapter / "http").glob("*.py"))
    assert not tuple((adapter / "admin").glob("*.py"))


def test_old_system_transport_dirs_are_gone() -> None:
    system = SERVER_ROOT / "src" / "system"
    assert not (system / "user_interface").exists()
    assert not (system / "network_helper").exists()
    assert not (system / "admin").exists()
