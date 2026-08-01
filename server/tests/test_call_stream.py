import asyncio
import base64
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest


server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.chat_session.call_models import CallExitCode, CallState
from src.chat_session.call_stream import CallStream
from src.chat_session.call_stream_manager import (
    CallRejectedError,
    CallStreamManager,
    is_call_event_bound,
)
from src.system.user_interface.types import WSEventType, WSMessage


class FakeWebSocket:
    def __init__(self):
        self.events = []

    async def send_json(self, event):
        self.events.append(event)


class FakeSession:
    def __init__(self):
        self.audio = []

    async def append_audio(self, audio):
        self.audio.append(audio)

    async def close(self):
        pass

    async def events(self):
        await asyncio.Future()
        if False:
            yield None


class FakeCallStore:
    @staticmethod
    def create_active_session(**_kwargs):
        return True


def make_stream(config=None):
    websocket = FakeWebSocket()
    stream = CallStream(
        call_id="call-1",
        user_id="user-1",
        user_name="alice",
        character_id="luotianyi",
        ws_connection=SimpleNamespace(websocket=websocket),
        config=config or {},
        realtime_dialogue_service=object(),
        conversation_service=object(),
        global_speaking_worker=SimpleNamespace(),
        agent_runtime=object(),
        call_store=FakeCallStore(),
    )
    return stream, websocket


def audio_event(seq, payload):
    return WSMessage(
        event_type=WSEventType.CALL_AUDIO_APPEND.value,
        payload={"seq": seq, "audio": base64.b64encode(payload).decode("ascii")},
    )


@pytest.mark.asyncio
async def test_start_waits_for_delay_and_provider_without_busy_loop():
    stream, _ = make_stream({"request_delay_seconds": 0.01})
    provider_release = asyncio.Event()
    ticker_count = 0
    ticking = True

    async def prepare_provider():
        await provider_release.wait()
        stream.session = FakeSession()

    async def ticker():
        nonlocal ticker_count
        while ticking:
            ticker_count += 1
            await asyncio.sleep(0)

    stream._prepare_provider = prepare_provider
    tick_task = asyncio.create_task(ticker())
    start_task = asyncio.create_task(stream.start())
    await asyncio.sleep(0.03)

    assert not start_task.done()
    assert ticker_count > 10

    provider_release.set()
    await asyncio.wait_for(start_task, timeout=1)
    ticking = False
    await tick_task
    assert stream.state == CallState.ACTIVE

    await stream._stop_audio_worker()
    await stream._cancel_task(stream.provider_task)


@pytest.mark.asyncio
async def test_audio_queue_packet_size_and_rate_are_bounded():
    stream, websocket = make_stream(
        {
            "audio_queue_maxsize": 2,
            "max_audio_packet_bytes": 4,
            "max_audio_packets_per_second": 3,
        }
    )
    stream.state = CallState.ACTIVE
    stream.session = FakeSession()

    await stream.handle_client_event(audio_event(0, b"oversized"))
    await stream.handle_client_event(audio_event(0, b"one"))
    await stream.handle_client_event(audio_event(1, b"two"))
    await stream.handle_client_event(audio_event(2, b"tri"))

    assert stream._audio_queue.qsize() == 2
    codes = [event["payload"]["code"] for event in websocket.events]
    assert "AUDIO_PACKET_TOO_LARGE" in codes
    assert "AUDIO_RATE_LIMIT" in codes
    assert len(stream._audio_arrival_times) <= 3


@pytest.mark.asyncio
async def test_audio_queue_overload_is_visible_and_never_grows_past_capacity():
    stream, websocket = make_stream(
        {"audio_queue_maxsize": 2, "max_audio_packets_per_second": 100}
    )
    stream.state = CallState.ACTIVE
    stream.session = FakeSession()

    await stream.handle_client_event(audio_event(0, b"zero"))
    await stream.handle_client_event(audio_event(1, b"one"))
    await stream.handle_client_event(audio_event(2, b"two"))

    assert stream._audio_queue.qsize() == 2
    assert websocket.events[-1]["payload"]["code"] == "AUDIO_OVERLOADED"


@pytest.mark.asyncio
async def test_audio_single_consumer_reorders_within_window_exactly_once():
    stream, _ = make_stream(
        {
            "audio_queue_maxsize": 8,
            "audio_reorder_window": 4,
            "audio_reorder_wait_seconds": 0.2,
            "max_audio_packets_per_second": 100,
        }
    )
    stream.state = CallState.ACTIVE
    stream.session = FakeSession()
    stream._audio_worker_task = asyncio.create_task(stream._run_audio_worker())

    one = audio_event(1, b"one")
    zero = audio_event(0, b"zero")
    await stream.handle_client_event(one)
    await stream.handle_client_event(zero)
    await stream._audio_queue.join()
    await stream.handle_client_event(one)
    await stream._audio_queue.join()

    assert stream.session.audio == [zero.payload["audio"], one.payload["audio"]]
    assert stream._next_audio_seq == 2
    assert stream._audio_reorder_buffer == {}

    stream.state = CallState.ENDING
    await stream._stop_audio_worker()


