import asyncio
import base64
from uuid import uuid4

import pytest
from support.aliyun_realtime_speech import FakeAliyunConnector, FakeAliyunWebSocket

from src.infrastructure.models.realtime_speech import (
    AliyunRealtimeSpeechConfig,
    AliyunRealtimeSpeechSessionFactory,
    AmbientAudio,
    AudioFrame,
    ProviderFailed,
    RealtimeSpeechConfig,
    SpeechStarted,
    SpeechStopped,
    TurnCompleted,
    TurnInvalid,
)


def provider_config(**overrides):
    values = {
        "api_key": "test-only-key",
        "model": "configured-model",
        "workspace_id": "workspace",
        "session_timeout_seconds": 0.5,
        "close_timeout_seconds": 0.5,
        "cleanup_timeout_seconds": 0.02,
        "write_queue_size": 2,
        "max_audio_frame_bytes": 8,
    }
    values.update(overrides)
    return AliyunRealtimeSpeechConfig(**values)


async def started_session(socket=None, **config_overrides):
    socket = socket or FakeAliyunWebSocket()
    factory = AliyunRealtimeSpeechSessionFactory(
        provider_config(**config_overrides), connector=FakeAliyunConnector(socket)
    )
    session = await factory.create(uuid4())
    await session.start(RealtimeSpeechConfig(language="zh"))
    return session, socket


@pytest.mark.asyncio
async def test_real_adapter_handshake_and_pcm_base64_schema():
    session, socket = await started_session()
    payload = b"\x00\x01\x02\x03"

    await session.push_audio(AudioFrame(payload, "pcm_s16le", 16_000, 1, sequence=99))
    await wait_for_sent_type(socket, "input_audio_buffer.append")

    assert socket.sent[0] == {
        "type": "session.update",
        "session": {
            "modalities": ["text", "audio"],
            "input_audio_format": "pcm",
            "output_audio_format": "pcm",
            "turn_detection": {"type": "smart_turn"},
            "input_audio_transcription": {"language": "zh"},
        },
    }
    assert socket.sent[1] == {
        "type": "input_audio_buffer.append",
        "audio": base64.b64encode(payload).decode("ascii"),
    }
    assert "sequence" not in socket.sent[1]

    with pytest.raises(ValueError, match="16 kHz mono PCM16"):
        await session.push_audio(AudioFrame(b"\x00\x00", "pcm_s16le", 48_000, 1))
    with pytest.raises(ValueError, match="complete samples"):
        await session.push_audio(AudioFrame(b"\x00", "pcm_s16le", 16_000, 1))
    with pytest.raises(ValueError, match="size limit"):
        await session.push_audio(AudioFrame(b"\x00\x00" * 5, "pcm_s16le", 16_000, 1))
    await session.close()


@pytest.mark.asyncio
async def test_normalizes_only_final_user_and_ambient_transcripts():
    session, socket = await started_session()
    events = session.events()
    await socket.server_event({"type": "input_audio_buffer.speech_started", "item_id": "user-1"})
    await socket.server_event({"type": "input_audio_buffer.speech_stopped", "item_id": "user-1"})
    await socket.server_event(
        {
            "type": "conversation.item.input_audio_transcription.delta",
            "item_id": "user-1",
            "delta": "not-final",
        }
    )
    await socket.server_event(
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "item_id": "user-1",
            "transcript": " 你好 ",
        }
    )
    await socket.server_event(
        {
            "type": "conversation.item.ambient_audio_transcription.completed",
            "item_id": "ambient-1",
            "transcript": " 门铃声 ",
        }
    )

    assert isinstance(await asyncio.wait_for(anext(events), 0.5), SpeechStarted)
    assert isinstance(await asyncio.wait_for(anext(events), 0.5), SpeechStopped)
    completed = await asyncio.wait_for(anext(events), 0.5)
    ambient = await asyncio.wait_for(anext(events), 0.5)
    assert isinstance(completed, TurnCompleted)
    assert completed.semantic.transcript == "你好"
    assert completed.semantic.emotion is None
    assert completed.semantic.sound_description is None
    assert ambient == AmbientAudio("门铃声")
    await session.close()


