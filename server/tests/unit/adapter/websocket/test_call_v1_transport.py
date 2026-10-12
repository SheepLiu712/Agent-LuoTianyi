import asyncio
import json

import pytest

from src.adapter.websocket.call_v1 import (
    CALL_CLOSE_TRY_AGAIN_LATER,
    BinaryAudioFrameCodec,
    CallAcceptanceReceipt,
    CallTransportBackpressure,
    CallTransportConfig,
    CallTransportError,
    CallTransportHub,
    CallTransportSession,
    InboundCallFrame,
    WireAudioFrame,
)

CALL_ID = "606ec5e6-a330-4e6c-b07a-8432a5716c8f"


class AcceptanceSink:
    def __init__(self, *, accept: bool = True) -> None:
        self.accept_result = accept
        self.frames: list[InboundCallFrame] = []
        self.receipts: list[CallAcceptanceReceipt] = []

    async def accept(self, frame: InboundCallFrame, receipt: CallAcceptanceReceipt) -> bool:
        if self.accept_result:
            self.frames.append(frame)
            self.receipts.append(receipt)
        return self.accept_result


def session(sink: AcceptanceSink | None = None, **config) -> CallTransportSession:
    return CallTransportSession(
        call_id=CALL_ID,
        user_id="user-1",
        character_id="luotianyi",
        sink=sink or AcceptanceSink(),
        config=CallTransportConfig(**config),
    )


def hangup(seq: int, reason: str = "user_hangup") -> str:
    return json.dumps(
        {"protocol": "call.v1", "type": "call.hangup", "seq": seq, "call_id": CALL_ID, "reason": reason},
        separators=(",", ":"),
    )


def audio(seq: int, payload: bytes = b"\x00\x01") -> bytes:
    return BinaryAudioFrameCodec().encode(WireAudioFrame(1, 2, 0, 0, seq, payload))


def message(output) -> dict:
    return json.loads(output.text)