@pytest.mark.asyncio
async def test_audio_gap_timeout_is_explicit_and_releases_buffer():
    stream, websocket = make_stream(
        {
            "audio_reorder_window": 4,
            "audio_reorder_wait_seconds": 0.02,
            "max_audio_packets_per_second": 100,
        }
    )
    stream.state = CallState.ACTIVE
    stream.session = FakeSession()
    stream._audio_worker_task = asyncio.create_task(stream._run_audio_worker())

    await stream.handle_client_event(audio_event(1, b"one"))
    await stream._audio_queue.join()
    await asyncio.sleep(0.05)

    assert stream.session.audio == [audio_event(1, b"one").payload["audio"]]
    assert stream._next_audio_seq == 2
    assert stream._audio_reorder_buffer == {}
    assert any(
        event["payload"].get("code") == "AUDIO_SEQUENCE_GAP"
        for event in websocket.events
    )

    stream.state = CallState.ENDING
    await stream._stop_audio_worker()


@pytest.mark.asyncio
async def test_audio_sequence_outside_window_is_rejected_without_advancing():
    stream, websocket = make_stream(
        {"audio_reorder_window": 2, "max_audio_packets_per_second": 100}
    )
    stream.state = CallState.ACTIVE
    stream.session = FakeSession()
    stream._audio_worker_task = asyncio.create_task(stream._run_audio_worker())

    await stream.handle_client_event(audio_event(5, b"far"))
    await stream._audio_queue.join()

    assert stream._next_audio_seq == 0
    assert stream._audio_reorder_buffer == {}
    assert websocket.events[-1]["payload"]["code"] == "AUDIO_SEQUENCE_WINDOW_EXCEEDED"

    stream.state = CallState.ENDING
    await stream._stop_audio_worker()


@pytest.mark.asyncio
async def test_call_manager_shutdown_is_idempotent_and_retries_failed_stream():
    class FlakyStream:
        call_id = "call-1"
        state = CallState.ACTIVE
        _postprocess_task = None

        def __init__(self):
            self.end_calls = 0

        async def end(self, _exit_code, _reason):
            self.end_calls += 1
            if self.end_calls == 1:
                raise RuntimeError("temporary stop failure")
            self.state = CallState.ENDED

    stream = FlakyStream()
    manager = object.__new__(CallStreamManager)
    manager.config = {"shutdown_timeout_seconds": 0.1}
    manager._lock = asyncio.Lock()
    manager._stop_lock = asyncio.Lock()
    manager._stopping = False
    manager._stopped = False
    manager._cleanup_task = None
    manager._streams_by_call_id = {stream.call_id: stream}
    manager._call_id_by_user_id = {"user-1": stream.call_id}
    manager._start_requests = {}
    manager._start_tasks = {}

    with pytest.raises(RuntimeError, match="temporary stop failure"):
        await manager.stop_background_services()
    assert manager._streams_by_call_id == {stream.call_id: stream}

    await manager.stop_background_services()
    await manager.stop_background_services()

    assert stream.end_calls == 2
    assert manager._streams_by_call_id == {}
    assert manager._stopped is True


class FakeSpeakingWorker:
    async def cancel_pending(self, **_kwargs):
        return None


def make_manager(config=None):
    return CallStreamManager(
        {"enabled": True, **(config or {})},
        conversation_service=object(),
        global_speaking_worker=object(),
        realtime_dialogue_service=object(),
        agent_runtime=object(),
        call_store=object(),
    )


