import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.adapter.websocket.call_v1 import (
    BinaryAudioFrameCodec,
    CallAcceptanceReceipt,
    CallStageBinding,
    CallTransportHub,
    CallTransportSession,
    CallWireOutput,
    InboundCallFrame,
    WireAudioFrame,
)
from src.server_runtime import CallCapabilityStatus
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
            call_capability=CallCapabilityStatus(*(available for _ in range(8)), ("luotianyi",) if available else ()),
            supports_call_character=lambda character_id: available and character_id == "luotianyi",
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


def test_call_endpoint_rejects_non_ready_character_before_claim(monkeypatch):
    configured_runtime, _, sink = enabled_test_runtime()
    configured_runtime.stage_manager = object()
    configured_runtime.realtime_speech_factory = object()
    configured_runtime.call_settlement_coordinator = object()

    with TestClient(app_for(monkeypatch, configured_runtime)) as client:
        with client.websocket_connect("/call_ws") as websocket:
            auth(websocket)
            websocket.send_text(
                json.dumps(
                    {
                        "protocol": "call.v1",
                        "type": "call.start",
                        "seq": 1,
                        "client_request_id": "request-other",
                        "character_id": "other",
                        "audio": {"encoding": "pcm_s16le", "sample_rate": 16000, "channels": 1},
                    },
                    separators=(",", ":"),
                )
            )
            error = json.loads(websocket.receive_text())
            assert error["code"] == "CALL_CHARACTER_UNAVAILABLE"

    assert sink.frames == []


@pytest.mark.asyncio
async def test_preparing_send_failure_always_fails_claim_and_unregisters_without_masking_original():
    call_id = CALL_ID

    class Manager:
        def __init__(self):
            self.failed = []

        async def fail_pending_call_claim(self, claim, error):
            self.failed.append((claim, error))
            return True

    class Bridge:
        terminal_delivered = asyncio.Event()

        async def send_failed(self, _reason):
            raise RuntimeError("SOCKET_CLOSED")

    class WebSocket:
        async def send_text(self, _text):
            raise RuntimeError("DRAIN_CLOSED")

    hub = CallTransportHub()
    bridge = Bridge()
    session = CallTransportSession(
        call_id=call_id,
        user_id="user-1",
        character_id="luotianyi",
        sink=Sink(),
    )
    hub.register(session)
    binding = await hub.attach_start(session, user_id="user-1", connection_id=object())
    outputs = asyncio.Queue()
    outputs.put_nowait(SimpleNamespace(text="{}", binary=None))
    manager = Manager()
    claim = SimpleNamespace(record=SimpleNamespace(call_id=call_id))
    original = RuntimeError("PREPARING_SEND_FAILED")

    await call_endpoint._cleanup_failed_start(
        websocket=WebSocket(),
        runtime=SimpleNamespace(call_transport_hub=hub),
        stage_manager=manager,
        claim=claim,
        bridge=bridge,
        session=session,
        binding=binding,
        outputs=outputs,
        create_started=False,
        original_error=original,
    )

    assert manager.failed == [(claim, original)]
    assert hub.session_for(call_id) is None
    assert outputs.empty()


@pytest.mark.asyncio
async def test_release_observer_never_expires_active_stage_then_unregisters_after_close():
    hub = CallTransportHub()
    transport = CallTransportSession(
        call_id=CALL_ID,
        user_id="user-1",
        character_id="luotianyi",
        sink=Sink(),
    )
    hub.register(transport)
    closed = asyncio.Event()
    terminal = asyncio.Event()
    outputs = asyncio.Queue()

    class Stage:
        async def wait_closed(self):
            await closed.wait()

    bridge = CallStageBinding(call_id=CALL_ID, deliver=lambda _output: None)
    bridge._terminal_delivered = terminal
    transport._sink = bridge
    observer = hub.own_task(
        call_endpoint._release_terminal_session(hub, transport, Stage(), outputs),
        name="call-transport-release",
    )

    await asyncio.sleep(0.05)
    assert hub.session_for(CALL_ID) is transport
    assert not observer.done()
    closed.set()
    terminal.set()
    await observer
    assert hub.session_for(CALL_ID) is None