def test_transport_metrics_capture_only_numeric_backlog_and_retry_fields() -> None:
    captured = []

    class Metrics:
        def record(self, metric):
            captured.append(metric)

    transport = CallTransportSession(
        call_id=CALL_ID,
        user_id="user-1",
        character_id="luotianyi",
        sink=AcceptanceSink(),
        call_metrics=Metrics(),
    )
    transport.send_control(
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
    transport.send_audio(WireAudioFrame(1, 2, 1, 1, 2, b"\x00\x01"))
    transport.acknowledge_server(2)
    with pytest.raises(CallTransportError, match="REPLAY_NOT_AVAILABLE"):
        transport.replay_missing(2)

    assert [metric.name.value for metric in captured] == ["buffer", "playback_ack_retry"]
    assert captured[0].numeric == {"buffered_bytes": captured[0].numeric["buffered_bytes"]}
    assert captured[1].numeric == {"ack_retry_count": 1}
    assert all("response_id" not in (metric.labels or {}) for metric in captured)


@pytest.mark.asyncio
async def test_hub_user_reset_closes_only_owned_replay_sessions() -> None:
    hub = CallTransportHub()
    owner = CallTransportSession(
        call_id=CALL_ID,
        user_id="owner",
        character_id="luotianyi",
        sink=AcceptanceSink(),
    )
    other = CallTransportSession(
        call_id="706ec5e6-a330-4e6c-b07a-8432a5716c8f",
        user_id="other",
        character_id="luotianyi",
        sink=AcceptanceSink(),
    )
    hub.register(owner)
    hub.register(other)

    assert await hub.close_user_sessions("owner") == 1
    assert hub.session_for(CALL_ID) is None
    assert hub.session_for(other.call_id) is other
    with pytest.raises(CallTransportError, match="TRANSPORT_CLOSED"):
        owner.send_control(
            {
                "protocol": "call.v1",
                "type": "ack",
                "ack_seq": 0,
                "call_id": CALL_ID,
            }
        )


@pytest.mark.asyncio
async def test_hub_checks_user_admission_before_resume() -> None:
    async def reject(_user_id: str) -> None:
        raise RuntimeError("USER_DATA_RESET_IN_PROGRESS")

    hub = CallTransportHub(require_user_admission=reject)
    session = CallTransportSession(
        call_id=CALL_ID,
        user_id="owner",
        character_id="luotianyi",
        sink=AcceptanceSink(),
    )
    hub.register(session)
    raw = json.dumps(
        {
            "protocol": "call.v1",
            "type": "call.resume",
            "call_id": CALL_ID,
            "character_id": "luotianyi",
            "last_contiguous_server_seq": 0,
        }
    )

    with pytest.raises(RuntimeError, match="USER_DATA_RESET_IN_PROGRESS"):
        await hub.attach_resume(raw, user_id="owner", connection_id=object())


@pytest.mark.asyncio
async def test_hub_rejected_start_is_not_registered_during_reset() -> None:
    async def reject(_user_id: str) -> None:
        raise RuntimeError("USER_DATA_RESET_IN_PROGRESS")

    hub = CallTransportHub(require_user_admission=reject)
    session = CallTransportSession(
        call_id=CALL_ID,
        user_id="owner",
        character_id="luotianyi",
        sink=AcceptanceSink(),
    )

    with pytest.raises(RuntimeError, match="USER_DATA_RESET_IN_PROGRESS"):
        await hub.register_and_attach_start(session, user_id="owner", connection_id=object())
    assert hub.session_for(CALL_ID) is None


@pytest.mark.asyncio
async def test_hub_reset_race_invalidates_session_registered_after_admission() -> None:
    from src.application.user import UserResetFence

    fence = UserResetFence()
    hub = CallTransportHub(user_reset_fence=fence)
    session = CallTransportSession(
        call_id=CALL_ID,
        user_id="owner",
        character_id="luotianyi",
        sink=AcceptanceSink(),
    )
    registered = asyncio.Event()
    release = asyncio.Event()
    original = hub._register_start

    async def blocked_register(*args, **kwargs):
        binding = await original(*args, **kwargs)
        registered.set()
        await release.wait()
        return binding

    hub._register_start = blocked_register
    task = asyncio.create_task(hub.register_and_attach_start(session, user_id="owner", connection_id=object()))
    await registered.wait()
    token = await fence.begin("owner")
    release.set()
    with pytest.raises(RuntimeError, match="USER_DATA_RESET_INVALIDATED_OPERATION"):
        await task
    await fence.wait("owner")
    assert hub.session_for(CALL_ID) is None
    await fence.end("owner", token)


@pytest.mark.asyncio
async def test_receive_start_requires_seq_one_is_idempotent_and_conflict_safe() -> None:
    transport = session()
    start = json.dumps(
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

    first = await transport.receive_start(start)
    duplicate = await transport.receive_start(start)

    assert message(first[0])["ack_seq"] == 1
    assert message(duplicate[0])["ack_seq"] == 1
    assert transport.client_cursor == 1

    conflicting = start.replace("request-1", "request-2")
    with pytest.raises(CallTransportError, match="SEQ_CONFLICT"):
        await transport.receive_start(conflicting)

    seq_two = json.loads(start)
    seq_two["seq"] = 2
    another = session()
    with pytest.raises(CallTransportError, match="INVALID_CALL_START"):
        await another.receive_start(json.dumps(seq_two, separators=(",", ":")))


@pytest.mark.asyncio
async def test_hub_shutdown_owns_cancels_and_observes_release_tasks() -> None:
    hub = CallTransportHub()
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocked_release():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    task = hub.own_task(blocked_release(), name="call-transport-release")
    await entered.wait()

    await hub.close()

    assert task.cancelled()
    assert cancelled.is_set()
    assert hub._owned_tasks == set()


@pytest.mark.asyncio
async def test_cancelled_registration_waits_for_late_owned_completion_and_leaves_no_session() -> None:
    from src.application.user import UserResetFence

    fence = UserResetFence()
    hub = CallTransportHub(user_reset_fence=fence)
    session = CallTransportSession(
        call_id=CALL_ID,
        user_id="owner",
        character_id="luotianyi",
        sink=AcceptanceSink(),
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    original = hub._register_start

    async def late_register(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    hub._register_start = late_register
    operation = asyncio.create_task(hub.register_and_attach_start(session, user_id="owner", connection_id=object()))
    await entered.wait()
    operation.cancel()
    await asyncio.sleep(0)
    assert not operation.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert hub.session_for(CALL_ID) is None
    assert fence._operations == {}


@pytest.mark.asyncio
async def test_old_disconnect_cannot_detach_new_resume_generation() -> None:
    hub = CallTransportHub()
    transport = session()
    hub.register(transport)
    old = await hub.attach_start(transport, user_id="user-1", connection_id=object())
    entered = asyncio.Event()
    release = asyncio.Event()

    async def disconnect_stage():
        entered.set()
        await release.wait()

    disconnect = asyncio.create_task(hub.detach_after_disconnect(old, disconnect_stage))
    await entered.wait()
    assert hub.is_current(old)
    release.set()
    assert await disconnect is True
    resumed = await hub.attach_resume(
        json.dumps(
            {
                "protocol": "call.v1",
                "type": "call.resume",
                "call_id": CALL_ID,
                "character_id": "luotianyi",
                "last_contiguous_server_seq": 0,
            }
        ),
        user_id="user-1",
        connection_id=object(),
    )

    assert await hub.detach(old) is False
    assert hub.is_current(resumed)


def resume_raw(*, character_id: str = "luotianyi") -> str:
    return json.dumps(
        {
            "protocol": "call.v1",
            "type": "call.resume",
            "call_id": CALL_ID,
            "character_id": character_id,
            "last_contiguous_server_seq": 0,
        }
    )


@pytest.mark.asyncio
async def test_resume_waits_for_the_observed_connection_to_release() -> None:
    hub = CallTransportHub(resume_release_timeout=0.2)
    transport = session()
    hub.register(transport)
    old = await hub.attach_start(transport, user_id="user-1", connection_id=object())

    resume = asyncio.create_task(hub.attach_resume(resume_raw(), user_id="user-1", connection_id=object()))
    await asyncio.sleep(0)
    assert not resume.done()

    assert await hub.detach(old) is True
    replacement = await resume

    assert replacement.generation == old.generation + 1
    assert hub.is_current(replacement)


@pytest.mark.asyncio
async def test_resume_does_not_take_over_a_live_connection_after_release_timeout() -> None:
    hub = CallTransportHub(resume_release_timeout=0.01)
    transport = session()
    hub.register(transport)
    old = await hub.attach_start(transport, user_id="user-1", connection_id=object())

    with pytest.raises(CallTransportError, match="CALL_CONNECTION_ACTIVE") as rejected:
        await hub.attach_resume(resume_raw(), user_id="user-1", connection_id=object())

    assert rejected.value.code == "CALL_CONNECTION_ACTIVE"
    assert hub.is_current(old)


@pytest.mark.asyncio
async def test_only_one_concurrent_resume_owns_the_released_generation() -> None:
    hub = CallTransportHub(resume_release_timeout=0.2)
    transport = session()
    hub.register(transport)
    old = await hub.attach_start(transport, user_id="user-1", connection_id=object())
    attempts = [
        asyncio.create_task(hub.attach_resume(resume_raw(), user_id="user-1", connection_id=object())) for _ in range(2)
    ]
    await asyncio.sleep(0)

    assert await hub.detach(old) is True
    results = await asyncio.gather(*attempts, return_exceptions=True)

    bindings = [result for result in results if not isinstance(result, BaseException)]
    errors = [result for result in results if isinstance(result, CallTransportError)]
    assert len(bindings) == 1
    assert len(errors) == 1
    assert errors[0].code == "CALL_CONNECTION_ACTIVE"
    assert hub.is_current(bindings[0])


@pytest.mark.asyncio
async def test_wrong_resume_identity_is_rejected_without_waiting_for_release() -> None:
    hub = CallTransportHub(resume_release_timeout=10.0)
    transport = session()
    hub.register(transport)
    old = await hub.attach_start(transport, user_id="user-1", connection_id=object())

    with pytest.raises(CallTransportError) as wrong_user:
        await hub.attach_resume(resume_raw(), user_id="other-user", connection_id=object())
    with pytest.raises(CallTransportError) as wrong_character:
        await hub.attach_resume(resume_raw(character_id="other-character"), user_id="user-1", connection_id=object())

    assert wrong_user.value.code == "RESUME_OWNERSHIP_MISMATCH"
    assert wrong_character.value.code == "RESUME_OWNERSHIP_MISMATCH"
    assert hub.is_current(old)


@pytest.mark.asyncio
@pytest.mark.parametrize("release", ["unregister", "reset", "shutdown"])
async def test_resume_waiter_is_woken_when_session_can_no_longer_bind(release: str) -> None:
    hub = CallTransportHub(resume_release_timeout=10.0)
    transport = session()
    hub.register(transport)
    await hub.attach_start(transport, user_id="user-1", connection_id=object())
    resume = asyncio.create_task(hub.attach_resume(resume_raw(), user_id="user-1", connection_id=object()))
    await asyncio.sleep(0)

    if release == "unregister":
        assert await hub.unregister(CALL_ID, expected_session=transport) is True
    elif release == "reset":
        assert await hub.close_user_sessions("user-1") == 1
    else:
        await hub.close()

    with pytest.raises(CallTransportError) as rejected:
        await resume
    assert rejected.value.code == "CALL_NOT_FOUND"


@pytest.mark.asyncio
async def test_cancelled_resume_waiter_does_not_leave_an_owned_task() -> None:
    hub = CallTransportHub(resume_release_timeout=10.0)
    transport = session()
    hub.register(transport)
    await hub.attach_start(transport, user_id="user-1", connection_id=object())
    resume = asyncio.create_task(hub.attach_resume(resume_raw(), user_id="user-1", connection_id=object()))
    await asyncio.sleep(0)

    resume.cancel()
    with pytest.raises(asyncio.CancelledError):
        await resume

    assert hub._owned_tasks == set()


@pytest.mark.asyncio
async def test_late_old_disconnect_cannot_release_the_resumed_generation() -> None:
    hub = CallTransportHub(resume_release_timeout=0.2)
    transport = session()
    hub.register(transport)
    old = await hub.attach_start(transport, user_id="user-1", connection_id=object())
    resume = asyncio.create_task(hub.attach_resume(resume_raw(), user_id="user-1", connection_id=object()))
    await asyncio.sleep(0)
    assert await hub.detach(old) is True
    replacement = await resume

    assert await hub.detach(old) is False
    assert hub.is_current(replacement)


@pytest.mark.asyncio
async def test_resume_rechecks_user_admission_after_waiting_for_release() -> None:
    admitted = True

    async def require_user_admission(_user_id: str) -> None:
        if not admitted:
            raise RuntimeError("USER_DATA_RESET_IN_PROGRESS")

    hub = CallTransportHub(require_user_admission=require_user_admission, resume_release_timeout=0.2)
    transport = session()
    hub.register(transport)
    old = await hub.attach_start(transport, user_id="user-1", connection_id=object())
    resume = asyncio.create_task(hub.attach_resume(resume_raw(), user_id="user-1", connection_id=object()))
    await asyncio.sleep(0)
    admitted = False
    assert await hub.detach(old) is True

    with pytest.raises(RuntimeError, match="USER_DATA_RESET_IN_PROGRESS"):
        await resume
    assert hub.session_for(CALL_ID) is transport


@pytest.mark.asyncio
async def test_resume_release_budget_is_bounded_below_the_stage_recovery_window() -> None:
    hub = CallTransportHub()
    transport = session()
    hub.register(transport)
    await hub.attach_start(transport, user_id="user-1", connection_id=object())
    started = asyncio.get_running_loop().time()

    with pytest.raises(CallTransportError) as rejected:
        await hub.attach_resume(resume_raw(), user_id="user-1", connection_id=object())

    elapsed = asyncio.get_running_loop().time() - started
    assert rejected.value.code == "CALL_CONNECTION_ACTIVE"
    assert 2.0 <= elapsed < 3.0


@pytest.mark.asyncio
async def test_terminal_timeout_unregisters_only_expected_session_and_shutdown_leaves_no_tasks():
    hub = CallTransportHub()
    old = session()
    hub.register(old)
    waiter = hub.own_task(asyncio.Event().wait(), name="call-transport-release")
    replacement = CallTransportSession(
        call_id="706ec5e6-a330-4e6c-b07a-8432a5716c8f",
        user_id="user-1",
        character_id="luotianyi",
        sink=AcceptanceSink(),
    )
    hub.register(replacement)

    assert await hub.unregister(old.call_id, expected_session=replacement) is False
    assert hub.session_for(old.call_id) is old
    assert hub.session_for(replacement.call_id) is replacement

    await hub.close()

    assert waiter.cancelled()
    assert hub._owned_tasks == set()
    assert hub._sessions == {}


@pytest.mark.asyncio
async def test_mixed_control_and_audio_share_one_client_sequence() -> None:
    sink = AcceptanceSink()
    transport = session(sink)

    assert message((await transport.receive_text(hangup(1)))[0])["ack_seq"] == 1
    assert message((await transport.receive_binary(audio(2)))[0])["ack_seq"] == 2

    assert [(frame.kind, frame.seq) for frame in sink.frames] == [("control", 1), ("audio", 2)]


@pytest.mark.asyncio
async def test_gap_nacks_first_missing_and_drains_only_after_sink_accepts() -> None:
    sink = AcceptanceSink()
    transport = session(sink)

    assert message((await transport.receive_binary(audio(2)))[0]) == {
        "protocol": "call.v1",
        "type": "nack",
        "call_id": CALL_ID,
        "missing_seq": 1,
    }
    assert sink.frames == []
    assert message((await transport.receive_text(hangup(1)))[0])["ack_seq"] == 2
    assert [frame.seq for frame in sink.frames] == [1, 2]

    sink.accept_result = False
    overloaded = await transport.receive_text(hangup(3))
    assert message(overloaded[0])["code"] == "OVERLOADED"
    assert transport.client_cursor == 2


@pytest.mark.asyncio
async def test_same_bytes_duplicate_is_idempotent_but_seq_conflict_closes() -> None:
    sink = AcceptanceSink()
    transport = session(sink)

    await transport.receive_text(hangup(1))
    assert message((await transport.receive_text(hangup(1)))[0])["ack_seq"] == 1
    assert len(sink.frames) == 1
    with pytest.raises(CallTransportError, match="SEQ_CONFLICT"):
        await transport.receive_text(hangup(1, "backgrounded"))


@pytest.mark.asyncio
async def test_pending_window_is_bounded_without_dropping_oldest_frame() -> None:
    transport = session(max_pending_frames=1)

    await transport.receive_binary(audio(2))
    with pytest.raises(CallTransportError) as raised:
        await transport.receive_binary(audio(3))

    assert raised.value.code == "PENDING_WINDOW_FULL"
    assert raised.value.close_code == CALL_CLOSE_TRY_AGAIN_LATER
    assert message((await transport.receive_text(hangup(1)))[0])["ack_seq"] == 2


def test_server_replay_preserves_original_text_and_binary_bytes() -> None:
    transport = session()
    started = transport.send_control(
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
    pcm = transport.send_audio(WireAudioFrame(1, 2, 1, 1, 2, b"\x00\x01"))

    replay = transport.replay_after(0)

    assert replay == [started, pcm]
    assert replay[0].text == started.text
    assert replay[1].binary == pcm.binary


def test_ack_frees_replay_but_never_accepts_future_or_regressing_cursor() -> None:
    transport = session()
    transport.send_control(
        {
            "protocol": "call.v1",
            "type": "call.state",
            "seq": 1,
            "call_id": CALL_ID,
            "client_request_id": "request-1",
            "state": "preparing",
        }
    )
    transport.acknowledge_server(1)

    assert transport.server_ack_cursor == 1
    assert transport.replay_after(1) == []
    with pytest.raises(CallTransportError, match="INVALID_ACK_CURSOR"):
        transport.acknowledge_server(0)
    with pytest.raises(CallTransportError, match="INVALID_ACK_CURSOR"):
        transport.acknowledge_server(2)


def test_retired_audio_payload_is_not_replayed_and_nack_replays_stop() -> None:
    transport = session()
    transport.send_control(
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
    transport.send_audio(WireAudioFrame(1, 2, 0, 1, 2, b"\x00\x01"))
    stop = transport.send_control(
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

    assert transport.replay_after(0) == [stop]
    assert transport.replay_missing(2) == [stop]


def test_stop_uses_net_replay_capacity_atomically() -> None:
    probe = session()
    started = start_stream(probe)
    audio_output = probe.send_audio(WireAudioFrame(1, 2, 0, 1, 2, b"\x00\x01" * 80))
    stop_message = {
        "protocol": "call.v1",
        "type": "playback.stop",
        "seq": 3,
        "call_id": CALL_ID,
        "response_id": "response-1",
        "stream_id": 1,
        "retire_server_seq": {"from": 1, "through": 2},
        "reason": "user_interrupted",
    }
    stop_bytes = len(json.dumps(stop_message, separators=(",", ":")).encode("utf-8"))
    current_bytes = len(started.text.encode("utf-8")) + len(audio_output.binary)
    transport = session(max_replay_bytes=max(current_bytes, stop_bytes))
    start_stream(transport)
    transport.send_audio(WireAudioFrame(1, 2, 0, 1, 2, b"\x00\x01" * 80))

    stop = transport.send_control(stop_message)

    assert transport.last_server_seq == 3
    assert transport.replay_after(0) == [stop]


def test_retirement_releases_response_audio_budget() -> None:
    transport = session(max_replay_bytes=2_000_000)
    start_stream(transport)
    payload = b"\x00\x01" * 8_000
    for seq in range(2, 92):
        transport.send_audio(WireAudioFrame(1, 2, 0, 1, seq, payload))
    stop = transport.send_control(
        {
            "protocol": "call.v1",
            "type": "playback.stop",
            "seq": 92,
            "call_id": CALL_ID,
            "response_id": "response-1",
            "stream_id": 1,
            "retire_server_seq": {"from": 1, "through": 91},
            "reason": "user_interrupted",
        }
    )

    assert transport.replay_after(0) == [stop]
    assert transport._response_audio_bytes["response-1"] == 0


def test_stop_net_capacity_failure_has_no_partial_state() -> None:
    probe = session()
    unrelated = probe.send_control(
        {
            "protocol": "call.v1",
            "type": "call.state",
            "seq": 1,
            "call_id": CALL_ID,
            "client_request_id": "request-1",
            "state": "preparing",
        }
    )
    message_data = {
        "protocol": "call.v1",
        "type": "playback.stop",
        "seq": 4,
        "call_id": CALL_ID,
        "response_id": "response-1",
        "stream_id": 1,
        "retire_server_seq": {"from": 2, "through": 3},
        "reason": "user_interrupted",
    }
    probe_started = start_stream(probe, seq=2)
    probe_audio = probe.send_audio(WireAudioFrame(1, 2, 0, 1, 3, b"\x00\x01"))
    stop_bytes = len(json.dumps(message_data, separators=(",", ":")).encode("utf-8"))
    unrelated_bytes = len(unrelated.text.encode("utf-8"))
    current_bytes = unrelated_bytes + len(probe_started.text.encode("utf-8")) + len(probe_audio.binary)
    transport = session(max_replay_bytes=current_bytes)
    transport.send_control(json.loads(unrelated.text))
    start_stream(transport, seq=2)
    transport.send_audio(WireAudioFrame(1, 2, 0, 1, 3, b"\x00\x01"))
    object.__setattr__(transport._config, "max_replay_bytes", unrelated_bytes + stop_bytes - 1)

    with pytest.raises(CallTransportBackpressure, match="REPLAY_BUFFER_FULL"):
        transport.send_control(message_data)
    assert transport.last_server_seq == 3
    replay = transport.replay_after(0)
    assert len(replay) == 3
    assert replay[2].binary == b"\x01\x02\x00\x00\x00\x00\x01\x00\x00\x00\x03\x00\x00\x00\x02\x00\x01"
    assert transport._response_audio_bytes["response-1"] == 2
    assert transport._stop_metadata == {}


@pytest.mark.asyncio
async def test_playback_stopped_metadata_survives_ack_and_is_idempotent() -> None:
    sink = AcceptanceSink()
    transport = session(sink)
    start_stream(transport)
    transport.send_audio(WireAudioFrame(1, 2, 0, 1, 2, b"\x00\x01"))
    transport.send_control(
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
    transport.acknowledge_server(3)
    stopped = json.dumps(
        {
            "protocol": "call.v1",
            "type": "playback.stopped",
            "seq": 1,
            "call_id": CALL_ID,
            "response_id": "response-1",
            "stop_seq": 3,
        },
        separators=(",", ":"),
    )

    assert message((await transport.receive_text(stopped))[0])["ack_seq"] == 1
    assert message((await transport.receive_text(stopped))[0])["ack_seq"] == 1
    assert len(sink.frames) == 1


@pytest.mark.asyncio
async def test_playback_stopped_before_ack_remains_valid_after_ack() -> None:
    sink = AcceptanceSink()
    transport = session(sink)
    start_stream(transport)
    transport.send_audio(WireAudioFrame(1, 2, 0, 1, 2, b"\x00\x01"))
    transport.send_control(
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
    stopped = json.dumps(
        {
            "protocol": "call.v1",
            "type": "playback.stopped",
            "seq": 1,
            "call_id": CALL_ID,
            "response_id": "response-1",
            "stop_seq": 3,
        },
        separators=(",", ":"),
    )

    assert message((await transport.receive_text(stopped))[0])["ack_seq"] == 1
    transport.acknowledge_server(3)
    assert message((await transport.receive_text(stopped))[0])["ack_seq"] == 1
    assert len(sink.frames) == 1


@pytest.mark.asyncio
async def test_playback_stopped_rejects_unknown_stop_and_wrong_response() -> None:
    transport = session()
    start_stream(transport)
    transport.send_audio(WireAudioFrame(1, 2, 0, 1, 2, b"\x00\x01"))
    transport.send_control(
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
    for index, (response_id, stop_seq) in enumerate((("response-1", 99), ("wrong", 3)), start=1):
        stopped = json.dumps(
            {
                "protocol": "call.v1",
                "type": "playback.stopped",
                "seq": index,
                "call_id": CALL_ID,
                "response_id": response_id,
                "stop_seq": stop_seq,
            },
            separators=(",", ":"),
        )
        with pytest.raises(CallTransportError, match="INVALID_PLAYBACK_STOP_CONFIRMATION"):
            await transport.receive_text(stopped)


@pytest.mark.parametrize("acknowledged", [False, True])
@pytest.mark.parametrize("tail_audio", [False, True])
def test_retirement_cannot_cover_unrelated_control_or_other_stream(acknowledged, tail_audio) -> None:
    transport = session()
    transport.send_control(
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
    transport.send_control(
        {
            "protocol": "call.v1",
            "type": "call.state",
            "seq": 2,
            "call_id": CALL_ID,
            "client_request_id": "request-1",
            "state": "ringing",
        }
    )

    if tail_audio:
        transport.send_audio(WireAudioFrame(1, 2, 1, 1, 3, b"\x00\x01"))
    last_seq = 3 if tail_audio else 2
    if acknowledged:
        transport.acknowledge_server(last_seq)
    with pytest.raises(CallTransportError, match="INVALID_RETIRE_RANGE"):
        transport.send_control(
            {
                "protocol": "call.v1",
                "type": "playback.stop",
                "seq": last_seq + 1,
                "call_id": CALL_ID,
                "response_id": "response-1",
                "stream_id": 1,
                "retire_server_seq": {"from": 1, "through": last_seq},
                "reason": "user_interrupted",
            }
        )
    assert transport.last_server_seq == last_seq
    replay = transport.replay_after(last_seq if acknowledged else 0)
    assert len(replay) == (0 if acknowledged else last_seq)


def test_replay_buffer_stops_producer_instead_of_evicting_unacked_oldest() -> None:
    transport = session(max_replay_bytes=200)
    first = transport.send_control(
        {
            "protocol": "call.v1",
            "type": "call.state",
            "seq": 1,
            "call_id": CALL_ID,
            "client_request_id": "request-1",
            "state": "preparing",
        }
    )
    with pytest.raises(CallTransportBackpressure) as raised:
        transport.send_control(
            {
                "protocol": "call.v1",
                "type": "call.state",
                "seq": 2,
                "call_id": CALL_ID,
                "client_request_id": "request-2",
                "state": "ringing",
            }
        )

    assert str(raised.value) == "REPLAY_BUFFER_FULL"
    assert transport.replay_after(0) == [first]
    assert transport.last_server_seq == 1


@pytest.mark.asyncio
async def test_replay_backpressure_waits_for_ack_and_retries_same_next_seq() -> None:
    transport = session(max_replay_bytes=200)
    transport.send_control(
        {
            "protocol": "call.v1",
            "type": "call.state",
            "seq": 1,
            "call_id": CALL_ID,
            "client_request_id": "request-1",
            "state": "preparing",
        }
    )
    candidate = {
        "protocol": "call.v1",
        "type": "call.state",
        "seq": 2,
        "call_id": CALL_ID,
        "client_request_id": "request-2",
        "state": "ringing",
    }
    with pytest.raises(CallTransportBackpressure):
        transport.send_control(candidate)
    waiter = asyncio.create_task(transport.wait_for_replay_capacity(150))
    await asyncio.sleep(0)
    assert not waiter.done()

    transport.acknowledge_server(1)
    await waiter
    output = transport.send_control(candidate)

    assert json.loads(output.text)["seq"] == 2
    assert transport.last_server_seq == 2


def test_stream_registration_is_not_published_when_replay_storage_rejects_start() -> None:
    transport = session(max_replay_bytes=1)

    with pytest.raises(CallTransportBackpressure, match="REPLAY_BUFFER_FULL"):
        transport.send_control(
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
    with pytest.raises(CallTransportError, match="UNREGISTERED_STREAM"):
        transport.send_audio(WireAudioFrame(1, 2, 0, 1, 1, b"\x00\x01"))


def test_resume_handshake_is_unsequenced_and_replays_after_cursor() -> None:
    transport = session()
    first = transport.send_control(
        {
            "protocol": "call.v1",
            "type": "call.state",
            "seq": 1,
            "call_id": CALL_ID,
            "client_request_id": "request-1",
            "state": "preparing",
        }
    )
    outputs = transport.resume(
        {
            "protocol": "call.v1",
            "type": "call.resume",
            "call_id": CALL_ID,
            "character_id": "luotianyi",
            "last_contiguous_server_seq": 0,
        }
    )

    assert message(outputs[0])["type"] == "call.resumed"
    assert "seq" not in message(outputs[0])
    assert outputs[1] == first


@pytest.mark.asyncio
async def test_call_start_is_rejected_without_lifecycle_dependencies() -> None:
    transport = session()
    raw = json.dumps(
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

    with pytest.raises(CallTransportError) as raised:
        await transport.receive_text(raw)

    assert raised.value.code == "CALL_START_UNAVAILABLE"
    assert raised.value.close_code == CALL_CLOSE_TRY_AGAIN_LATER


@pytest.mark.asyncio
async def test_playback_completion_requires_registered_final_stream() -> None:
    transport = session()
    completion = json.dumps(
        {
            "protocol": "call.v1",
            "type": "playback.completed",
            "seq": 1,
            "call_id": CALL_ID,
            "response_id": "response-1",
            "stream_id": 1,
        },
        separators=(",", ":"),
    )

    with pytest.raises(CallTransportError, match="INVALID_PLAYBACK_COMPLETION"):
        await transport.receive_text(completion)


def start_stream(transport, *, seq=1, stream_id=1, response_id="response-1"):
    return transport.send_control(
        {
            "protocol": "call.v1",
            "type": "audio.stream_started",
            "seq": seq,
            "call_id": CALL_ID,
            "audio_route": "CALL",
            "stream_id": stream_id,
            "response_id": response_id,
            "encoding": "pcm_s16le",
            "sample_rate": 24000,
            "channels": 1,
        }
    )


def test_response_audio_retention_has_exact_30_second_boundary() -> None:
    transport = session(max_replay_bytes=2_000_000)
    start_stream(transport)
    payload = b"\x00\x01" * 8_000

    for seq in range(2, 92):
        transport.send_audio(WireAudioFrame(1, 2, 0, 1, seq, payload))
    with pytest.raises(CallTransportBackpressure, match="RESPONSE_AUDIO_BUFFER_FULL"):
        transport.send_audio(WireAudioFrame(1, 2, 0, 1, 92, b"\x00\x01"))

    assert transport.last_server_seq == 91


def test_small_audio_is_not_rejected_by_wall_clock_age() -> None:
    transport = session()
    start_stream(transport)

    output = transport.send_audio(WireAudioFrame(1, 2, 0, 1, 2, b"\x00\x01"))

    assert output.binary is not None


def test_audio_ack_releases_response_budget_and_other_response_is_isolated() -> None:
    transport = session(max_replay_bytes=4_000_000)
    start_stream(transport)
    payload = b"\x00\x01" * 8_000
    for seq in range(2, 92):
        transport.send_audio(WireAudioFrame(1, 2, 0, 1, seq, payload))
    start_stream(transport, seq=92, stream_id=2, response_id="response-2")
    for seq in range(93, 183):
        transport.send_audio(WireAudioFrame(1, 2, 0, 2, seq, payload))

    with pytest.raises(CallTransportBackpressure, match="RESPONSE_AUDIO_BUFFER_FULL"):
        transport.send_audio(WireAudioFrame(1, 2, 0, 1, 183, b"\x00\x01"))
    transport.acknowledge_server(2)
    output = transport.send_audio(WireAudioFrame(1, 2, 0, 1, 183, b"\x00\x01"))

    assert output.binary is not None


@pytest.mark.asyncio
async def test_audio_capacity_waits_for_target_response_ack_and_sends_same_next_seq() -> None:
    transport = session(max_replay_bytes=4_000_000)
    start_stream(transport)
    payload = b"\x00\x01" * 8_000
    for seq in range(2, 92):
        transport.send_audio(WireAudioFrame(1, 2, 0, 1, seq, payload))
    frame = WireAudioFrame(1, 2, 0, 1, 92, b"\x00\x01")
    wire_bytes = len(BinaryAudioFrameCodec().encode(frame))
    waiter = asyncio.create_task(transport.wait_for_audio_capacity("response-1", wire_bytes, 2))
    await asyncio.sleep(0)
    assert not waiter.done()

    transport.acknowledge_server(2)
    await waiter
    output = transport.send_audio(frame)

    assert output.binary is not None
    assert transport.last_server_seq == 92


@pytest.mark.asyncio
async def test_audio_capacity_retirement_wakes_waiter() -> None:
    transport = session(max_replay_bytes=4_000_000)
    start_stream(transport)
    payload = b"\x00\x01" * 8_000
    for seq in range(2, 92):
        transport.send_audio(WireAudioFrame(1, 2, 0, 1, seq, payload))
    frame = WireAudioFrame(1, 2, 0, 1, 93, b"\x00\x01")
    waiter = asyncio.create_task(
        transport.wait_for_audio_capacity("response-1", len(BinaryAudioFrameCodec().encode(frame)), 2)
    )
    await asyncio.sleep(0)

    transport.send_control(
        {
            "protocol": "call.v1",
            "type": "playback.stop",
            "seq": 92,
            "call_id": CALL_ID,
            "response_id": "response-1",
            "stream_id": 1,
            "retire_server_seq": {"from": 1, "through": 91},
            "reason": "user_interrupted",
        }
    )

    await waiter


@pytest.mark.asyncio
async def test_other_response_ack_only_spuriously_wakes_then_target_wait_continues() -> None:
    transport = session(max_replay_bytes=4_000_000)
    start_stream(transport, stream_id=2, response_id="response-2")
    transport.send_audio(WireAudioFrame(1, 2, 0, 2, 2, b"\x00\x01"))
    start_stream(transport, seq=3)
    payload = b"\x00\x01" * 8_000
    for seq in range(4, 94):
        transport.send_audio(WireAudioFrame(1, 2, 0, 1, seq, payload))
    frame = WireAudioFrame(1, 2, 0, 1, 94, b"\x00\x01")
    waiter = asyncio.create_task(
        transport.wait_for_audio_capacity("response-1", len(BinaryAudioFrameCodec().encode(frame)), 2)
    )
    await asyncio.sleep(0)

    transport.acknowledge_server(2)
    await asyncio.sleep(0)
    assert not waiter.done()
    transport.acknowledge_server(4)
    await waiter


@pytest.mark.asyncio
async def test_audio_capacity_close_wakes_with_transport_closed() -> None:
    transport = session(max_replay_bytes=4_000_000)
    start_stream(transport)
    payload = b"\x00\x01" * 8_000
    for seq in range(2, 92):
        transport.send_audio(WireAudioFrame(1, 2, 0, 1, seq, payload))
    waiter = asyncio.create_task(transport.wait_for_audio_capacity("response-1", 17, 2))
    await asyncio.sleep(0)

    transport.close()

    with pytest.raises(CallTransportError, match="TRANSPORT_CLOSED"):
        await waiter


@pytest.mark.asyncio
async def test_audio_capacity_rejects_impossible_requests_without_waiting() -> None:
    transport = session(max_replay_bytes=300)
    start_stream(transport)

    with pytest.raises(ValueError, match="wire_bytes can never fit"):
        await transport.wait_for_audio_capacity("response-1", 301, 2)
    with pytest.raises(ValueError, match="payload_bytes can never fit"):
        await transport.wait_for_audio_capacity("response-1", 17, 1_440_002)


def test_stream_rejects_every_frame_after_final_without_advancing_seq() -> None:
    transport = session()
    transport.send_control(
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
    final = transport.send_audio(WireAudioFrame(1, 2, 1, 1, 2, b"\x00\x01"))

    for flags in (0, 1):
        with pytest.raises(CallTransportError, match="STREAM_ALREADY_FINAL"):
            transport.send_audio(WireAudioFrame(1, 2, flags, 1, 3, b"\x00\x01"))

    assert transport.last_server_seq == 2
    assert transport.replay_after(0)[-1] == final


@pytest.mark.asyncio
async def test_acceptance_finishes_and_commits_before_cancellation_propagates() -> None:
    accepted = asyncio.Event()
    release = asyncio.Event()
    receipts: list[CallAcceptanceReceipt] = []

    class CancelSink:
        async def accept(self, frame, receipt):
            del frame
            receipts.append(receipt)
            accepted.set()
            await release.wait()
            return True

    transport = session(CancelSink())
    task = asyncio.create_task(transport.receive_text(hangup(1)))
    await accepted.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert transport.client_cursor == 1
    assert receipts[0].call_id == CALL_ID
    assert receipts[0].direction == "client_to_server"
    assert message((await transport.receive_text(hangup(1)))[0])["ack_seq"] == 1
    assert len(receipts) == 1


@pytest.mark.asyncio
async def test_close_clears_state_and_wakes_backpressure_waiter() -> None:
    transport = session(max_replay_bytes=200)
    transport.send_control(
        {
            "protocol": "call.v1",
            "type": "call.state",
            "seq": 1,
            "call_id": CALL_ID,
            "client_request_id": "request-1",
            "state": "preparing",
        }
    )
    waiter = asyncio.create_task(transport.wait_for_replay_capacity(150))
    await asyncio.sleep(0)
    transport.close()

    with pytest.raises(CallTransportError, match="TRANSPORT_CLOSED"):
        await waiter
    with pytest.raises(CallTransportError, match="TRANSPORT_CLOSED"):
        transport.replay_after(0)


def test_retirement_rejects_other_stream_and_stream_id_cannot_be_reused() -> None:
    transport = session()
    for seq, stream_id, response_id in ((1, 1, "response-1"), (2, 2, "response-2")):
        transport.send_control(
            {
                "protocol": "call.v1",
                "type": "audio.stream_started",
                "seq": seq,
                "call_id": CALL_ID,
                "audio_route": "CALL",
                "stream_id": stream_id,
                "response_id": response_id,
                "encoding": "pcm_s16le",
                "sample_rate": 24000,
                "channels": 1,
            }
        )

    with pytest.raises(CallTransportError, match="INVALID_RETIRE_RANGE"):
        transport.send_control(
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
    with pytest.raises(CallTransportError, match="STREAM_ID_CONFLICT"):
        transport.send_control(
            {
                "protocol": "call.v1",
                "type": "audio.stream_started",
                "seq": 3,
                "call_id": CALL_ID,
                "audio_route": "CALL",
                "stream_id": 1,
                "response_id": "response-3",
                "encoding": "pcm_s16le",
                "sample_rate": 24000,
                "channels": 1,
            }
        )