async def cancel_manager_start_tasks(manager):
    tasks = list(manager._start_tasks.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_manager_allows_five_calls_and_rejects_the_sixth(monkeypatch):
    blocker = asyncio.Event()

    async def blocked_start(_stream):
        await blocker.wait()

    monkeypatch.setattr(CallStream, "start", blocked_start)
    manager = make_manager({"max_concurrent_calls": 5})
    connections = [
        SimpleNamespace(user_uuid=f"user-{index}", user_name=f"user-{index}")
        for index in range(6)
    ]
    try:
        for connection in connections[:5]:
            await manager.start_call(ws_connection=connection)
        with pytest.raises(CallRejectedError) as rejected:
            await manager.start_call(ws_connection=connections[5])
        assert rejected.value.code == "CALL_CONCURRENCY_LIMIT"
        assert len(manager._streams_by_call_id) == 5
    finally:
        await cancel_manager_start_tasks(manager)


@pytest.mark.asyncio
async def test_manager_does_not_share_idempotent_start_across_websockets(monkeypatch):
    blocker = asyncio.Event()

    async def blocked_start(_stream):
        await blocker.wait()

    monkeypatch.setattr(CallStream, "start", blocked_start)
    manager = make_manager()
    first = SimpleNamespace(user_uuid="same-user", user_name="first")
    second = SimpleNamespace(user_uuid="same-user", user_name="second")
    try:
        stream = await manager.start_call(
            ws_connection=first,
            client_request_id="same-request",
        )
        assert await manager.start_call(
            ws_connection=first,
            client_request_id="same-request",
        ) is stream
        with pytest.raises(CallRejectedError) as rejected:
            await manager.start_call(
                ws_connection=second,
                client_request_id="same-request",
            )
        assert rejected.value.code == "CALL_IN_PROGRESS"
    finally:
        await cancel_manager_start_tasks(manager)


def test_call_event_binding_rejects_foreign_socket_and_call_id():
    owner = object()
    foreign = object()
    stream = SimpleNamespace(call_id="call-1", ws_connection=owner)

    assert is_call_event_bound(stream, owner, {"call_id": "call-1"}) is True
    assert is_call_event_bound(stream, foreign, {"call_id": "call-1"}) is False
    assert is_call_event_bound(stream, owner, {"call_id": "call-2"}) is False
    assert is_call_event_bound(stream, owner, ["call-1"]) is False


@pytest.mark.asyncio
async def test_requesting_reconnect_stays_requesting_until_connected():
    stream, _ = make_stream()
    stream.global_speaking_worker = FakeSpeakingWorker()
    await stream.lost_connection()
    assert stream.state == CallState.RECONNECTING

    websocket = FakeWebSocket()
    assert await stream.reconnect(SimpleNamespace(websocket=websocket)) is True

    assert stream.state == CallState.REQUESTING
    assert websocket.events[-1]["type"] == WSEventType.CALL_REQUESTED.value
    assert stream._audio_worker_task is None


@pytest.mark.asyncio
async def test_stale_reconnect_cleanup_does_not_end_resumed_stream():
    stream, _ = make_stream()
    stream.global_speaking_worker = FakeSpeakingWorker()
    stream.state = CallState.ACTIVE
    await stream.lost_connection()
    stream._reconnect_deadline = 0
    resumed_ws = SimpleNamespace(websocket=FakeWebSocket())
    original_expire = stream.end_if_reconnect_expired

    async def resume_before_expire(now):
        assert await stream.reconnect(resumed_ws) is True
        return await original_expire(now)

    stream.end_if_reconnect_expired = resume_before_expire
    manager = make_manager()
    manager._streams_by_call_id[stream.call_id] = stream
    manager._call_id_by_user_id[stream.user_id] = stream.call_id

    await manager.cleanup_expired_streams()

    assert stream.state == CallState.ACTIVE
    assert manager.get_by_call_id(stream.call_id) is stream
    await stream._stop_audio_worker()


@pytest.mark.asyncio
async def test_ending_settlement_is_retried_and_released_by_cleanup():
    class RetryStore(FakeCallStore):
        def __init__(self):
            self.calls = 0

        def settle_call_and_conversation(self, **_kwargs):
            self.calls += 1
            return None if self.calls == 1 else "conversation-1"

    store = RetryStore()
    stream, _ = make_stream()
    stream.call_store = store
    stream.global_speaking_worker = FakeSpeakingWorker()
    stream.state = CallState.ACTIVE
    stream.connected_at = datetime.now() - timedelta(seconds=1)

    async def postprocess(**_kwargs):
        return None

    stream._settlement.process_after_end = postprocess
    with pytest.raises(RuntimeError, match="connected call settlement failed"):
        await stream.end(CallExitCode.NORMAL, "first_attempt")
    assert stream.state == CallState.ENDING

    manager = make_manager()
    manager._streams_by_call_id[stream.call_id] = stream
    manager._call_id_by_user_id[stream.user_id] = stream.call_id
    await manager.cleanup_expired_streams()

    assert store.calls == 2
    assert manager.get_by_call_id(stream.call_id) is None


@pytest.mark.asyncio
async def test_ended_reentry_completes_missing_finalization_marker():
    stream, websocket = make_stream()
    stream.state = CallState.ENDED
    stream.exit_code = int(CallExitCode.NORMAL)
    stream.ended_at = datetime.now()

    await stream.end(CallExitCode.NORMAL, "retry_finalization")

    assert stream._end_event.is_set()
    assert websocket.events[-1]["type"] == WSEventType.CALL_ENDED.value


@pytest.mark.asyncio
async def test_call_tts_send_failure_keeps_packet_sequence_for_retry():
    class FlakyWebSocket(FakeWebSocket):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        async def send_json(self, event):
            self.attempts += 1
            if self.attempts == 1:
                raise ConnectionError("temporary")
            await super().send_json(event)

    stream, _ = make_stream()
    websocket = FlakyWebSocket()
    stream.ws_connection = SimpleNamespace(websocket=websocket)
    stream.state = CallState.ACTIVE
    stream._audio_lines["audio-1"] = SimpleNamespace(
        response_id="response-1",
        expression="",
    )
    response = SimpleNamespace(
        uuid="audio-1",
        audio="chunk",
        is_final_package=True,
        expression="",
    )

    with pytest.raises(ConnectionError, match="not accepted"):
        await stream._send_tts_packet(response)
    assert stream._audio_packet_seq("audio-1") == 0

    await stream._send_tts_packet(response)
    assert websocket.events[-1]["payload"]["seq"] == 0
    assert stream._audio_packet_seq("audio-1") == 1
