import json
from io import StringIO

import pytest

from src.cli.actions import ActionExecutor, ExitCode, parse_action
from src.cli.main import main
from src.cli.output import Redactor, serialize_record
from src.session import (
    AggregatedReply,
    ReplyTimeoutError,
    SessionConnectionError,
    SessionState,
)


class FakeSession:
    def __init__(self, *, connect_error=None, ack=None, replies=None):
        self.state = SessionState.NEW
        self.connect_error = connect_error
        self.ack = ack or {"ok": True, "request_id": "generated-id", "error": None}
        self.replies = replies or {}
        self.calls = []

    def connect(self, username, password, *, timeout):
        self.calls.append(("connect", username, password, timeout))
        if self.connect_error:
            raise self.connect_error
        self.state = SessionState.READY

    def close(self):
        self.calls.append(("close",))
        self.state = SessionState.CLOSED

    def send_text(self, text, *, client_msg_id, ack_timeout):
        self.calls.append(("send_text", text, client_msg_id, ack_timeout))
        return {**self.ack, "request_id": client_msg_id}

    def get_reply(self, reply_uuid):
        return self.replies.get(reply_uuid)

    def wait_for_reply(self, reply_uuid, timeout):
        self.calls.append(("wait_for_reply", reply_uuid, timeout))
        reply = self.replies.get(reply_uuid)
        if reply is None:
            raise ReplyTimeoutError("secret-token timed out")
        return reply


def _reply(text="hello world"):
    return AggregatedReply(
        uuid="reply-1",
        texts=(text,),
        expressions=("smile",),
        complete=True,
        audio_path=None,
        audio_error=False,
        error_code=None,
        display_in_chat=True,
        is_ephemeral=False,
    )


def _executor(session=None, *, env=None):
    session = session or FakeSession()
    return ActionExecutor(
        session_factory=lambda **_kwargs: session,
        environ=env or {},
        session_id="session-test",
    ), session


def _connect(executor):
    executor.execute(
        {
            "action": "session.connect",
            "params": {
                "base_url": "http://localhost:60030",
                "username": "alice",
                "password": "secret",
            },
        }
    )


@pytest.mark.parametrize(
    "raw",
    [
        [],
        {},
        {"action": 1},
        {"action": "session.status", "params": []},
    ],
)
def test_action_parser_rejects_invalid_envelopes(raw):
    with pytest.raises(ValueError):
        parse_action(raw)


def test_jsonl_record_has_stable_schema_and_error_object():
    executor, _session = _executor()
    record, exit_code = executor.execute(
        {"action": "unknown.action", "action_id": "a-1", "params": {}}
    )
    serialized = json.loads(serialize_record(record, Redactor()))

    assert exit_code == ExitCode.INPUT_ERROR
    assert serialized.keys() == {
        "schema_version",
        "timestamp",
        "session_id",
        "action_id",
        "action",
        "event",
        "status",
        "duration_ms",
        "correlation_id",
        "data",
        "error",
    }
    assert serialized["schema_version"] == "1.0"
    assert serialized["event"] == "action_result"
    assert serialized["status"] == "failed"
    assert serialized["error"] == {
        "code": "UNKNOWN_ACTION",
        "message": "unknown action: unknown.action",
        "category": "input",
    }


def test_exit_code_categories_are_stable():
    assert ExitCode.SUCCESS == 0
    assert ExitCode.ASSERTION_FAILED == 2
    assert ExitCode.INPUT_ERROR == 3
    assert ExitCode.AUTH_TRANSPORT_ERROR == 4
    assert ExitCode.TIMEOUT == 5


def test_redactor_covers_nested_fields_strings_and_jsonl():
    redactor = Redactor(["plain-secret", "secret-token", "QUJDREVGRw=="])
    value = {
        "password": "plain-secret",
        "message_token": "secret-token",
        "Authorization": "Bearer secret-token",
        "audio_base64": "QUJDREVGRw==",
        "exception": "failed with plain-secret and secret-token",
    }
    output = serialize_record(value, redactor)

    for secret in ("plain-secret", "secret-token", "QUJDREVGRw=="):
        assert secret not in output
    assert json.loads(output)["password"] == "***"


def test_noninteractive_entrypoint_keeps_stdout_jsonl_and_stderr_separate():
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        ["--action", json.dumps({"action": "session.connect", "params": {}})],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == ExitCode.INPUT_ERROR
    lines = stdout.getvalue().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["error"]["code"] == "INVALID_INPUT"
    assert stderr.getvalue() == ""