@pytest.mark.asyncio
async def test_invalid_duplicate_late_and_empty_transcripts_do_not_complete_turns():
    session, socket = await started_session()
    events = session.events()
    await socket.server_event(
        {"type": "input_audio_buffer.speech_stopped", "item_id": "invalid", "reason": "turn_invalid"}
    )
    await socket.server_event(
        {"type": "input_audio_buffer.speech_stopped", "item_id": "invalid", "reason": "turn_invalid"}
    )
    await socket.server_event(
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "item_id": "invalid",
            "transcript": "must-not-leak",
        }
    )
    await socket.server_event(
        {"type": "conversation.item.input_audio_transcription.completed", "item_id": "empty", "transcript": " "}
    )
    await socket.server_event(
        {"type": "conversation.item.input_audio_transcription.completed", "item_id": "valid", "transcript": "one"}
    )
    await socket.server_event(
        {"type": "conversation.item.input_audio_transcription.completed", "item_id": "valid", "transcript": "duplicate"}
    )

    assert await asyncio.wait_for(anext(events), 0.5) == TurnInvalid("turn_invalid")
    assert await asyncio.wait_for(anext(events), 0.5) == TurnInvalid("empty_transcript")
    completed = await asyncio.wait_for(anext(events), 0.5)
    assert isinstance(completed, TurnCompleted)
    assert completed.semantic.transcript == "one"
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(anext(events), 0.02)
    await session.close()


@pytest.mark.asyncio
async def test_assistant_output_is_cancelled_once_deleted_and_never_emitted():
    session, socket = await started_session()
    events = session.events()
    await socket.server_event({"type": "response.created", "response": {"id": "response-1"}})
    await socket.server_event({"type": "response.created", "response": {"id": "response-1"}})
    await socket.server_event(
        {
            "type": "response.output_item.added",
            "response_id": "response-1",
            "item": {"id": "assistant-1", "role": "assistant", "content": [{"text": "secret reply"}]},
        }
    )
    await socket.server_event(
        {
            "type": "response.text.delta",
            "response_id": "response-1",
            "item_id": "assistant-1",
            "delta": "must never leave the adapter",
        }
    )
    await wait_for_sent_type(socket, "conversation.item.delete")
    await socket.server_event({"type": "conversation.item.deleted", "item_id": "assistant-1"})
    await socket.server_event(
        {
            "type": "response.output_item.done",
            "response_id": "response-1",
            "item": {"id": "assistant-1", "role": "assistant"},
        }
    )
    await socket.server_event({"type": "conversation.item.created", "item": {"id": "assistant-1", "role": "assistant"}})
    await socket.server_event(
        {
            "type": "response.done",
            "response": {
                "id": "response-1",
                "status": "cancelled",
                "usage": {"total_tokens": 7, "input_tokens": 5, "output_tokens": 2, "content": "ignored"},
            },
        }
    )
    await wait_for_condition(lambda: session.usage_totals.get("total_tokens") == 7)

    assert [message for message in socket.sent if message["type"] == "response.cancel"] == [{"type": "response.cancel"}]
    assert [message for message in socket.sent if message["type"] == "conversation.item.delete"] == [
        {"type": "conversation.item.delete", "item_id": "assistant-1"}
    ]
    assert session.usage_totals == {"total_tokens": 7, "input_tokens": 5, "output_tokens": 2}
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(anext(events), 0.02)
    await session.close()


@pytest.mark.asyncio
async def test_uncertain_assistant_cleanup_fails_closed():
    session, socket = await started_session()
    events = session.events()
    await socket.server_event({"type": "response.created", "response": {"id": "response-1"}})
    await socket.server_event(
        {
            "type": "response.output_item.added",
            "response_id": "response-1",
            "item": {"id": "assistant-1", "role": "assistant"},
        }
    )
    await socket.server_event({"type": "response.done", "response": {"id": "response-1", "status": "cancelled"}})
    assert await asyncio.wait_for(anext(events), 0.5) == ProviderFailed("provider_assistant_cleanup_timeout", False)
    await wait_for_condition(lambda: socket.closed)
    await session.close()