@pytest.mark.asyncio
async def test_release_observer_terminal_timeout_is_bounded_and_unregisters(monkeypatch):
    hub = CallTransportHub()
    transport = CallTransportSession(
        call_id=CALL_ID,
        user_id="user-1",
        character_id="luotianyi",
        sink=Sink(),
    )
    hub.register(transport)

    class Stage:
        async def wait_closed(self):
            return None

    terminal = asyncio.Event()
    bridge = CallStageBinding(call_id=CALL_ID, deliver=lambda _output: None)
    bridge._terminal_delivered = terminal
    transport._sink = bridge
    real_wait_for = asyncio.wait_for

    async def short_wait_for(operation, timeout):
        return await real_wait_for(operation, timeout=0.01 if timeout == 2.0 else timeout)

    monkeypatch.setattr(call_endpoint.asyncio, "wait_for", short_wait_for)
    await call_endpoint._release_terminal_session(hub, transport, Stage(), asyncio.Queue())
    assert hub.session_for(CALL_ID) is None


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


@pytest.mark.parametrize("failure", ["cursor", "send"])
def test_failed_resume_handshake_releases_owner_for_correct_retry(monkeypatch, failure):
    from starlette.websockets import WebSocketDisconnect

    configured_runtime, _, _ = enabled_test_runtime()
    configured_runtime.call_transport_hub._resume_release_wait_seconds = 0.01
    original_send = call_endpoint._send_bound_outputs
    fail_send = failure == "send"

    async def send_once_failed(*args, **kwargs):
        nonlocal fail_send
        if fail_send:
            fail_send = False
            raise RuntimeError("injected handshake send failure")
        return await original_send(*args, **kwargs)

    monkeypatch.setattr(call_endpoint, "_send_bound_outputs", send_once_failed)
    with TestClient(app_for(monkeypatch, configured_runtime)) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/call_ws") as websocket:
                auth(websocket)
                resume(websocket, 1 if failure == "cursor" else 0)
        with client.websocket_connect("/call_ws") as websocket:
            auth(websocket)
            assert resume(websocket)["type"] == "call.resumed"


@pytest.mark.asyncio
async def test_cancelled_handshake_releases_owner_without_touching_new_generation():
    configured_runtime, session, _ = enabled_test_runtime()
    hub = configured_runtime.call_transport_hub
    binding = await hub.attach_start(session, user_id="user-1", connection_id=object())
    entered = asyncio.Event()

    async def handshake():
        async with call_endpoint._handshake_ownership(hub, binding, None, None):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(handshake())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    replacement = await hub.attach_start(session, user_id="user-1", connection_id=object())
    assert not await hub.detach(binding)
    assert hub.is_current(replacement)
    await hub.detach(replacement)


@pytest.mark.asyncio
async def test_send_failure_wakes_idle_receive_and_releases_stage_for_resume(monkeypatch):
    configured_runtime, session, _ = enabled_test_runtime()
    hub = configured_runtime.call_transport_hub
    binding = await hub.attach_start(session, user_id="user-1", connection_id=object())
    receive_started = asyncio.Event()
    receive_cancelled = asyncio.Event()
    disconnected = asyncio.Event()
    outputs = asyncio.Queue()
    await outputs.put(CallWireOutput(text="queued-output"))

    class Socket:
        close_code = None

        async def accept(self):
            pass

        async def receive(self):
            receive_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                receive_cancelled.set()

        async def send_text(self, text):
            await receive_started.wait()
            raise RuntimeError("injected physical send failure")

        async def close(self, *, code, reason):
            self.close_code = code

    class Stage:
        async def disconnect(self):
            disconnected.set()

        async def wait_closed(self):
            await asyncio.Event().wait()

    async def attach(*args):
        return binding, Stage(), outputs

    app_for(monkeypatch, configured_runtime)
    monkeypatch.setattr(call_endpoint, "_authenticate_and_attach", attach)
    socket = Socket()
    try:
        await asyncio.wait_for(call_endpoint.call_ws(socket), 1)
        assert socket.close_code == 1011
        assert receive_cancelled.is_set()
        assert disconnected.is_set()
        assert not hub.is_current(binding)
        replacement = await hub.attach_start(session, user_id="user-1", connection_id=object())
        assert hub.is_current(replacement)
        await hub.detach(replacement)
    finally:
        await hub.close()
