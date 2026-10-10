import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.adapter.websocket.call_v1 import (
    BinaryAudioFrameCodec,
    CallAcceptanceReceipt,
    CallTransportHub,
    CallTransportSession,
    InboundCallFrame,
    WireAudioFrame,
)
from src.web.websocket import call_endpoint

CALL_ID = "606ec5e6-a330-4e6c-b07a-8432a5716c8f"


class Sink:
    def __init__(self) -> None:
        self.frames: list[InboundCallFrame] = []

    async def accept(self, frame: InboundCallFrame, receipt: CallAcceptanceReceipt) -> bool:
        del receipt
        self.frames.append(frame)
        return True


class CredentialService:
    @staticmethod
    def check_message_token(username, token):
        return (username == "alice" and token == "valid-token", "user-1")


def runtime(*, available: bool):
    from src.web.websocket import WebSocketService

    hub = CallTransportHub()
    sink = Sink()
    session = CallTransportSession(
        call_id=CALL_ID,
        user_id="user-1",
        character_id="luotianyi",
        sink=sink,
    )
    hub.register(session)
    return (
        SimpleNamespace(
            websocket_service=WebSocketService(),
            database_manager=SimpleNamespace(credential_service=CredentialService()),
            call_transport_available=available,
            call_transport_hub=hub,
        ),
        session,
        sink,
    )


def enabled_test_runtime():
    """Isolated test factory; production ServerRuntime never exposes this enable path."""
    return runtime(available=True)


def app_for(monkeypatch, configured_runtime):
    app = FastAPI()
    app.include_router(call_endpoint.router)
    monkeypatch.setattr(
        call_endpoint,
        "get_admin_shell",
        lambda: SimpleNamespace(runtime_supervisor=SimpleNamespace(runtime=configured_runtime)),
    )
    return app


def auth(websocket):
    assert websocket.receive_json()["type"] == "system_ready"
    websocket.send_json(
        {
            "type": "user_auth",
            "client_msg_id": "auth-1",
            "payload": {"username": "alice", "token": "valid-token"},
        }
    )
    assert websocket.receive_json()["type"] == "auth_ok"


def resume(websocket, cursor=0):
    websocket.send_text(
        json.dumps(
            {
                "protocol": "call.v1",
                "type": "call.resume",
                "call_id": CALL_ID,
                "character_id": "luotianyi",
                "last_contiguous_server_seq": cursor,
            },
            separators=(",", ":"),
        )
    )
    return json.loads(websocket.receive_text())


def test_call_endpoint_is_unavailable_by_default(monkeypatch):
    configured_runtime, _, _ = runtime(available=False)

    with TestClient(app_for(monkeypatch, configured_runtime)) as client:
        try:
            with client.websocket_connect("/call_ws") as websocket:
                websocket.receive_text()
        except Exception as error:
            assert getattr(error, "code", None) == 1013


def test_call_endpoint_rejects_call_start_without_consuming_business_state(monkeypatch):
    configured_runtime, _, sink = enabled_test_runtime()

    with TestClient(app_for(monkeypatch, configured_runtime)) as client:
        try:
            with client.websocket_connect("/call_ws") as websocket:
                auth(websocket)
                websocket.send_text(
                    json.dumps(
                        {
                            "protocol": "call.v1",
                            "type": "call.start",
                            "seq": 1,
                            "client_request_id": "request-1",
                            "character_id": "luotianyi",
                            "audio": {"encoding": "pcm_s16le", "sample_rate": 16000, "channels": 1},
                        },
                        separators=(",", ":"),
                    )
                )
                websocket.receive_text()
        except Exception as error:
            assert getattr(error, "code", None) == 1013

    assert sink.frames == []


def test_real_websocket_auth_mixed_frames_gap_nack_and_duplicate(monkeypatch):
    configured_runtime, _, sink = enabled_test_runtime()

    with (
        TestClient(app_for(monkeypatch, configured_runtime)) as client,
        client.websocket_connect("/call_ws") as websocket,
    ):
        auth(websocket)
        assert resume(websocket)["type"] == "call.resumed"
        websocket.send_bytes(bytes.fromhex("0102000000000000000002000000020001"))
        assert json.loads(websocket.receive_text())["missing_seq"] == 1
        seq_one = json.dumps(
            {"protocol": "call.v1", "type": "call.hangup", "seq": 1, "call_id": CALL_ID, "reason": "user_hangup"},
            separators=(",", ":"),
        )
        websocket.send_text(seq_one)
        assert json.loads(websocket.receive_text())["ack_seq"] == 2
        websocket.send_text(seq_one)
        assert json.loads(websocket.receive_text())["ack_seq"] == 2

    assert [frame.seq for frame in sink.frames] == [1, 2]


def test_real_websocket_same_seq_conflict_uses_protocol_close(monkeypatch):
    configured_runtime, _, _ = enabled_test_runtime()

    with TestClient(app_for(monkeypatch, configured_runtime)) as client:
        try:
            with client.websocket_connect("/call_ws") as websocket:
                auth(websocket)
                resume(websocket)
                websocket.send_text(
                    json.dumps(
                        {
                            "protocol": "call.v1",
                            "type": "call.hangup",
                            "seq": 1,
                            "call_id": CALL_ID,
                            "reason": "user_hangup",
                        },
                        separators=(",", ":"),
                    )
                )
                websocket.receive_text()
                websocket.send_text(
                    json.dumps(
                        {
                            "protocol": "call.v1",
                            "type": "call.hangup",
                            "seq": 1,
                            "call_id": CALL_ID,
                            "reason": "backgrounded",
                        },
                        separators=(",", ":"),
                    )
                )
                websocket.receive_text()
        except Exception as error:
            assert getattr(error, "code", None) == 1002