async def wait_for_sent_type(socket, event_type, timeout=0.5):
    async def wait():
        while not any(message.get("type") == event_type for message in socket.sent):
            await asyncio.sleep(0)

    await asyncio.wait_for(wait(), timeout)


async def wait_for_condition(predicate, timeout=0.5):
    async def wait():
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(wait(), timeout)


@pytest.mark.asyncio
async def test_error_abnormal_close_and_factory_sessions_are_isolated():
    first_socket = FakeAliyunWebSocket()
    second_socket = FakeAliyunWebSocket()
    connector = FakeAliyunConnector(first_socket, second_socket)
    factory = AliyunRealtimeSpeechSessionFactory(provider_config(), connector=connector)
    first = await factory.create(uuid4())
    second = await factory.create(uuid4())
    await first.start(RealtimeSpeechConfig())
    await second.start(RealtimeSpeechConfig())
    assert first is not second

    first_events = first.events()
    second_events = second.events()
    await first_socket.server_event({"type": "error", "error": {"type": "server_error", "message": "sensitive"}})
    await second_socket.abnormal_close()

    assert await asyncio.wait_for(anext(first_events), 0.5) == ProviderFailed("provider_server_error", True)
    assert await asyncio.wait_for(anext(second_events), 0.5) == ProviderFailed("provider_connection_closed", True)
    await first.close()
    await second.close()


@pytest.mark.asyncio
async def test_bounded_write_queue_applies_backpressure_and_close_releases_tasks():
    socket = FakeAliyunWebSocket(block_sends=True)
    connector = FakeAliyunConnector(socket)
    session = await AliyunRealtimeSpeechSessionFactory(provider_config(write_queue_size=1), connector=connector).create(
        uuid4()
    )
    start_task = asyncio.create_task(session.start(RealtimeSpeechConfig()))
    await socket.send_started.wait()
    socket.release_sends.set()
    await start_task

    socket.release_sends.clear()
    socket.send_started.clear()
    first = asyncio.create_task(session.push_audio(AudioFrame(b"\x00\x00", "pcm_s16le", 16_000, 1)))
    await socket.send_started.wait()
    second = asyncio.create_task(session.push_audio(AudioFrame(b"\x00\x00", "pcm_s16le", 16_000, 1)))
    await asyncio.wait_for(first, 0.5)
    await asyncio.wait_for(second, 0.5)
    third = asyncio.create_task(session.push_audio(AudioFrame(b"\x00\x00", "pcm_s16le", 16_000, 1)))
    await asyncio.sleep(0)
    assert not third.done()

    await session.close()
    await asyncio.gather(first, second, third, return_exceptions=True)
    await session.close()
    assert socket.closed


@pytest.mark.asyncio
async def test_cancelled_start_closes_owned_socket_without_leaking_tasks():
    socket = FakeAliyunWebSocket(block_sends=True)
    session = await AliyunRealtimeSpeechSessionFactory(provider_config(), connector=FakeAliyunConnector(socket)).create(
        uuid4()
    )
    task = asyncio.create_task(session.start(RealtimeSpeechConfig()))
    await socket.send_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert socket.closed


@pytest.mark.asyncio
async def test_session_update_timeout_fails_start_and_closes_socket():
    socket = FakeAliyunWebSocket(acknowledge_session=False)
    session = await AliyunRealtimeSpeechSessionFactory(
        provider_config(session_timeout_seconds=0.01), connector=FakeAliyunConnector(socket)
    ).create(uuid4())

    with pytest.raises(RuntimeError, match="initialization failed"):
        await session.start(RealtimeSpeechConfig())
    assert socket.closed


