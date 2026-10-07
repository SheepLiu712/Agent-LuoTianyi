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


def test_protocol_docs_and_driver_match_the_server_agent_states():
    """`agent_state` 取值必须以服务端枚举为真源，两份协议文档与驱动都不得漂移。

    服务端曾有一段时间只发射 `thinking`/`waiting`，而驱动硬等 `listening`（必然超时）；
    #252 起服务端开始发射 `listening`。状态的**发射时机**属于实现细节，这里断言的是三处
    **取值集合一致**：

    1. 服务端 `AgentPresentationState`（真源）；
    2. `server/docs` 与 `client/docs` 两份协议副本的 §5.5「当前可能值」；
    3. 驱动 `wait_for_event(..., value=...)` 里等待的取值 ⊆ 真源（不得等待服务端无法发射的状态）。
    """
    import re
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    enum_path = repo_root / "server" / "src" / "domain" / "stage" / "output.py"
    docs = (
        repo_root / "server" / "docs" / "dev" / "统一事件协议.md",
        repo_root / "client" / "docs" / "dev" / "统一事件协议.md",
    )
    driver_path = repo_root / "cli-client" / "tests" / "manual_e2e" / "22-voice-message.driver.py"
    if not enum_path.exists() or not docs[0].exists():
        pytest.skip("server sources are not available alongside cli-client")

    enum_source = enum_path.read_text(encoding="utf-8")
    server_states = set(re.findall(r'^\s+[A-Z_]+ = "([a-z_]+)"$', enum_source, flags=re.MULTILINE))
    assert server_states, "AgentPresentationState must declare its values"

    for doc in docs:
        source = doc.read_text(encoding="utf-8")
        # ① 序列图里的简写：不带省略号时必须列出**全部**取值（带省略号时只能是子集）。
        shorthand = re.search(r"agent_state_changed \(([^)]*)\)", source)
        assert shorthand, f"{doc.name} must summarize agent_state_changed values"
        listed = {value.strip().strip("`") for value in shorthand.group(1).split("/") if value.strip("` ")}
        has_ellipsis = "..." in shorthand.group(1)
        assert listed <= server_states or has_ellipsis, (
            f"{doc.name} lists states the server cannot emit: {listed - server_states}"
        )
        if not has_ellipsis:
            assert listed == server_states, f"{doc.name} shorthand drifted from the enum: {listed ^ server_states}"

        # ② §5.5「当前可能值」必须与枚举完全一致。
        section = source.split("### 5.5 agent_state_changed", 1)[1].split("### 5.6", 1)[0]
        assert "当前可能值" in section, f"{doc.name} §5.5 must list the current agent_state values"
        possible = section.split("当前可能值", 1)[1]
        doc_states = set(re.findall(r"^\d+\.\s*`([a-z_]+)`", possible, flags=re.MULTILINE))
        assert doc_states == server_states, (
            f"{doc.name} drifted from AgentPresentationState: {doc_states ^ server_states}"
        )

    driver_source = driver_path.read_text(encoding="utf-8")
    gated = set(re.findall(r'wait_for_event\(\s*"agent_state"[^)]*?value="([^"]+)"', driver_source))
    assert gated <= server_states, f"driver gates on states the server cannot emit: {gated - server_states}"