def test_real_websocket_rejects_second_active_connection_then_allows_resume(monkeypatch):
    configured_runtime, session, _ = enabled_test_runtime()

    with TestClient(app_for(monkeypatch, configured_runtime)) as client:
        with client.websocket_connect("/call_ws") as first:
            auth(first)
            assert resume(first)["type"] == "call.resumed"
            initial_cursor = session.client_cursor
            try:
                with client.websocket_connect("/call_ws") as second:
                    auth(second)
                    resume(second)
            except Exception as error:
                assert getattr(error, "code", None) == 1008
            assert session.client_cursor == initial_cursor
        with client.websocket_connect("/call_ws") as replacement:
            auth(replacement)
            assert resume(replacement)["type"] == "call.resumed"


def test_real_websocket_resume_replays_original_text_and_binary(monkeypatch):
    configured_runtime, session, _ = enabled_test_runtime()
    state = session.send_control(
        {
            "protocol": "call.v1",
            "type": "call.state",
            "seq": 1,
            "call_id": CALL_ID,
            "client_request_id": "request-1",
            "state": "preparing",
        }
    )
    started = session.send_control(
        {
            "protocol": "call.v1",
            "type": "audio.stream_started",
            "seq": 2,
            "call_id": CALL_ID,
            "audio_route": "CALL",
            "stream_id": 1,
            "response_id": "response-1",
            "encoding": "pcm_s16le",
            "sample_rate": 24000,
            "channels": 1,
        }
    )
    pcm = session.send_audio(WireAudioFrame(1, 2, 1, 1, 3, b"\x00\x01"))

    with (
        TestClient(app_for(monkeypatch, configured_runtime)) as client,
        client.websocket_connect("/call_ws") as websocket,
    ):
        auth(websocket)
        assert resume(websocket)["type"] == "call.resumed"
        assert websocket.receive_text() == state.text
        assert websocket.receive_text() == started.text
        assert (
            websocket.receive_bytes()
            == pcm.binary
            == BinaryAudioFrameCodec().encode(WireAudioFrame(1, 2, 1, 1, 3, b"\x00\x01"))
        )


def test_real_websocket_nack_replays_retirement_control_not_audio(monkeypatch):
    configured_runtime, session, _ = enabled_test_runtime()
    session.send_control(
        {
            "protocol": "call.v1",
            "type": "audio.stream_started",
            "seq": 1,
            "call_id": CALL_ID,
            "audio_route": "CALL",
            "stream_id": 1,
            "response_id": "response-1",
            "encoding": "pcm_s16le",
            "sample_rate": 24000,
            "channels": 1,
        }
    )
    session.send_audio(WireAudioFrame(1, 2, 0, 1, 2, b"\x00\x01"))
    session.send_control(
        {
            "protocol": "call.v1",
            "type": "playback.stop",
            "seq": 3,
            "call_id": CALL_ID,
            "response_id": "response-1",
            "stream_id": 1,
            "retire_server_seq": {"from": 1, "through": 2},
            "reason": "user_interrupted",
        }
    )

    with (
        TestClient(app_for(monkeypatch, configured_runtime)) as client,
        client.websocket_connect("/call_ws") as websocket,
    ):
        auth(websocket)
        assert resume(websocket)["type"] == "call.resumed"
        assert json.loads(websocket.receive_text())["type"] == "playback.stop"
        websocket.send_text(
            json.dumps(
                {"protocol": "call.v1", "type": "nack", "call_id": CALL_ID, "missing_seq": 2},
                separators=(",", ":"),
            )
        )
        assert json.loads(websocket.receive_text())["type"] == "playback.stop"


def test_hub_rejects_second_active_connection_and_allows_resume_after_detach():
    _, session, _ = enabled_test_runtime()
    hub = CallTransportHub()
    hub.register(session)
    raw = json.dumps(
        {
            "protocol": "call.v1",
            "type": "call.resume",
            "call_id": CALL_ID,
            "character_id": "luotianyi",
            "last_contiguous_server_seq": 0,
        },
        separators=(",", ":"),
    )

    import asyncio

    async def scenario():
        first = await hub.attach_resume(raw, user_id="user-1", connection_id=object())
        try:
            await hub.attach_resume(raw, user_id="user-1", connection_id=object())
            raise AssertionError("second active connection was accepted")
        except Exception as error:
            assert getattr(error, "code", None) == "CALL_CONNECTION_ACTIVE"
        assert await hub.detach(first) is True
        second = await hub.attach_resume(raw, user_id="user-1", connection_id=object())
        assert second.generation == first.generation + 1
        before = session.server_ack_cursor
        try:
            hub.acknowledge_bound(first, before)
            raise AssertionError("stale binding changed ACK state")
        except Exception as error:
            assert getattr(error, "code", None) == "STALE_CALL_CONNECTION"
        assert session.server_ack_cursor == before
        assert await hub.detach(first) is False
        assert hub.is_current(second)

    asyncio.run(scenario())


def test_hub_unregister_requires_expected_session_and_closes_registered_state():
    _, session, _ = enabled_test_runtime()
    hub = CallTransportHub()
    hub.register(session)
    other = CallTransportSession(
        call_id=CALL_ID,
        user_id="user-1",
        character_id="luotianyi",
        sink=Sink(),
    )

    import asyncio

    async def scenario():
        assert await hub.unregister(CALL_ID, expected_session=other) is False
        assert await hub.unregister(CALL_ID, expected_session=session) is True
        try:
            session.replay_after(0)
            raise AssertionError("unregistered session remained open")
        except Exception as error:
            assert getattr(error, "code", None) == "TRANSPORT_CLOSED"

    asyncio.run(scenario())