@pytest.mark.asyncio
async def test_two_responses_cleanup_is_scoped_and_done_allows_late_delete_ack():
    session, socket = await started_session(cleanup_timeout_seconds=0.1)
    events = session.events()
    for response_id in ("response-a", "response-b"):
        await socket.server_event({"type": "response.created", "response": {"id": response_id}})
        await socket.server_event(
            {
                "type": "response.output_item.added",
                "response_id": response_id,
                "item": {"id": f"item-{response_id[-1]}", "role": "assistant"},
            }
        )
    await wait_for_sent_count(socket, "conversation.item.delete", 2)
    await socket.server_event({"type": "response.done", "response": {"id": "response-a", "status": "cancelled"}})
    await socket.server_event({"type": "conversation.item.deleted", "item_id": "item-a"})
    await socket.server_event({"type": "conversation.item.deleted", "item_id": "wrong-item"})
    await socket.server_event({"type": "conversation.item.deleted", "item_id": "item-a"})
    await socket.server_event({"type": "response.done", "response": {"id": "response-b", "status": "cancelled"}})
    await socket.server_event({"type": "conversation.item.deleted", "item_id": "item-b"})

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(anext(events), 0.12)
    await session.close()


@pytest.mark.asyncio
async def test_done_then_late_assistant_item_is_deleted_and_acknowledged():
    session, socket = await started_session(cleanup_timeout_seconds=0.1)
    events = session.events()
    await socket.server_event({"type": "response.created", "response": {"id": "response-1"}})
    await socket.server_event({"type": "response.done", "response": {"id": "response-1", "status": "cancelled"}})
    await socket.server_event(
        {
            "type": "response.output_item.done",
            "response_id": "response-1",
            "item": {"id": "late-item", "role": "assistant"},
        }
    )
    await wait_for_sent_type(socket, "conversation.item.delete")
    await socket.server_event({"type": "conversation.item.deleted", "item_id": "late-item"})

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(anext(events), 0.12)
    await session.close()


@pytest.mark.asyncio
async def test_done_then_late_assistant_item_without_ack_times_out():
    session, socket = await started_session(cleanup_timeout_seconds=0.01)
    events = session.events()
    await socket.server_event({"type": "response.created", "response": {"id": "response-1"}})
    await socket.server_event({"type": "response.done", "response": {"id": "response-1", "status": "cancelled"}})
    await socket.server_event(
        {
            "type": "response.output_item.done",
            "response_id": "response-1",
            "item": {"id": "late-item", "role": "assistant"},
        }
    )
    await wait_for_sent_type(socket, "conversation.item.delete")

    assert await asyncio.wait_for(anext(events), 0.5) == ProviderFailed("provider_assistant_cleanup_timeout", False)
    await session.close()


@pytest.mark.asyncio
async def test_unknown_assistant_delta_fails_closed_without_user_event():
    session, socket = await started_session()
    events = session.events()
    await socket.server_event(
        {"type": "response.text.delta", "response_id": "unknown", "item_id": "unknown-item", "delta": "hidden"}
    )

    assert await asyncio.wait_for(anext(events), 0.5) == ProviderFailed("provider_assistant_context_uncertain", False)
    with pytest.raises(StopAsyncIteration):
        await anext(events)
    await session.close()


@pytest.mark.asyncio
async def test_unknown_conversation_assistant_item_fails_closed_but_known_duplicate_is_safe():
    session, socket = await started_session()
    events = session.events()
    await socket.server_event(
        {"type": "conversation.item.created", "item": {"id": "unknown-item", "role": "assistant"}}
    )

    assert await asyncio.wait_for(anext(events), 0.5) == ProviderFailed("provider_assistant_context_uncertain", False)
    with pytest.raises(StopAsyncIteration):
        await anext(events)
    await session.close()


@pytest.mark.asyncio
async def test_output_for_retired_response_fails_closed_and_suppresses_late_user_turn():
    session, socket = await started_session(cleanup_timeout_seconds=0.01)
    events = session.events()
    await socket.server_event({"type": "response.created", "response": {"id": "response-1"}})
    await socket.server_event({"type": "response.done", "response": {"id": "response-1", "status": "cancelled"}})
    await wait_for_condition(lambda: "response-1" in session._retired_responses)
    await socket.server_event(
        {
            "type": "response.output_item.added",
            "response_id": "response-1",
            "item": {"id": "impossible-late-item", "role": "assistant"},
        }
    )
    await socket.server_event(
        {"type": "conversation.item.input_audio_transcription.completed", "item_id": "user", "transcript": "late"}
    )

    assert await asyncio.wait_for(anext(events), 0.5) == ProviderFailed("provider_assistant_context_uncertain", False)
    with pytest.raises(StopAsyncIteration):
        await anext(events)
    await session.close()


