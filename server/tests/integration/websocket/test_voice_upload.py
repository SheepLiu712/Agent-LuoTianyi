import asyncio
import base64
import json
import struct
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from fastapi import WebSocketDisconnect

import src.domain.agent as d
from src.adapter.websocket import WebSocketAdapter
from src.web.websocket.endpoint import _receive_events
from src.web.websocket.service import WebSocketConnection, WebSocketService


def _atom(atom_type: bytes, payload: bytes = b"") -> bytes:
    return struct.pack(">I4s", len(payload) + 8, atom_type) + payload


def _descriptor(tag: int, payload: bytes) -> bytes:
    return bytes((tag, len(payload))) + payload


def m4a_bytes(*, duration_ms: int = 1234, codec_config: bytes = b"\x12\x10") -> bytes:
    decoder_specific = _descriptor(5, codec_config)
    decoder_config = _descriptor(4, b"\x40\x15" + b"\0\0\0" + struct.pack(">II", 128_000, 128_000) + decoder_specific)
    es_descriptor = _descriptor(3, struct.pack(">HB", 1, 0) + decoder_config)
    esds = _atom(b"esds", b"\0\0\0\0" + es_descriptor)
    sample_entry = _atom(
        b"mp4a",
        b"\0" * 6 + struct.pack(">H", 1) + b"\0" * 8 + struct.pack(">HHHHI", 2, 16, 0, 0, 44_100 << 16) + esds,
    )
    stsd = _atom(b"stsd", b"\0\0\0\0" + struct.pack(">I", 1) + sample_entry)
    mdhd = _atom(b"mdhd", b"\0\0\0\0" + struct.pack(">IIIIHH", 0, 0, 1000, duration_ms, 0, 0))
    hdlr = _atom(b"hdlr", b"\0" * 8 + b"soun" + b"\0" * 12)
    moov = _atom(b"moov", _atom(b"trak", _atom(b"mdia", mdhd + hdlr + _atom(b"minf", _atom(b"stbl", stsd)))))
    return _atom(b"ftyp", b"M4A " + struct.pack(">I", 0) + b"isomM4A ") + moov


class Socket:
    def __init__(self, events):
        self.events = list(events)
        self.sent = []

    async def receive_json(self):
        if self.events:
            return self.events.pop(0)
        raise WebSocketDisconnect()

    async def send_json(self, event):
        self.sent.append(event)


class Stage:
    def __init__(self, user_id="user-1"):
        self.interaction_id = str(uuid4())
        self.user_id = user_id
        self.character_id = "luotianyi"
        self.stimulus_input_sink = self
        self.stimuli = []
        self.available = True

    def can_accept(self, stimulus):
        return self.available

    def submit(self, stimulus):
        if not self.available:
            return False
        self.stimuli.append(stimulus)
        return True

    async def connection_changed(self, state):
        pass


def event(phase, upload_id, payload=None):
    return {
        "type": "user_voice",
        "client_msg_id": f"{upload_id}:{phase}",
        "payload": {"phase": phase, "upload_id": upload_id, **(payload or {})},
    }


async def run_events(tmp_path, events, *, adapter=None, user_id="user-1"):
    socket = Socket(events)
    connection = WebSocketConnection(socket, user_id, user_id)
    connection.capabilities.add("negative_ack_v1")
    adapter = adapter or WebSocketAdapter({"media_store": {"root": str(tmp_path / "media")}})
    stage = Stage(user_id)
    await adapter.bind(stage, connection)
    runtime = SimpleNamespace(
        websocket_service=WebSocketService(),
        chat_adapter=adapter,
        client_llm_executor=SimpleNamespace(),
    )
    try:
        with pytest.raises(WebSocketDisconnect):
            await _receive_events(runtime, connection)
        return socket.sent, stage, adapter
    finally:
        await adapter.disconnect(stage)


