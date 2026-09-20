import threading

import pytest

from src.cli.actions import ActionExecutor, ExitCode
from src.network.event_types import (
    WSEventType,
    WSMessage,
    normalize_agent_message,
)
from src.session import HeadlessSession, SessionState


class FakeSession:
    def __init__(self, *, audio_active=False):
        self.state = SessionState.READY
        self.is_server_audio_active = audio_active
        self.send_ack = {"ok": True, "request_id": "c-1", "error": None}
        self.send_calls = []

    def send_touch(
        self,
        touch_area,
        click_frequency=None,
        touch_meta=None,
        *,
        client_msg_id=None,
        ack_timeout=10.0,
    ):
        self.send_calls.append(
            {
                "touch_area": touch_area,
                "click_frequency": click_frequency,
                "touch_meta": touch_meta,
                "client_msg_id": client_msg_id,
                "ack_timeout": ack_timeout,
            }
        )
        return dict(self.send_ack)

    def close(self):
        self.state = SessionState.CLOSED


def _executor(session):
    executor = ActionExecutor(
        session_factory=lambda **_kwargs: session,
        session_id="session-touch",
    )
    executor._session = session
    return executor


def _touch(executor, **params):
    return executor.execute({"action": "touch.send", "params": params})


def test_touch_send_passes_ack_and_correlation():
    session = FakeSession()
    executor = _executor(session)

    record, exit_code = _touch(
        executor,
        touch_area=["head"],
        click_frequency={"count_10s": 2},
        touch_meta={"source": "cli"},
    )

    assert exit_code == ExitCode.SUCCESS
    assert record["status"] == "passed"
    assert record["data"]["ack"] is True
    assert len(session.send_calls) == 1
    call = session.send_calls[0]
    assert call["touch_area"] == ["head"]
    assert call["click_frequency"] == {"count_10s": 2}
    assert call["touch_meta"] == {"source": "cli"}
    assert call["client_msg_id"] == record["correlation_id"]
    assert call["client_msg_id"]


def test_touch_send_suppressed_during_server_audio_without_sending():
    session = FakeSession(audio_active=True)
    executor = _executor(session)

    record, exit_code = _touch(executor, touch_area="head")

    assert exit_code == ExitCode.SUCCESS
    assert record["status"] == "suppressed"
    assert record["data"] == {"suppressed": True, "reason": "server_audio_active"}
    assert session.send_calls == []


def test_touch_send_ack_rejection_is_reported():
    session = FakeSession()
    session.send_ack = {"ok": False, "error": "[BAD_MESSAGE] rejected"}
    executor = _executor(session)

    record, exit_code = _touch(executor, touch_area="head")

    assert exit_code == ExitCode.ASSERTION_FAILED
    assert record["error"]["code"] == "ACK_REJECTED"
    assert len(session.send_calls) == 1


@pytest.mark.parametrize("touch_area", [None, "", "   ", [], [1], [""]])
def test_touch_send_rejects_invalid_touch_area(touch_area):
    session = FakeSession()
    executor = _executor(session)
    params = {} if touch_area is None else {"touch_area": touch_area}

    record, exit_code = executor.execute({"action": "touch.send", "params": params})

    assert exit_code == ExitCode.INPUT_ERROR
    assert record["error"]["code"] == "INVALID_INPUT"
    assert session.send_calls == []


@pytest.mark.parametrize("field", ["click_frequency", "touch_meta"])
def test_touch_send_rejects_invalid_metadata_types(field):
    session = FakeSession()
    executor = _executor(session)

    record, exit_code = executor.execute(
        {"action": "touch.send", "params": {"touch_area": "head", field: "not-an-object"}}
    )

    assert exit_code == ExitCode.INPUT_ERROR
    assert record["error"]["code"] == "INVALID_INPUT"
    assert session.send_calls == []


class FakeWsTransport:
    def __init__(self, *, ready=True):
        self._ready = threading.Event()
        if ready:
            self._ready.set()
        self.listener = None
        self.state_listener = None
        self.stopped = False

    def set_agent_message_listener(self, listener, state_listener, system_listener=None):
        self.listener = listener
        self.state_listener = state_listener

    def wait_until_ready(self, timeout):
        return self._ready.wait(timeout)

    def is_ready(self):
        return self._ready.is_set()

    def stop(self):
        self.stopped = True
        self._ready.clear()


class FakeNetworkClient:
    def __init__(self, *, ready=True):
        self.ws_transport = FakeWsTransport(ready=ready)
        self.touch_calls = []

    def login(self, username, password, request_token=False):
        return True, "ok"

    def send_touch(
        self,
        touch_area,
        click_frequency=None,
        touch_meta=None,
        ack_timeout=10.0,
        client_msg_id=None,
    ):
        self.touch_calls.append(
            {
                "touch_area": touch_area,
                "click_frequency": click_frequency,
                "touch_meta": touch_meta,
                "ack_timeout": ack_timeout,
                "client_msg_id": client_msg_id,
            }
        )
        return {"ok": True, "request_id": client_msg_id, "error": None}


def _agent_message(*, uuid="r1", audio="", is_final_package=False):
    return normalize_agent_message(
        WSMessage(
            event_type=WSEventType.AGENT_MESSAGE,
            payload={
                "uuid": uuid,
                "text": "",
                "audio": audio,
                "is_final_package": is_final_package,
            },
        )
    )


def test_facade_send_touch_delegates_to_network_client():
    network = FakeNetworkClient(ready=True)
    session = HeadlessSession(base_url="http://test", network_client=network)
    session.connect("user", "pass")

    ack = session.send_touch(
        "head",
        click_frequency={"count_10s": 1},
        touch_meta={"a": 1},
        client_msg_id="c-9",
        ack_timeout=3.0,
    )

    assert ack == {"ok": True, "request_id": "c-9", "error": None}
    assert network.touch_calls == [
        {
            "touch_area": "head",
            "click_frequency": {"count_10s": 1},
            "touch_meta": {"a": 1},
            "ack_timeout": 3.0,
            "client_msg_id": "c-9",
        }
    ]


def test_facade_server_audio_active_lifecycle():
    network = FakeNetworkClient(ready=True)
    session = HeadlessSession(base_url="http://test", network_client=network)
    session.connect("user", "pass")
    listener = network.ws_transport.listener
    assert listener is not None

    assert session.is_server_audio_active is False

    listener(_agent_message(uuid="r1", audio="QUJD"))
    assert session.is_server_audio_active is True

    listener(_agent_message(uuid="r1", is_final_package=True))
    assert session.is_server_audio_active is False