@pytest.mark.asyncio
async def test_full_event_queue_close_and_failure_emit_one_terminal_without_deadlock():
    session, socket = await started_session(event_queue_size=1, close_timeout_seconds=0.02)
    events = session.events()
    await socket.server_event(
        {"type": "conversation.item.input_audio_transcription.completed", "item_id": "user", "transcript": "kept"}
    )
    await wait_for_condition(lambda: len(session._event_buffer) == 1)
    await socket.server_event({"type": "error", "error": {"type": "server_error"}})

    completed = await asyncio.wait_for(anext(events), 0.5)
    assert isinstance(completed, TurnCompleted)
    assert completed.semantic.transcript == "kept"
    assert await asyncio.wait_for(anext(events), 0.5) == ProviderFailed("provider_server_error", True)
    with pytest.raises(StopAsyncIteration):
        await anext(events)
    await asyncio.wait_for(session.close(), 0.1)


@pytest.mark.asyncio
async def test_invalid_and_completed_events_keep_order_before_single_failure():
    session, socket = await started_session(event_queue_size=2)
    events = session.events()
    await socket.server_event(
        {"type": "input_audio_buffer.speech_stopped", "item_id": "invalid", "reason": "turn_invalid"}
    )
    await socket.server_event(
        {"type": "conversation.item.input_audio_transcription.completed", "item_id": "valid", "transcript": "kept"}
    )
    await wait_for_condition(lambda: len(session._event_buffer) == 2)
    await socket.server_event({"type": "error", "error": {"type": "server_error"}})
    await socket.server_event({"type": "error", "error": {"type": "server_error"}})

    assert await asyncio.wait_for(anext(events), 0.5) == TurnInvalid("turn_invalid")
    completed = await asyncio.wait_for(anext(events), 0.5)
    assert isinstance(completed, TurnCompleted)
    assert completed.semantic.transcript == "kept"
    assert await asyncio.wait_for(anext(events), 0.5) == ProviderFailed("provider_server_error", True)
    with pytest.raises(StopAsyncIteration):
        await anext(events)
    await session.close()


@pytest.mark.asyncio
async def test_full_event_queue_close_drains_business_event_and_releases_tasks():
    session, socket = await started_session(event_queue_size=1, close_timeout_seconds=0.02)
    events = session.events()
    await socket.server_event(
        {"type": "conversation.item.input_audio_transcription.completed", "item_id": "user", "transcript": "kept"}
    )
    await wait_for_condition(lambda: len(session._event_buffer) == 1)

    await asyncio.wait_for(session.close(), 0.1)
    completed = await asyncio.wait_for(anext(events), 0.5)
    assert isinstance(completed, TurnCompleted)
    assert completed.semantic.transcript == "kept"
    with pytest.raises(StopAsyncIteration):
        await anext(events)
    assert all(task is None or task.done() for task in (session._reader, session._writer, session._cleanup))


@pytest.mark.asyncio
async def test_socket_close_timeout_bounds_shutdown():
    socket = FakeAliyunWebSocket(block_close=True)
    session, _ = await started_session(socket, close_timeout_seconds=0.01)

    await asyncio.wait_for(session.close(), 0.1)
    assert socket.close_started.is_set()
    assert all(task is None or task.done() for task in (session._reader, session._writer, session._cleanup))


@pytest.mark.asyncio
async def test_writer_failure_wins_race_with_reader_close_once():
    socket = FakeAliyunWebSocket(fail_send_type="input_audio_buffer.append")
    session, _ = await started_session(socket)
    events = session.events()
    with pytest.raises(RuntimeError, match="unavailable"):
        await session.push_audio(AudioFrame(b"\x00\x00", "pcm_s16le", 16_000, 1))
    await socket.abnormal_close()

    failure = await asyncio.wait_for(anext(events), 0.5)
    assert isinstance(failure, ProviderFailed)
    assert failure.error_code in {"provider_write_failed", "provider_connection_closed"}
    with pytest.raises(StopAsyncIteration):
        await anext(events)
    await session.close()


