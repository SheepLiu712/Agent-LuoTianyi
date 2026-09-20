import json
import threading

import pytest

from src.cli.actions import ActionExecutor, ExitCode
from src.session import HeadlessSession, SessionNotReadyError, SessionState


class FakeSession:
    def __init__(self):
        self.state = SessionState.READY
        self.preferences = {"theme": "dark", "volume": 50}
        self.get_calls = 0
        self.overwrite_calls = []
        self.overwrite_result = {"ok": True}
        self.on_overwrite = None

    def get_preferences(self):
        self.get_calls += 1
        return dict(self.preferences)

    def overwrite_preferences(self, preferences):
        self.overwrite_calls.append(dict(preferences))
        self.preferences = dict(preferences)  # 模拟服务端覆盖生效
        if self.on_overwrite is not None:
            self.on_overwrite(dict(preferences))
        return dict(self.overwrite_result)

    def close(self):
        self.state = SessionState.CLOSED


def _executor(session):
    executor = ActionExecutor(
        session_factory=lambda **_kwargs: session,
        session_id="session-preferences",
    )
    executor._session = session
    return executor


def _action(executor, action, **params):
    return executor.execute({"action": action, "params": params})


def test_preferences_open_stores_snapshot_and_outputs_full_object():
    session = FakeSession()
    executor = _executor(session)

    record, exit_code = _action(executor, "preferences.open")

    assert exit_code == ExitCode.SUCCESS
    assert record["data"]["preferences"] == {"theme": "dark", "volume": 50}
    assert session.get_calls == 1


def test_preferences_read_auto_opens_when_no_snapshot():
    session = FakeSession()
    executor = _executor(session)

    record, exit_code = _action(executor, "preferences.read")

    assert exit_code == ExitCode.SUCCESS
    assert session.get_calls == 1
    assert record["data"]["preferences"]["theme"] == "dark"


def test_preferences_read_uses_snapshot_without_refetch():
    session = FakeSession()
    executor = _executor(session)
    assert _action(executor, "preferences.open")[1] == ExitCode.SUCCESS
    session.preferences = {"theme": "light"}

    record, exit_code = _action(executor, "preferences.read")

    assert exit_code == ExitCode.SUCCESS
    assert record["data"]["preferences"] == {"theme": "dark", "volume": 50}
    assert session.get_calls == 1


def test_preferences_update_merges_by_key_and_confirms():
    session = FakeSession()
    executor = _executor(session)
    assert _action(executor, "preferences.open")[1] == ExitCode.SUCCESS

    record, exit_code = _action(executor, "preferences.update", values={"volume": 80})

    assert exit_code == ExitCode.SUCCESS
    assert session.overwrite_calls == [{"theme": "dark", "volume": 80}]
    assert record["data"]["updated_keys"] == ["volume"]
    assert record["data"]["confirmed"] is True
    assert record["data"]["preferences"] == {"theme": "dark", "volume": 80}


def test_preferences_update_replace_mode_overwrites_exactly():
    session = FakeSession()
    executor = _executor(session)

    record, exit_code = _action(
        executor, "preferences.update", values={"a": 1}, replace=True
    )

    assert exit_code == ExitCode.SUCCESS
    assert session.overwrite_calls == [{"a": 1}]
    assert record["data"]["updated_keys"] == ["a"]
    assert record["data"]["preferences"] == {"a": 1}


def test_preferences_update_reports_mismatch_without_dumping_full_object():
    session = FakeSession()
    executor = _executor(session)
    assert _action(executor, "preferences.open")[1] == ExitCode.SUCCESS

    def drop_write(_prefs):
        session.preferences = {"theme": "dark", "volume": 50}

    session.on_overwrite = drop_write

    record, exit_code = _action(executor, "preferences.update", values={"volume": 80})

    assert exit_code == ExitCode.ASSERTION_FAILED
    assert record["error"]["code"] == "PREFERENCES_NOT_CONFIRMED"
    assert record["data"]["mismatched_keys"] == ["volume"]
    assert record["data"]["diff"]["volume"] == {"expected": 80, "actual": 50}
    assert "theme" not in json.dumps(record["data"])

    read_record, read_exit = _action(executor, "preferences.read")
    assert read_exit == ExitCode.SUCCESS
    assert read_record["data"]["preferences"] == {"theme": "dark", "volume": 50}


@pytest.mark.parametrize("values", [None, "not-an-object", [], 3])
def test_preferences_update_requires_values_object(values):
    session = FakeSession()
    executor = _executor(session)
    params = {} if values is None else {"values": values}

    record, exit_code = executor.execute(
        {"action": "preferences.update", "params": params}
    )

    assert exit_code == ExitCode.INPUT_ERROR
    assert record["error"]["code"] == "INVALID_INPUT"
    assert session.overwrite_calls == []


def test_preferences_update_rejects_non_boolean_replace():
    session = FakeSession()
    executor = _executor(session)

    record, exit_code = _action(
        executor, "preferences.update", values={"a": 1}, replace="yes"
    )

    assert exit_code == ExitCode.INPUT_ERROR
    assert record["error"]["code"] == "INVALID_INPUT"
    assert session.overwrite_calls == []


def test_preferences_update_ack_rejection_keeps_snapshot():
    session = FakeSession()
    executor = _executor(session)
    assert _action(executor, "preferences.open")[1] == ExitCode.SUCCESS
    session.overwrite_result = {"ok": False, "error": "[BAD] rejected"}

    record, exit_code = _action(executor, "preferences.update", values={"volume": 80})

    assert exit_code == ExitCode.ASSERTION_FAILED
    assert record["error"]["code"] == "ACK_REJECTED"
    read_record, read_exit = _action(executor, "preferences.read")
    assert read_exit == ExitCode.SUCCESS
    assert read_record["data"]["preferences"] == {"theme": "dark", "volume": 50}


class FakeWsTransport:
    def __init__(self, *, ready=True):
        self._ready = threading.Event()
        if ready:
            self._ready.set()
        self.listener = None
        self.state_listener = None

    def set_agent_message_listener(self, listener, state_listener, system_listener=None):
        self.listener = listener
        self.state_listener = state_listener

    def wait_until_ready(self, timeout):
        return self._ready.wait(timeout)

    def is_ready(self):
        return self._ready.is_set()

    def stop(self):
        self._ready.clear()


class FakeNetworkClient:
    def __init__(self, *, ready=True):
        self.ws_transport = FakeWsTransport(ready=ready)
        self.get_calls = 0
        self.overwrite_calls = []

    def login(self, username, password, request_token=False):
        return True, "ok"

    def get_preferences(self):
        self.get_calls += 1
        return {"theme": "dark"}

    def overwrite_preferences(self, preferences):
        self.overwrite_calls.append(dict(preferences))
        return {"ok": True}


def test_facade_preferences_methods_delegate_and_require_ready():
    network = FakeNetworkClient(ready=True)
    session = HeadlessSession(base_url="http://test", network_client=network)
    session.connect("user", "pass")

    assert session.get_preferences() == {"theme": "dark"}
    session.overwrite_preferences({"theme": "light"})

    assert network.get_calls == 1
    assert network.overwrite_calls == [{"theme": "light"}]

    cold = HeadlessSession(
        base_url="http://test", network_client=FakeNetworkClient(ready=False)
    )
    with pytest.raises(SessionNotReadyError):
        cold.get_preferences()
