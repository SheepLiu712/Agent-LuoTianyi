import hashlib

import pytest
from test_headless_session import FakeNetworkClient

from cli_client.network.network_client import NetworkClient
from cli_client.network.ws_transport import WsTransport, normalize_server_ack
from cli_client.session import HeadlessSession, SessionState, SessionVoiceError
from cli_client.types import ConversationItem


class VoiceTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def submit_user_voice(self, phase, upload_id, **kwargs):
        self.calls.append((phase, upload_id, kwargs))
        return self.responses.pop(0)

    def submit_voice_recording_started(self, recording_id, ack_timeout=5.0):
        self.calls.append(("recording_started", recording_id, {"ack_timeout": ack_timeout}))
        return self.responses.pop(0)


def _ready_session(tmp_path, responses):
    network = FakeNetworkClient()
    transport = VoiceTransport(responses)
    network.download_audio = lambda _uuid: b"voice-bytes"
    session = HeadlessSession("http://localhost:60030", network_client=network, audio_output_dir=tmp_path)
    network.ws_transport = transport
    session._transport = transport
    session._state = SessionState.READY
    transport.is_ready = lambda: True
    return session, network, transport


def test_ws_transport_builds_all_voice_protocol_phases():
    transport = WsTransport("http://localhost", lambda: "user", lambda: "token")
    submitted = []
    transport._submit_user_event = lambda event_type, payload, ack_timeout, client_msg_id: submitted.append(
        (event_type.value, payload, client_msg_id)
    ) or {"ok": True}

    transport.submit_user_voice("begin", "upload-1", byte_length=3, total_chunks=1)
    transport.submit_user_voice("chunk", "upload-1", chunk_index=0, audio_chunk=b"abc")
    transport.submit_user_voice("finalize", "upload-1")
    transport.submit_user_voice("abort", "upload-1")
    transport.submit_voice_recording_started("upload-1")
    transport.submit_voice_recording_cancelled("upload-1")

    assert [call[2] for call in submitted] == [
        "upload-1:begin",
        "upload-1:chunk:0",
        "upload-1:finalize",
        "upload-1:abort",
        "upload-1:recording_started",
        "upload-1:recording_cancelled",
    ]
    assert submitted[1][1]["audio_base64"] == "YWJj"


def test_voice_finalize_ack_metadata_and_nack_are_normalized():
    assert normalize_server_ack(
        {"ok": True, "message_uuid": "message-1", "duration_ms": 900}
    ) == {"ok": True, "error": None, "message_uuid": "message-1", "duration_ms": 900}
    nack = normalize_server_ack(
        {"ok": False, "code": "VOICE_MISSING_CHUNKS", "message": "missing", "retryable": True}
    )
    assert nack["code"] == "VOICE_MISSING_CHUNKS"
    assert nack["retryable"] is True
    assert nack["drop"] is False


def test_ws_transport_rejects_oversized_voice_chunk():
    transport = WsTransport("http://localhost", lambda: "user", lambda: "token")
    with pytest.raises(ValueError, match="48 KiB"):
        transport.submit_user_voice("chunk", "upload-1", chunk_index=0, audio_chunk=b"x" * (48 * 1024 + 1))


def test_send_voice_success_and_chunk_bounds(tmp_path):
    source = tmp_path / "voice.m4a"
    source.write_bytes(b"a" * (48 * 1024 + 1))
    session, _, transport = _ready_session(
        tmp_path,
        [
            {"ok": True},
            {"ok": True},
            {"ok": True},
            {"ok": True},
            {"ok": True, "message_uuid": "message-1", "duration_ms": 1250},
        ],
    )

    result = session.send_voice(source, upload_id="upload-1")

    assert result == {"message_uuid": "message-1", "duration_ms": 1250}
    assert [call[0] for call in transport.calls] == ["recording_started", "begin", "chunk", "chunk", "finalize"]
    assert transport.calls[1][2]["total_chunks"] == 2
    assert all(len(call[2]["audio_chunk"]) <= 48 * 1024 for call in transport.calls[2:4])


def test_send_voice_retries_transient_ack_and_resends_after_missing_chunks(tmp_path):
    source = tmp_path / "voice.m4a"
    source.write_bytes(b"voice")
    session, _, transport = _ready_session(
        tmp_path,
        [
            {"ok": True},
            {"ok": False, "retryable": True, "error": "timeout"},
            {"ok": True},
            {"ok": True},
            {"ok": False, "retryable": True, "code": "VOICE_MISSING_CHUNKS"},
            {"ok": True},
            {"ok": True, "message_uuid": "message-1", "duration_ms": 900},
        ],
    )

    result = session.send_voice(source, upload_id="upload-1")

    assert result["message_uuid"] == "message-1"
    assert [call[0] for call in transport.calls] == [
        "recording_started",
        "begin",
        "begin",
        "chunk",
        "finalize",
        "chunk",
        "finalize",
    ]


def test_send_voice_raises_on_permanent_nack_and_aborts(tmp_path):
    source = tmp_path / "voice.m4a"
    source.write_bytes(b"voice")
    session, _, transport = _ready_session(
        tmp_path,
        [
            {"ok": True},
            {"ok": True},
            {"ok": False, "retryable": False, "error": "conflict"},
            {"ok": True},
        ],
    )

    with pytest.raises(SessionVoiceError, match="conflict"):
        session.send_voice(source, upload_id="upload-1")

    assert [call[0] for call in transport.calls] == ["recording_started", "begin", "chunk", "abort"]


def test_history_metadata_and_download_sha256_helpers(tmp_path):
    source = tmp_path / "voice.m4a"
    source.write_bytes(b"voice-bytes")
    session, network, _ = _ready_session(tmp_path, [])
    network.get_history = lambda count, end_index: (
        [
            ConversationItem(
                timestamp="2026-01-01 00:00:00",
                source="user",
                type="audio",
                content="[语音消息]",
                uuid="message-1",
                duration_ms=900,
                audio_available=True,
            )
        ],
        0,
    )

    item = session.assert_voice_in_history("message-1", 900)
    digest = session.assert_download_sha256("message-1", source)

    assert item.audio_available is True
    assert digest == hashlib.sha256(b"voice-bytes").hexdigest()


def test_network_audio_download_uses_bearer_token():
    client = NetworkClient("http://localhost")
    client.user_id = "alice"
    client.message_token = "secret-token"

    class Response:
        status_code = 200
        content = b"downloaded"

    calls = []
    client.session.get = lambda url, **kwargs: calls.append((url, kwargs)) or Response()

    assert client.download_audio("message-1") == b"downloaded"
    assert calls[0][0].endswith("/media/audio/message-1")
    assert calls[0][1]["headers"] == {"Authorization": "Bearer secret-token"}
