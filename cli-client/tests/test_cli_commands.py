"""Human-facing command grammar and image URI acceptance."""

import importlib.util
from io import StringIO
from pathlib import Path

import pytest

from cli_client.cli.actions import ActionExecutor
from cli_client.cli.commands import CommandError, command_candidates, parse_command
from cli_client.cli.main import main
from cli_client.utils import image_rules


def _action(command: str, env=None):
    parsed = parse_command(command, environ=env or {})
    return parsed.actions[0]


def test_text_image_touch_and_quoted_preference_commands():
    assert _action('/text "你好 世界"')["params"] == {"text": "你好 世界"}
    assert _action('/image "C:\\photo dir\\a.png"')["params"] == {"path": "C:\\photo dir\\a.png"}
    assert _action("/touch")["params"] == {"touch_area": "头"}
    assert _action('/set-preference relationship="好 朋友"')["params"] == {
        "values": {"relationship": "好 朋友"},
        "replace": False,
    }


def test_command_options_defaults_and_validation():
    env = {"CLI_E2E_BASE_URL": "https://example.invalid", "CLI_E2E_USER": "alice", "CLI_E2E_PASSWORD": "secret"}
    assert _action("/login --remember", env)["params"]["remember_login"] is True
    assert _action("/register alice CODE", env)["params"]["invite_code"] == "CODE"
    assert _action("/history 20 --end-index -1")["params"]["end_index"] == -1
    assert _action("/wait agent_state thinking --timeout 90")["params"]["timeout"] == 90
    with pytest.raises(CommandError, match="不支持选项"):
        _action("/status --remember")
    with pytest.raises(CommandError, match="引号未闭合"):
        _action('/text "你好')
    with pytest.raises(CommandError, match="必须是数字"):
        _action("/history --end-index bad")


def test_completion_candidates_and_help():
    assert [name for name, _ in command_candidates("/te")] == ["/text"]
    assert command_candidates("/text hello") == []
    assert "发送文字" in parse_command("/help text").help_text
    assert parse_command("/exit").exit_requested


def test_default_shell_output_is_readable_and_accepts_stdin_commands():
    output = StringIO()
    code = main([], stdin=StringIO("/status\n/help text\n/exit\n"), stdout=output, stderr=StringIO())
    assert code == 0
    assert "会话状态：new" in output.getvalue()
    assert "发送文字" in output.getvalue()
    assert not output.getvalue().lstrip().startswith("{")


def test_file_uri_image_is_accepted(tmp_path):
    image = tmp_path / "photo.png"
    image.write_bytes(b"PNG")
    executor = ActionExecutor()
    assert executor._validate_image_path(image.as_uri()) == image


def test_remote_image_uri_is_size_limited(monkeypatch, tmp_path):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield b"PNG"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("cli_client.cli.actions.requests.get", lambda *args, **kwargs: Response())
    result = ActionExecutor()._validate_image_path("https://example.invalid/photo.png")
    assert result.read_bytes() == b"PNG"
    assert result.parent == tmp_path / "temp" / "cli_images"

    class Oversized(Response):
        def iter_content(self, chunk_size):
            yield b"x" * (image_rules.MAX_IMAGE_BYTES + 1)

    monkeypatch.setattr("cli_client.cli.actions.requests.get", lambda *args, **kwargs: Oversized())
    with pytest.raises(ValueError, match="size limit"):
        ActionExecutor()._validate_image_path("https://example.invalid/large.png")
    assert list(result.parent.iterdir()) == [result]


def test_manual_slash_scripts_parse_without_embedded_password(monkeypatch):
    root = Path(__file__).parent / "manual_e2e"
    monkeypatch.setenv("CLI_E2E_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("CLI_E2E_USER", "test-user")
    monkeypatch.setenv("CLI_E2E_PASSWORD", "test-password")
    monkeypatch.setenv("CLI_E2E_IMAGE", "C:/tmp/image.png")
    for script in root.glob("*.cli"):
        if script.name.startswith("21-"):
            continue  # Intentional input-error example.
        content = script.read_text(encoding="utf-8")
        assert "test-password" not in content
        for line in content.splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                assert parse_command(line).actions


def test_manual_driver_adapter_sends_public_command_grammar():
    helper = Path(__file__).parent / "manual_e2e" / "driver_support.py"
    spec = importlib.util.spec_from_file_location("driver_support", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    env = {"CLI_E2E_BASE_URL": "https://example.invalid", "CLI_E2E_USER": "alice", "CLI_E2E_PASSWORD": "secret"}
    login = module.slash_command(
        "session.connect",
        {"base_url": "https://example.invalid", "username": "alice", "password_env": "CLI_E2E_PASSWORD"},
    )
    assert _action(login, env)["action"] == "session.connect"
    assert _action(module.slash_command("events.wait", {"kind": "agent_state", "value": "thinking", "after_seq": 2}))[
        "params"
    ] == {"kind": "agent_state", "value": "thinking", "after_seq": 2}