def test_session_lifecycle_uses_same_session_and_environment_password():
    executor, session = _executor(env={"CLI_PASSWORD": "from-env"})

    connected, connect_exit = executor.execute(
        {
            "action": "session.connect",
            "params": {
                "base_url": "http://localhost:60030",
                "username": "alice",
                "password_env": "CLI_PASSWORD",
                "timeout": 1,
            },
        }
    )
    status, status_exit = executor.execute({"action": "session.status"})
    closed, close_exit = executor.execute({"action": "session.close"})

    assert (connect_exit, status_exit, close_exit) == (0, 0, 0)
    assert connected["status"] == "passed"
    assert status["data"] == {"state": "ready"}
    assert closed["data"] == {"state": "closed"}
    assert session.calls[0] == ("connect", "alice", "from-env", 1.0)
    assert "from-env" in executor.redactor.secrets


def test_connect_failure_is_auth_transport_error_and_redacted():
    secret = "login-secret"
    executor, _session = _executor(
        FakeSession(connect_error=SessionConnectionError(f"bad password {secret}"))
    )
    record, exit_code = executor.execute(
        {
            "action": "session.connect",
            "params": {
                "base_url": "http://localhost:60030",
                "username": "alice",
                "password": secret,
            },
        }
    )

    output = serialize_record(record, executor.redactor)
    assert exit_code == ExitCode.AUTH_TRANSPORT_ERROR
    assert secret not in output
    assert json.loads(output)["error"]["code"] == "AUTH_OR_TRANSPORT_FAILED"


@pytest.mark.parametrize(
    ("ack", "expected_exit", "expected_code"),
    [
        ({"ok": True, "error": None}, ExitCode.SUCCESS, None),
        ({"ok": False, "error": "rejected"}, ExitCode.ASSERTION_FAILED, "ACK_REJECTED"),
        ({"ok": False, "error": "Wait server ack timeout"}, ExitCode.TIMEOUT, "TIMEOUT"),
    ],
)
def test_send_text_reports_ack_success_rejection_and_timeout(
    ack,
    expected_exit,
    expected_code,
):
    executor, session = _executor(FakeSession(ack=ack))
    executor.execute(
        {
            "action": "session.connect",
            "params": {
                "base_url": "http://localhost:60030",
                "username": "alice",
                "password": "secret",
            },
        }
    )
    record, exit_code = executor.execute(
        {
            "action": "chat.send_text",
            "params": {"text": "hello", "client_msg_id": "msg-1", "ack_timeout": 2},
        }
    )

    assert exit_code == expected_exit
    assert record["correlation_id"] == "msg-1"
    assert (record["error"] or {}).get("code") == expected_code
    assert session.calls[-1] == ("send_text", "hello", "msg-1", 2.0)


@pytest.mark.parametrize(
    "assertions",
    [
        {"non_empty": True},
        {"contains": "world"},
        {"regex": r"hello\s+world"},
    ],
)
def test_reply_wait_and_read_apply_text_assertions(assertions):
    executor, _session = _executor(FakeSession(replies={"reply-1": _reply()}))
    _connect(executor)
    wait_record, wait_exit = executor.execute(
        {
            "action": "reply.wait",
            "params": {"reply_uuid": "reply-1", "timeout": 1, **assertions},
        }
    )
    read_record, read_exit = executor.execute(
        {"action": "reply.read", "params": {"reply_uuid": "reply-1", **assertions}}
    )

    assert wait_exit == read_exit == ExitCode.SUCCESS
    assert wait_record["data"]["text"] == "hello world"
    assert read_record["data"]["audio"] == {
        "available": False,
        "byte_count": 0,
        "format": None,
        "reference": None,
    }


def test_reply_assertion_failure_and_timeout_have_distinct_exit_codes():
    executor, _session = _executor(FakeSession(replies={"reply-1": _reply("hello")}))
    _connect(executor)
    failed, failed_exit = executor.execute(
        {
            "action": "reply.read",
            "params": {"reply_uuid": "reply-1", "contains": "missing"},
        }
    )
    timed_out, timeout_exit = executor.execute(
        {
            "action": "reply.wait",
            "params": {"reply_uuid": "missing", "timeout": 0.01},
        }
    )

    assert failed_exit == ExitCode.ASSERTION_FAILED
    assert failed["error"]["code"] == "ASSERTION_FAILED"
    assert timeout_exit == ExitCode.TIMEOUT
    assert timed_out["status"] == "timed_out"
    assert timed_out["error"]["code"] == "TIMEOUT"