@pytest.mark.asyncio
async def test_cancelled_empty_event_wait_leaves_no_waiter_and_next_consumer_gets_turn():
    session, socket = await started_session()
    first_events = session.events()
    waiting = asyncio.create_task(anext(first_events))
    await asyncio.sleep(0)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    await first_events.aclose()

    await socket.server_event(
        {"type": "conversation.item.input_audio_transcription.completed", "item_id": "user", "transcript": "kept"}
    )
    second_events = session.events()
    completed = await asyncio.wait_for(anext(second_events), 0.5)
    assert isinstance(completed, TurnCompleted)
    assert completed.semantic.transcript == "kept"
    await second_events.aclose()
    assert not session._event_consumer_active
    await session.close()


@pytest.mark.asyncio
async def test_cancel_racing_dequeue_requeues_event_once_in_fifo_order():
    session, socket = await started_session()
    first_events = session.events()
    delivery = asyncio.create_task(anext(first_events))
    await asyncio.sleep(0)
    await socket.server_event(
        {"type": "conversation.item.input_audio_transcription.completed", "item_id": "one", "transcript": "one"}
    )
    await socket.server_event(
        {"type": "conversation.item.input_audio_transcription.completed", "item_id": "two", "transcript": "two"}
    )
    delivery.cancel()
    delivered = []
    try:
        first = await delivery
    except asyncio.CancelledError:
        pass
    else:
        assert isinstance(first, TurnCompleted)
        delivered.append(first.semantic.transcript)
    await first_events.aclose()

    second_events = session.events()
    while len(delivered) < 2:
        event = await asyncio.wait_for(anext(second_events), 0.5)
        assert isinstance(event, TurnCompleted)
        delivered.append(event.semantic.transcript)
    assert delivered == ["one", "two"]
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(anext(second_events), 0.02)
    await second_events.aclose()
    await session.close()


@pytest.mark.asyncio
async def test_cancel_then_failure_new_consumer_drains_fifo_failure_and_stop():
    session, socket = await started_session(event_queue_size=2)
    first_events = session.events()
    waiting = asyncio.create_task(anext(first_events))
    await asyncio.sleep(0)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    await first_events.aclose()

    await socket.server_event(
        {"type": "input_audio_buffer.speech_stopped", "item_id": "invalid", "reason": "turn_invalid"}
    )
    await socket.server_event(
        {"type": "conversation.item.input_audio_transcription.completed", "item_id": "valid", "transcript": "kept"}
    )
    await wait_for_condition(lambda: len(session._event_buffer) == 2)
    await socket.server_event({"type": "error", "error": {"type": "server_error"}})

    second_events = session.events()
    assert await asyncio.wait_for(anext(second_events), 0.5) == TurnInvalid("turn_invalid")
    completed = await asyncio.wait_for(anext(second_events), 0.5)
    assert isinstance(completed, TurnCompleted)
    assert completed.semantic.transcript == "kept"
    assert await asyncio.wait_for(anext(second_events), 0.5) == ProviderFailed("provider_server_error", True)
    with pytest.raises(StopAsyncIteration):
        await anext(second_events)
    await session.close()


@pytest.mark.asyncio
async def test_concurrent_event_consumer_is_stably_rejected():
    session, _socket = await started_session()
    first_events = session.events()
    waiting = asyncio.create_task(anext(first_events))
    await asyncio.sleep(0)
    second_events = session.events()
    with pytest.raises(RuntimeError, match="one consumer"):
        await anext(second_events)

    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    await first_events.aclose()
    await second_events.aclose()
    await session.close()


async def wait_for_sent_count(socket, event_type, count, timeout=0.5):
    await wait_for_condition(
        lambda: len([message for message in socket.sent if message.get("type") == event_type]) >= count,
        timeout,
    )
