import threading
import queue
from unittest.mock import Mock

import pytest

from src.message_process import multi_media_stream as stream_module
from src.message_process.message_processor import MessageProcessor
from src.message_process.multi_media_stream import MultiMediaStream
from src.network.event_types import AgentMessage


class _FakeLogger:
    def error(self, *_args, **_kwargs):
        pass


def _bare_stream() -> MultiMediaStream:
    stream = MultiMediaStream.__new__(MultiMediaStream)
    stream.logger = _FakeLogger()
    stream._state_lock = threading.Lock()
    stream._server_audio_active = False
    stream._mouth_thread = None
    stream._local_play_thread = None
    stream._local_stop_event = None
    stream._local_play_request_id = 0
    return stream


def test_local_replay_is_blocked_while_server_audio_is_active(monkeypatch):
    stream = _bare_stream()
    stream._server_audio_active = True
    monkeypatch.setattr(stream_module.os.path, "exists", lambda _path: True)

    assert stream.feed_local_wav("saved.wav", conv_uuid="sentence-1") is False
    assert stream._local_play_thread is None


@pytest.fixture
def terminal_processor():
    stream = _bare_stream()
    stream._mouth_queue = None
    stream._stop_mouth_event = None
    stream.local_audio_properties = stream_module.AudioProperties()
    stream._open_audio_stream_if_needed = Mock()
    stream.audio_queue_in = queue.Queue()
    stream.audio_queue_out = Mock()
    stream.audio_queue_out.empty.return_value = True
    stream.audio_queue_out.get.return_value = "finished"
    processor = MessageProcessor.__new__(MessageProcessor)
    processor._running = True
    processor._event_queue = queue.Queue()
    processor._playback_queue = queue.Queue()
    processor._audio_buffers = {}
    processor._send_queue = []
    processor._send_cond = threading.Condition()
    processor._reply_counter = 0
    processor.logger = Mock()
    processor.multimedia_stream = stream
    processor.response_signal = Mock()
    processor.expression_signal = None
    processor.update_bubble_signal = None
    return processor


def _process_terminal_then_text(processor, response):
    listener = threading.Thread(target=processor._listen_ws_events, daemon=True)
    playback = threading.Thread(target=processor._process_playback_events, daemon=True)
    listener.start()
    playback.start()
    try:
        processor.feed_agent_msg(response)
        processor.feed_agent_msg(AgentMessage(
            uuid="next", text="still available", expression="", audio="",
            is_final_package=False, reply_to=None,
        ))
    finally:
        processor._event_queue.put(None)
        listener.join(timeout=3)
        playback.join(timeout=3)
    assert not listener.is_alive()
    assert not playback.is_alive()


def test_zero_sample_terminal_audio_allows_follow_up_messages_and_touch(terminal_processor):
    import base64
    import io
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
    response = AgentMessage(
        uuid="empty-terminal", text="", expression="",
        audio=base64.b64encode(buffer.getvalue()).decode("ascii"),
        is_final_package=True, reply_to=None, is_ephemeral=True,
    )

    _process_terminal_then_text(terminal_processor, response)

    assert not terminal_processor.is_server_audio_active()
    terminal_processor.response_signal.assert_called_once_with("next", "still available")
    assert terminal_processor.send_touch("头") is not None


def test_playback_failure_is_logged_and_allows_follow_up_messages_and_touch(terminal_processor, monkeypatch):
    monkeypatch.setattr(
        terminal_processor.multimedia_stream,
        "feed",
        Mock(side_effect=RuntimeError("explicit-playback-failure")),
    )
    response = AgentMessage(
        uuid="failed-terminal", text="", expression="", audio="c2VydmVy",
        is_final_package=True, reply_to=None, is_ephemeral=True,
    )

    _process_terminal_then_text(terminal_processor, response)

    assert not terminal_processor.is_server_audio_active()
    terminal_processor.response_signal.assert_called_once_with("next", "still available")
    assert terminal_processor.send_touch("头") is not None
    assert any(
        "explicit-playback-failure" in call.args[0]
        for call in terminal_processor.logger.error.call_args_list
    )


def test_server_audio_stops_local_replay_before_streaming(monkeypatch):
    stream = _bare_stream()
    events = []
    replay_started = threading.Event()
    replay_stopped = threading.Event()
    stop_event = threading.Event()

    def replay_worker():
        replay_started.set()
        stop_event.wait(timeout=1)
        events.append("local-stopped")
        replay_stopped.set()

    local_thread = threading.Thread(target=replay_worker, daemon=True)
    stream._local_stop_event = stop_event
    stream._local_play_thread = local_thread
    stream._append_audio_stream = lambda audio: events.append(("server-fed", audio))
    monkeypatch.setattr(stream_module, "decode_from_base64", lambda _audio: b"server-audio")

    local_thread.start()
    assert replay_started.wait(timeout=1)

    stream.feed("encoded")

    assert replay_stopped.is_set()
    assert events == ["local-stopped", ("server-fed", b"server-audio")]
    assert stream._server_audio_active is True

    stream._close_audio_stream = lambda wait_audio_finish: events.append(("finished", wait_audio_finish))
    stream.finish_one_sentense()
    assert stream._server_audio_active is False


def test_network_receive_reserves_server_audio_before_listener_queue():
    events = []

    class FakeStream:
        def reserve_server_audio(self):
            events.append("reserved")

    class RecordingQueue(queue.Queue):
        def put(self, item, *args, **kwargs):
            events.append("queued")
            return super().put(item, *args, **kwargs)

    processor = MessageProcessor.__new__(MessageProcessor)
    processor.multimedia_stream = FakeStream()
    processor._event_queue = RecordingQueue()
    payload = AgentMessage(
        uuid="online-message",
        text="",
        expression="",
        audio="c2VydmVy",
        is_final_package=False,
        reply_to=None,
    )

    processor.feed_agent_msg(payload)

    assert events == ["reserved", "queued"]


def test_touch_is_not_enqueued_while_server_audio_is_active():
    processor = MessageProcessor.__new__(MessageProcessor)
    processor.multimedia_stream = _bare_stream()
    processor.multimedia_stream._server_audio_active = True
    processor._send_queue = []
    processor._send_cond = threading.Condition()
    processor._reply_counter = 0

    result = processor.send_touch("头")

    assert result is None
    assert processor._send_queue == []


@pytest.mark.parametrize("timed_out", [False, True])
def test_replay_stays_blocked_until_finish_ack_or_90_second_timeout(monkeypatch, timed_out):
    stream = _bare_stream()
    stream.logger = Mock()
    stream._server_audio_active = True
    stream._stop_mouth_event = None
    stream.local_audio_properties = None
    stream.audio_queue_in = queue.Queue()
    stream.audio_queue_out = Mock()
    stream.audio_queue_out.empty.return_value = True
    monkeypatch.setattr(stream_module.os.path, "exists", lambda _path: True)

    def wait_for_finished(*, timeout):
        assert timeout == 90
        assert stream.is_server_audio_active() is True
        assert stream.feed_local_wav("saved.wav", conv_uuid="sentence-1") is False
        if timed_out:
            raise queue.Empty
        return "finished"

    stream.audio_queue_out.get.side_effect = wait_for_finished
    stream.finish_one_sentense()

    assert stream.is_server_audio_active() is False
    assert stream.audio_queue_in.get_nowait() == {"cmd": "wait_finish"}
    assert stream.audio_queue_in.empty()
    assert stream.logger.warning.call_count == int(timed_out)
