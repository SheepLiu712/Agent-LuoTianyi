import base64
import io
import json
import wave
from pathlib import Path

import pytest

from src.cli.actions import ActionExecutor, ExitCode
from src.cli.media import PlaybackResult
from src.cli.output import serialize_record
from src.session import AggregatedReply, SessionState


class FakeSession:
    def __init__(self, replies):
        self.state = SessionState.READY
        self.replies = replies

    def get_reply(self, reply_uuid):
        return self.replies.get(reply_uuid)

    def close(self):
        self.state = SessionState.CLOSED


class FakePlayer:
    def __init__(self, result=PlaybackResult.COMPLETED):
        self.result = result
        self.paths = []

    def play(self, path):
        self.paths.append(Path(path))
        return self.result


def _wav_bytes():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x00\x00" * 80)
    return buffer.getvalue()


def _reply(
    *,
    uuid="reply-1",
    path=None,
    complete=True,
    audio_error=False,
    is_ephemeral=False,
    display_in_chat=True,
):
    return AggregatedReply(
        uuid=uuid,
        texts=("hello",),
        expressions=("smile", "happy"),
        complete=complete,
        audio_path=str(path) if path else None,
        audio_error=audio_error,
        error_code="TTS_STREAM_ERROR" if audio_error else None,
        display_in_chat=display_in_chat,
        is_ephemeral=is_ephemeral,
    )


def _executor(replies, player=None):
    session = FakeSession(replies)
    player = player or FakePlayer()
    executor = ActionExecutor(
        session_factory=lambda **_kwargs: session,
        playback_backend=player,
        session_id="session-media",
    )
    executor._session = session
    return executor, player


def _execute(executor, action, reply_uuid="reply-1"):
    return executor.execute(
        {"action": action, "params": {"reply_uuid": reply_uuid}}
    )


def test_audio_replay_success_waits_for_fake_backend_completion(tmp_path):
    audio_path = tmp_path / "reply-1.wav"
    audio_path.write_bytes(_wav_bytes())
    executor, player = _executor({"reply-1": _reply(path=audio_path)})

    record, exit_code = _execute(executor, "audio.replay")

    assert exit_code == ExitCode.SUCCESS
    assert record["data"]["playback"] == "completed"
    assert record["data"]["audio"] == {
        "available": True,
        "byte_count": audio_path.stat().st_size,
        "format": "wav",
        "reference": "reply-1.wav",
    }
    assert player.paths == [audio_path]


@pytest.mark.parametrize(
    ("reply", "expected_code"),
    [
        (None, "AUDIO_REPLY_NOT_FOUND"),
        (_reply(complete=False), "AUDIO_NOT_READY"),
        (_reply(is_ephemeral=True), "AUDIO_EPHEMERAL"),
        (_reply(display_in_chat=False), "AUDIO_EPHEMERAL"),
        (_reply(audio_error=True), "AUDIO_STREAM_FAILED"),
        (_reply(path="missing.wav"), "AUDIO_FILE_MISSING"),
    ],
)
def test_audio_replay_rejects_ineligible_reply_states(reply, expected_code):
    replies = {} if reply is None else {"reply-1": reply}
    executor, player = _executor(replies)

    record, exit_code = _execute(executor, "audio.replay")

    assert exit_code == ExitCode.ASSERTION_FAILED
    assert record["error"]["code"] == expected_code
    assert player.paths == []


def test_audio_replay_rejects_unreadable_format_before_playback(tmp_path):
    audio_path = tmp_path / "reply-1.wav"
    audio_path.write_bytes(b"not a wave file")
    executor, player = _executor({"reply-1": _reply(path=audio_path)})

    record, exit_code = _execute(executor, "audio.replay")

    assert exit_code == ExitCode.ASSERTION_FAILED
    assert record["error"]["code"] == "AUDIO_FORMAT_INVALID"
    assert player.paths == []


@pytest.mark.parametrize(
    ("result", "expected_code"),
    [
        (PlaybackResult.DEVICE_UNAVAILABLE, "DEVICE_UNAVAILABLE"),
        (PlaybackResult.INTERRUPTED, "PLAYBACK_INTERRUPTED"),
    ],
)
def test_audio_replay_classifies_backend_failures(tmp_path, result, expected_code):
    audio_path = tmp_path / "reply-1.wav"
    audio_path.write_bytes(_wav_bytes())
    executor, player = _executor(
        {"reply-1": _reply(path=audio_path)},
        FakePlayer(result),
    )

    record, exit_code = _execute(executor, "audio.replay")

    assert exit_code == ExitCode.ASSERTION_FAILED
    assert record["error"]["code"] == expected_code
    assert player.paths == [audio_path]


def test_reply_media_fields_fill_s3_shape_without_base64_or_absolute_path(tmp_path):
    audio_path = tmp_path / "reply-1.wav"
    raw_audio = _wav_bytes()
    encoded = base64.b64encode(raw_audio).decode("ascii")
    audio_path.write_bytes(raw_audio)
    executor, _player = _executor({"reply-1": _reply(path=audio_path)})

    record, exit_code = _execute(executor, "reply.read")
    output = serialize_record(record, executor.redactor)
    parsed = json.loads(output)

    assert exit_code == ExitCode.SUCCESS
    assert parsed["data"]["expressions"] == ["smile", "happy"]
    assert parsed["data"]["audio"] == {
        "available": True,
        "byte_count": len(raw_audio),
        "format": "wav",
        "reference": "reply-1.wav",
    }
    assert encoded not in output
    assert str(tmp_path) not in output
