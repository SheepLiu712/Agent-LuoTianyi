import threading
import time

import pytest

from src.cli.actions import ActionExecutor, ExitCode
from src.network.event_types import WSEventType, WSMessage, normalize_agent_message
from src.session import (
    AggregatedReply,
    HeadlessSession,
    ReplyTimeoutError,
    SessionClosedError,
    SessionState,
)


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

    def login(self, username, password, request_token=False):
        return True, "ok"


def _message(*, uuid="r1", text="hello", is_final_package=True):
    return normalize_agent_message(
        WSMessage(
            event_type=WSEventType.AGENT_MESSAGE,
            payload={
                "uuid": uuid,
                "text": text,
                "audio": "",
                "is_final_package": is_final_package,
            },
        )
    )


def _connected_session():
    network = FakeNetworkClient(ready=True)
    session = HeadlessSession(base_url="http://test", network_client=network)
    session.connect("user", "pass")
    return session, network


def test_wait_for_next_reply_excludes_earlier_completions():
    session, network = _connected_session()
    listener = network.ws_transport.listener
    listener(_message(uuid="old", text="old reply"))

    result = {}
    errors = []

    def waiter():
        try:
            result["reply"] = session.wait_for_next_reply(timeout=5.0)
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    thread = threading.Thread(target=waiter)
    thread.start()
    time.sleep(0.3)
    listener(_message(uuid="new", text="new reply"))
    thread.join(timeout=5.0)

    assert errors == []
    assert result["reply"].uuid == "new"
    assert result["reply"].texts == ("new reply",)


def test_wait_for_next_reply_times_out_without_new_completion():
    session, network = _connected_session()
    network.ws_transport.listener(_message(uuid="old", text="old reply"))

    with pytest.raises(ReplyTimeoutError):
        session.wait_for_next_reply(timeout=0.1)


def test_wait_for_next_reply_after_close_raises_closed_error():
    session, _network = _connected_session()
    session.close()

    with pytest.raises(SessionClosedError):
        session.wait_for_next_reply(timeout=0.1)


class FakeReplySession:
    def __init__(self):
        self.state = SessionState.READY
        self.reply = AggregatedReply(
            uuid="reply-next",
            texts=("hi there",),
            expressions=("smile",),
            complete=True,
            audio_path=None,
            audio_error=False,
            error_code=None,
            display_in_chat=True,
            is_ephemeral=False,
        )
        self.explicit_calls = []
        self.next_calls = []
        self.next_error = None

    def wait_for_reply(self, reply_uuid, timeout):
        self.explicit_calls.append((reply_uuid, timeout))
        return self.reply

    def wait_for_next_reply(self, timeout):
        self.next_calls.append(timeout)
        if self.next_error is not None:
            raise self.next_error
        return self.reply

    def close(self):
        self.state = SessionState.CLOSED


def _executor(session):
    executor = ActionExecutor(
        session_factory=lambda **_kwargs: session, session_id="session-next"
    )
    executor._session = session
    return executor


def test_reply_wait_without_uuid_waits_for_next_reply():
    session = FakeReplySession()
    executor = _executor(session)

    record, exit_code = executor.execute(
        {"action": "reply.wait", "params": {"timeout": 7, "non_empty": True}}
    )

    assert exit_code == ExitCode.SUCCESS
    assert session.next_calls == [7.0]
    assert session.explicit_calls == []
    assert record["data"]["reply_uuid"] == "reply-next"
    assert record["data"]["text"] == "hi there"
    assert record["correlation_id"] == "reply-next"


def test_reply_wait_with_uuid_keeps_explicit_semantics():
    session = FakeReplySession()
    executor = _executor(session)

    record, exit_code = executor.execute(
        {"action": "reply.wait", "params": {"reply_uuid": "r-x", "timeout": 3}}
    )

    assert exit_code == ExitCode.SUCCESS
    assert session.explicit_calls == [("r-x", 3.0)]
    assert session.next_calls == []
    assert record["data"]["reply_uuid"] == "reply-next"


def test_reply_wait_next_timeout_maps_to_timeout_exit_code():
    session = FakeReplySession()
    session.next_error = ReplyTimeoutError("no new reply")
    executor = _executor(session)

    record, exit_code = executor.execute(
        {"action": "reply.wait", "params": {"timeout": 1}}
    )

    assert exit_code == ExitCode.TIMEOUT
    assert record["status"] == "timed_out"
    assert record["error"]["code"] == "TIMEOUT"