def upload_events(data, upload_id=None, *, order=None):
    upload_id = upload_id or str(uuid4())
    split = max(1, len(data) // 2)
    chunks = [data[:split], data[split:]]
    begin = event(
        "begin",
        upload_id,
        {"mime_type": "audio/mp4", "container": "m4a", "codec": "aac_lc", "byte_length": len(data), "total_chunks": 2},
    )
    chunk_events = [
        event("chunk", upload_id, {"chunk_index": index, "audio_base64": base64.b64encode(chunk).decode("ascii")})
        for index, chunk in enumerate(chunks)
    ]
    if order is not None:
        chunk_events = [chunk_events[index] for index in order]
    return upload_id, [begin, *chunk_events, event("finalize", upload_id)]


@pytest.mark.asyncio
async def test_voice_upload_success_out_of_order_and_finalize_replay(tmp_path):
    data = m4a_bytes()
    upload_id, events = upload_events(data, order=[1, 0])
    events.append(events[-1])
    sent, stage, _ = await run_events(tmp_path, events)

    assert all(item["type"] == "server_ack" for item in sent)
    assert [type(item) for item in stage.stimuli] == [d.VoiceRecordingCommitted, d.VoiceMessage]
    message = stage.stimuli[-1]
    expected_uuid = str(
        uuid5(
            NAMESPACE_URL,
            json.dumps(
                ["conversation-audio", "user-1", "luotianyi", upload_id],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
    )
    assert message.message_uuid == expected_uuid
    assert message.client_msg_id == upload_id
    assert message.duration_ms == 1234
    assert sent[-1]["payload"]["duplicate"] is True
    assert sent[-1]["payload"]["message_uuid"] == expected_uuid
    assert (tmp_path / "media" / message.media_ref.media_id / "content.bin").read_bytes() == data


@pytest.mark.asyncio
async def test_missing_chunk_can_be_retried_and_same_chunk_is_idempotent(tmp_path):
    data = m4a_bytes()
    upload_id, events = upload_events(data)
    begin, first, second, finalize = events
    sent, stage, _ = await run_events(tmp_path, [begin, first, first, finalize, second, finalize])

    assert sent[2]["payload"]["duplicate"] is True
    assert sent[3]["payload"]["code"] == "VOICE_MISSING_CHUNKS"
    assert sent[3]["payload"]["retryable"] is True
    assert isinstance(stage.stimuli[-1], d.VoiceMessage)


@pytest.mark.asyncio
async def test_chunk_conflict_and_invalid_base64_are_stable_nacks(tmp_path):
    data = m4a_bytes()
    upload_id, events = upload_events(data)
    begin, first, _, _ = events
    conflict = event(
        "chunk",
        upload_id,
        {"chunk_index": 0, "audio_base64": base64.b64encode(b"different").decode("ascii")},
    )
    invalid = event("chunk", upload_id, {"chunk_index": 1, "audio_base64": "%%%"})
    sent, stage, _ = await run_events(tmp_path, [begin, first, conflict, invalid])

    assert [item["payload"].get("code") for item in sent] == [None, None, "VOICE_UPLOAD_CONFLICT", "BAD_MESSAGE"]
    assert not any(isinstance(item, d.VoiceMessage) for item in stage.stimuli)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"mime_type": "audio/mpeg"}, "VOICE_UNSUPPORTED_MEDIA"),
        ({"container": "mp4"}, "VOICE_UNSUPPORTED_MEDIA"),
        ({"codec": "opus"}, "VOICE_UNSUPPORTED_MEDIA"),
        ({"byte_length": 1024 * 1024 + 1}, "VOICE_TOO_LARGE"),
        ({"total_chunks": 33}, "VOICE_TOO_LARGE"),
    ],
)
async def test_begin_limits_and_media_declarations(tmp_path, changes, code):
    upload_id = str(uuid4())
    payload = {"mime_type": "audio/mp4", "container": "m4a", "codec": "aac_lc", "byte_length": 1, "total_chunks": 1}
    payload.update(changes)
    sent, stage, _ = await run_events(tmp_path, [event("begin", upload_id, payload)])
    assert sent[0]["payload"]["code"] == code
    assert stage.stimuli == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data", "code"),
    [
        (m4a_bytes(codec_config=b"\x0a\x10"), "VOICE_UNSUPPORTED_MEDIA"),
        (m4a_bytes(duration_ms=499), "VOICE_INVALID_DURATION"),
        (m4a_bytes(duration_ms=30_501), "VOICE_INVALID_DURATION"),
    ],
)
async def test_finalize_rejects_codec_and_duration(tmp_path, data, code):
    _, events = upload_events(data)
    sent, stage, _ = await run_events(tmp_path, events)
    assert sent[-1]["payload"]["code"] == code
    assert isinstance(stage.stimuli[-1], d.VoiceUploadFailed)
    assert not any(isinstance(item, d.VoiceMessage) for item in stage.stimuli)


@pytest.mark.asyncio
async def test_abort_is_idempotent_before_finalize_and_conflicts_after(tmp_path):
    data = m4a_bytes()
    upload_id, events = upload_events(data)
    sent, stage, _ = await run_events(tmp_path, [events[0], event("abort", upload_id), event("abort", upload_id)])
    assert all(item["payload"]["ok"] for item in sent)
    assert sum(isinstance(item, d.VoiceUploadFailed) for item in stage.stimuli) == 1

    upload_id, events = upload_events(data)
    sent, stage, _ = await run_events(tmp_path, [*events, event("abort", upload_id)])
    assert sent[-1]["payload"]["code"] == "VOICE_UPLOAD_CONFLICT"
    assert sum(isinstance(item, d.VoiceMessage) for item in stage.stimuli) == 1


