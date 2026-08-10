import threading
import queue

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
