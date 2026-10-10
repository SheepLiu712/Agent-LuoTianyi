import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

from src.adapter.websocket.call_v1 import (
    BinaryAudioFrameCodec,
    CallStageBinding,
    CallTransportConfig,
    CallTransportSession,
    WireAudioFrame,
)
from src.domain.agent import CALL_PCM_FORMAT
from src.domain.call import (
    CallEndReason,
    CallFinalSnapshot,
    CallOutcome,
    CallState,
    CallTerminalFacts,
)
from src.stage.call_stage import CallStateChanged


class _Stage:
    snapshot = None
    _ownership = SimpleNamespace(client_request_id="request")
    _record = SimpleNamespace(connected_at=None)

    def __init__(self):
        self.pcm = []
        self.completed = []
        self.stopped = []
        self._playback = SimpleNamespace(pending_streams=())

    def accept_pcm(self, receipt, payload):
        self.pcm.append((receipt, payload))
        return True

    def playback_completed(self, response_id, stream_id):
        self.completed.append((response_id, stream_id))

    def playback_stopped(self, response_id, stream_id):
        self.stopped.append((response_id, stream_id))
        return True


@pytest.mark.asyncio
async def test_real_binding_uses_one_transport_sequence_for_control_and_audio_and_preserves_receipt():
    delivered = []

    async def deliver(output):
        delivered.append(output)

    binding = CallStageBinding(call_id="606ec5e6-a330-4e6c-b07a-8432a5716c8f", deliver=deliver)
    session = CallTransportSession(
        call_id=binding.call_id,
        user_id="user",
        character_id="luotianyi",
        sink=binding,
    )
    stage = _Stage()
    binding.bind(stage=stage, session=session)

    await binding.start_stream("response", 1, CALL_PCM_FORMAT)
    await binding.send_pcm("response", 1, b"\x00\x01", final=True)

    started = json.loads(delivered[0].text)
    audio = BinaryAudioFrameCodec().decode(delivered[1].binary)
    assert started["seq"] == 1
    assert audio.seq == 2
    assert audio.flags == 1

    control = json.dumps(
        {
            "protocol": "call.v1",
            "type": "playback.completed",
            "seq": 1,
            "call_id": binding.call_id,
            "response_id": "response",
            "stream_id": 1,
        }
    )
    await session.receive_text(control)
    raw = BinaryAudioFrameCodec().encode(WireAudioFrame(1, 2, 0, 0, 2, b"\x02\x03"))
    await session.receive_binary(raw)

    assert stage.completed == [("response", 1)]
    receipt, payload = stage.pcm[0]
    assert receipt.seq == 2
    assert receipt.fingerprint
    assert payload == b"\x02\x03"


@pytest.mark.asyncio
async def test_binding_backpressure_blocks_without_consuming_additional_pcm():
    delivered = []

    async def deliver(output):
        delivered.append(output)

    binding = CallStageBinding(call_id="606ec5e6-a330-4e6c-b07a-8432a5716c8f", deliver=deliver)
    session = CallTransportSession(
        call_id=binding.call_id,
        user_id="user",
        character_id="luotianyi",
        sink=binding,
        config=CallTransportConfig(max_replay_bytes=500),
    )
    binding.bind(stage=_Stage(), session=session)
    await binding.start_stream("response", 1, CALL_PCM_FORMAT)
    first = asyncio.create_task(binding.send_pcm("response", 1, b"\x00\x01" * 80, final=False))
    await first
    blocked = asyncio.create_task(binding.send_pcm("response", 1, b"\x02\x03" * 80, final=True))
    for _ in range(100):
        if not session._replay_capacity_event.is_set():
            break
        await asyncio.sleep(0)
    assert not blocked.done()
    assert not session._replay_capacity_event.is_set()
    session.acknowledge_server(2)
    await asyncio.wait_for(blocked, 1)
    assert len(delivered) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [CallState.ENDING, CallState.DECLINED, CallState.FAILED])
async def test_binding_does_not_encode_internal_or_terminal_states_as_call_state(state):
    delivered = []

    async def deliver(output):
        delivered.append(output)

    binding = CallStageBinding(call_id="606ec5e6-a330-4e6c-b07a-8432a5716c8f", deliver=deliver)
    session = CallTransportSession(
        call_id=binding.call_id,
        user_id="user",
        character_id="luotianyi",
        sink=binding,
    )
    binding.bind(stage=_Stage(), session=session)

    await binding.send_state(CallStateChanged(binding.call_id, state))

    assert delivered == []
    assert session.next_server_seq == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "reason", "duration"),
    [
        (CallOutcome.CONNECTED, CallEndReason.AGENT_HANGUP, 1200),
        (CallOutcome.DECLINED, CallEndReason.DECLINED, 0),
        (CallOutcome.CANCELLED_BEFORE_ANSWER, CallEndReason.USER_HANGUP, 0),
    ],
)
async def test_binding_sends_frozen_terminal_facts_exactly_once(outcome, reason, duration):
    delivered = []

    async def deliver(output):
        delivered.append(output)

    binding = CallStageBinding(call_id="606ec5e6-a330-4e6c-b07a-8432a5716c8f", deliver=deliver)
    session = CallTransportSession(
        call_id=binding.call_id,
        user_id="user",
        character_id="luotianyi",
        sink=binding,
    )
    binding.bind(stage=_Stage(), session=session)
    snapshot = CallFinalSnapshot(
        CallTerminalFacts(UUID(binding.call_id), outcome, reason, duration, datetime.now(timezone.utc)),
        (),
        0,
    )

    await binding.send_ended(snapshot)
    await binding.send_ended(snapshot)

    assert [_message["type"] for _message in map(lambda item: json.loads(item.text), delivered)] == ["call.ended"]
    terminal = json.loads(delivered[0].text)
    assert terminal["outcome"] == outcome.value
    assert terminal["end_reason"] == reason.value
    assert terminal["active_duration_ms"] == duration
    assert terminal["seq"] == 1


@pytest.mark.asyncio
async def test_binding_setup_failure_uses_nonrecordable_error_without_consuming_sequence():
    delivered = []

    async def deliver(output):
        delivered.append(output)

    binding = CallStageBinding(call_id="606ec5e6-a330-4e6c-b07a-8432a5716c8f", deliver=deliver)
    session = CallTransportSession(
        call_id=binding.call_id,
        user_id="user",
        character_id="luotianyi",
        sink=binding,
    )
    binding.bind(stage=_Stage(), session=session)

    await binding.send_failed(CallEndReason.SYSTEM_FAILURE)
    await binding.send_failed(CallEndReason.SYSTEM_FAILURE)

    failure = json.loads(delivered[0].text)
    assert failure["type"] == "error"
    assert failure["code"] == "CALL_SETUP_FAILED"
    assert failure["retryable"] is False
    assert len(delivered) == 1
    assert session.next_server_seq == 1