@pytest.mark.asyncio
async def test_recording_coordination_events_are_ephemeral_and_idempotent(tmp_path):
    recording_id = str(uuid4())
    events = [
        {"type": "user_voice_recording_started", "client_msg_id": "start-1", "payload": {"recording_id": recording_id}},
        {"type": "user_voice_recording_started", "client_msg_id": "start-2", "payload": {"recording_id": recording_id}},
        {
            "type": "user_voice_recording_cancelled",
            "client_msg_id": "cancel",
            "payload": {"recording_id": recording_id},
        },
    ]
    sent, stage, _ = await run_events(tmp_path, events)
    assert [type(item) for item in stage.stimuli] == [d.VoiceRecordingStarted, d.VoiceRecordingCancelled]
    assert all(item.ephemeral for item in stage.stimuli)
    assert sent[1]["payload"]["duplicate"] is True


@pytest.mark.asyncio
async def test_global_limit_and_user_isolation(tmp_path):
    adapter = WebSocketAdapter(
        {"media_store": {"root": str(tmp_path / "media")}, "voice_upload": {"max_incomplete": 1}}
    )
    first = str(uuid4())
    begin_payload = {
        "mime_type": "audio/mp4",
        "container": "m4a",
        "codec": "aac_lc",
        "byte_length": 1,
        "total_chunks": 1,
    }
    sent, _, adapter = await run_events(
        tmp_path,
        [event("begin", first, begin_payload)],
        adapter=adapter,
        user_id="user-a",
    )
    assert sent[0]["payload"]["ok"] is True
    second = str(uuid4())
    socket = Socket([event("begin", second, begin_payload)])
    connection = WebSocketConnection(socket, "user-b", "user-b")
    connection.capabilities.add("negative_ack_v1")
    stage = Stage("user-b")
    await adapter.bind(stage, connection)
    runtime = SimpleNamespace(
        websocket_service=WebSocketService(),
        chat_adapter=adapter,
        client_llm_executor=SimpleNamespace(),
    )
    try:
        with pytest.raises(WebSocketDisconnect):
            await _receive_events(runtime, connection)
        assert socket.sent[0]["payload"]["code"] == "OVERLOADED"
    finally:
        await adapter.disconnect(stage)


@pytest.mark.asyncio
async def test_per_user_limit_chunk_size_and_ttl_cleanup(tmp_path):
    adapter = WebSocketAdapter(
        {
            "media_store": {"root": str(tmp_path / "media")},
            "voice_upload": {"ttl_seconds": 0.001},
        }
    )
    first = str(uuid4())
    second = str(uuid4())
    begin_payload = {
        "mime_type": "audio/mp4",
        "container": "m4a",
        "codec": "aac_lc",
        "byte_length": 1,
        "total_chunks": 1,
    }
    sent, stage, adapter = await run_events(
        tmp_path,
        [event("begin", first, begin_payload), event("begin", second, begin_payload)],
        adapter=adapter,
    )
    assert sent[1]["payload"]["code"] == "VOICE_UPLOAD_CONFLICT"
    await asyncio.sleep(0.01)
    oversized_chunk = event(
        "chunk",
        second,
        {"chunk_index": 0, "audio_base64": base64.b64encode(b"x" * (48 * 1024 + 1)).decode("ascii")},
    )
    sent, next_stage, _ = await run_events(
        tmp_path,
        [event("begin", second, {**begin_payload, "byte_length": 48 * 1024 + 1}), oversized_chunk],
        adapter=adapter,
    )
    assert any(isinstance(item, d.VoiceUploadFailed) and item.reason == "expired" for item in stage.stimuli)
    assert sent[-1]["payload"]["code"] == "VOICE_TOO_LARGE"
    assert not any(isinstance(item, d.VoiceMessage) for item in next_stage.stimuli)


@pytest.mark.asyncio
async def test_inbound_frame_size_is_enforced_explicitly():
    socket = Socket([{"type": "user_text", "client_msg_id": "large", "payload": {"text": "x" * 200}}])
    connection = WebSocketConnection(socket, "user-1", "user-1")
    service = WebSocketService(max_inbound_frame_bytes=128)

    assert await service.try_recv_client_msg(connection) is None
    assert socket.sent[0]["payload"]["code"] == "BAD_MESSAGE"


@pytest.mark.asyncio
async def test_same_upload_id_is_isolated_between_users(tmp_path):
    adapter = WebSocketAdapter({"media_store": {"root": str(tmp_path / "media")}})
    upload_id = str(uuid4())
    data = m4a_bytes()
    _, events = upload_events(data, upload_id)
    sent_a, stage_a, adapter = await run_events(tmp_path, events, adapter=adapter, user_id="user-a")
    _, events = upload_events(data, upload_id)
    sent_b, stage_b, _ = await run_events(tmp_path, events, adapter=adapter, user_id="user-b")
    assert sent_a[-1]["payload"]["message_uuid"] != sent_b[-1]["payload"]["message_uuid"]
    assert isinstance(stage_a.stimuli[-1], d.VoiceMessage)
    assert isinstance(stage_b.stimuli[-1], d.VoiceMessage)
