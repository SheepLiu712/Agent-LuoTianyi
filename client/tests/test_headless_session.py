import base64
import threading

import pytest

from src.network.event_types import AgentMessage
from src.session import (
    HeadlessSession,
    ReplyTimeoutError,
    SessionClosedError,
    SessionConnectionError,
    SessionNotReadyError,
    SessionReadyTimeout,
    SessionState,
)


class FakeWsTransport:
    def __init__(self, *, ready=True):
        self._ready_event = threading.Event()
        if ready:
            self._ready_event.set()
        self.listener = None
        self.state_listener = None
        self.system_listener = None
        self.stopped = False

    def set_agent_message_listener(
        self,
        listener,
        state_listener,
        system_listener=None,
        llm_request_listener=None,
    ):
        self.listener = listener
        self.state_listener = state_listener
        self.system_listener = system_listener

    def stop(self):
        self.stopped = True
        self._ready_event.clear()


class FakeNetworkClient:
    def __init__(self, *, ready=True, login_result=(True, "ok"), auto_login_result=True):
        self.ws_transport = FakeWsTransport(ready=ready)
        self.login_result = login_result
        self.auto_login_result = auto_login_result
        self.login_calls = []
        self.auto_login_calls = []
        self.sent = []

    def login(self, username, password, request_token=False):
        self.login_calls.append((username, password, request_token))
        return self.login_result

    def auto_login(self, username, token):
        self.auto_login_calls.append((username, token))
        return self.auto_login_result

    def send_chat(self, text, is_proactive=False, ack_timeout=10.0, client_msg_id=None):
        self.sent.append((text, is_proactive, ack_timeout, client_msg_id))
        return {"ok": True, "request_id": client_msg_id, "error": None}


def _message(
    *,
    uuid="reply-1",
    text="",
    expression=None,
    audio=None,
    final=False,
    audio_error=False,
    error_code=None,
    display_in_chat=True,
    is_ephemeral=False,
):
    return AgentMessage(
        uuid=uuid,
        text=text,
        expression=expression,
        audio=audio,
        is_final_package=final,
        reply_to=None,
        audio_error=audio_error,
        error_code=error_code,
        display_in_chat=display_in_chat,
        is_ephemeral=is_ephemeral,
    )


def test_connect_waits_for_ready_and_send_text_delegates_ack_contract(tmp_path):
    network = FakeNetworkClient()
    session = HeadlessSession(
        "http://localhost:60030",
        network_client=network,
        audio_output_dir=tmp_path,
    )

    session.connect("alice", "secret", timeout=0.1)
    ack = session.send_text("hello", client_msg_id="msg-1", ack_timeout=2.5)

    assert session.state == SessionState.READY
    assert network.login_calls == [("alice", "secret", False)]
    assert network.sent == [("hello", False, 2.5, "msg-1")]
    assert ack == {"ok": True, "request_id": "msg-1", "error": None}


def test_connect_reports_login_failure_and_ready_timeout_without_credentials(tmp_path):
    failed = HeadlessSession(
        "http://localhost:60030",
        network_client=FakeNetworkClient(login_result=(False, "invalid credentials")),
        audio_output_dir=tmp_path,
    )
    with pytest.raises(SessionConnectionError, match="invalid credentials"):
        failed.connect("alice", "secret", timeout=0.01)
    assert failed.state == SessionState.AUTH_FAILED

    not_ready = HeadlessSession(
        "http://localhost:60030",
        network_client=FakeNetworkClient(ready=False),
        audio_output_dir=tmp_path,
    )
    with pytest.raises(SessionReadyTimeout) as exc_info:
        not_ready.connect("alice", "do-not-leak", timeout=0.01)
    assert "do-not-leak" not in str(exc_info.value)
    assert not_ready.state == SessionState.DISCONNECTED


def test_connect_with_token_and_non_ready_send_behavior(tmp_path):
    network = FakeNetworkClient()
    session = HeadlessSession(
        "http://localhost:60030",
        network_client=network,
        audio_output_dir=tmp_path,
    )

    with pytest.raises(SessionNotReadyError):
        session.send_text("too early", client_msg_id="msg-early")

    session.connect_with_token("alice", "login-token", timeout=0.1)
    assert network.auto_login_calls == [("alice", "login-token")]
    assert session.state == SessionState.READY


def test_subscribers_observe_packets_and_completed_reply_with_audio_index(tmp_path):
    network = FakeNetworkClient()
    session = HeadlessSession(
        "http://localhost:60030",
        network_client=network,
        audio_output_dir=tmp_path,
    )
    observed = []
    unsubscribe = session.subscribe(observed.append)
    session.connect("alice", "secret", timeout=0.1)

    network.ws_transport.listener(
        _message(
            text="first",
            expression="smile",
            audio=base64.b64encode(b"audio-").decode("ascii"),
        )
    )
    network.ws_transport.listener(
        _message(
            text="second",
            expression="happy",
            audio=base64.b64encode(b"tail").decode("ascii"),
            final=True,
        )
    )

    reply = session.wait_for_reply("reply-1", timeout=0.1)
    assert reply.texts == ("first", "second")
    assert reply.expressions == ("smile", "happy")
    assert reply.complete is True
    assert reply.audio_path == str(tmp_path / "reply-1.wav")
    assert (tmp_path / "reply-1.wav").read_bytes() == b"audio-tail"
    assert session.audio_path_for("reply-1") == reply.audio_path
    assert [event.kind for event in observed].count("agent_message") == 2
    assert [event.kind for event in observed].count("reply_completed") == 1

    unsubscribe()
    network.ws_transport.state_listener("thinking")
    assert observed[-1].kind == "reply_completed"


@pytest.mark.parametrize(
    "message",
    [
        _message(
            text="kept",
            audio=base64.b64encode(b"partial").decode("ascii"),
            final=True,
            audio_error=True,
            error_code="TTS_STREAM_ERROR",
        ),
        _message(
            audio=base64.b64encode(b"ephemeral").decode("ascii"),
            final=True,
            display_in_chat=False,
            is_ephemeral=True,
        ),
    ],
)
def test_failed_or_ephemeral_audio_completes_without_audio_index(tmp_path, message):
    network = FakeNetworkClient()
    session = HeadlessSession(
        "http://localhost:60030",
        network_client=network,
        audio_output_dir=tmp_path,
    )
    session.connect("alice", "secret", timeout=0.1)

    network.ws_transport.listener(message)

    reply = session.wait_for_reply("reply-1", timeout=0.1)
    assert reply.complete is True
    assert reply.audio_path is None
    assert session.audio_path_for("reply-1") is None
    assert list(tmp_path.iterdir()) == []


def test_wait_timeout_and_close_wake_waiters(tmp_path):
    network = FakeNetworkClient()
    session = HeadlessSession(
        "http://localhost:60030",
        network_client=network,
        audio_output_dir=tmp_path,
    )
    session.connect("alice", "secret", timeout=0.1)

    with pytest.raises(ReplyTimeoutError):
        session.wait_for_reply("missing", timeout=0.01)

    session.close()
    session.close()
    assert session.state == SessionState.CLOSED
    assert network.ws_transport.stopped is True
    with pytest.raises(SessionClosedError):
        session.wait_for_reply("missing", timeout=0.1)
