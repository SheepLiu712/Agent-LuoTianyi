import base64
import queue
import threading

from src.message_process.message_processor import MessageProcessor
from src.network.event_types import (
    AgentMessage,
    WSMessage,
    WSEventType,
    is_audio_terminal,
    normalize_agent_message,
)


def test_audio_error_final_package_is_a_terminal_event():
    message = WSMessage(
        event_type=WSEventType.AGENT_MESSAGE,
        payload={
            "uuid": "reply-1",
            "text": "已经生成的文本",
            "audio": "",
            "is_final_package": True,
            "audio_error": True,
            "error_code": "TTS_EMPTY",
        },
    )

    normalized = normalize_agent_message(message)

    assert normalized.text == "已经生成的文本"
    assert normalized.audio_error is True
    assert normalized.error_code == "TTS_EMPTY"
    assert is_audio_terminal(normalized) is True


def test_non_final_audio_error_flag_does_not_end_playback_by_itself():
    message = WSMessage(
        event_type=WSEventType.AGENT_MESSAGE,
        payload={
            "uuid": "reply-1",
            "is_final_package": False,
            "audio_error": True,
            "error_code": "TTS_STREAM_ERROR",
        },
    )

    assert is_audio_terminal(normalize_agent_message(message)) is False


class _FakeLogger:
    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


def _agent_message(*, uuid, text, expression, audio, is_final_package):
    return AgentMessage(
        uuid=uuid,
        text=text,
        expression=expression,
        audio=audio,
        is_final_package=is_final_package,
        reply_to=None,
    )


def test_desktop_saves_complete_audio_before_waiting_and_defers_next_sentence():
    events = []
    first_playback_wait_started = threading.Event()
    release_first_playback = threading.Event()
    second_text_displayed = threading.Event()

    class FakeMultiMediaStream:
        finish_count = 0

        def feed(self, _audio):
            events.append("audio")

        def finish_one_sentense(self):
            self.finish_count += 1
            events.append(f"finish-{self.finish_count}")
            if self.finish_count == 1:
                first_playback_wait_started.set()
                assert release_first_playback.wait(timeout=2)

    processor = MessageProcessor.__new__(MessageProcessor)
    processor._event_queue = queue.Queue()
    processor._running = True
    processor.multimedia_stream = FakeMultiMediaStream()
    processor.processing_uuid = None
    processor.processing_audio = bytearray()
    processor.logger = _FakeLogger()

    def display_text(uuid, _text):
        events.append(f"text-{uuid}")
        if uuid == "sentence-2":
            second_text_displayed.set()

    processor.response_signal = display_text
    processor.expression_signal = lambda expression: events.append(f"expression-{expression}")
    processor.update_bubble_signal = lambda uuid, state: events.append(f"bubble-{uuid}-{state}")

    def save_audio(audio_data, uuid, _postfix):
        events.append(f"save-{uuid}-{audio_data.decode('utf-8')}")
        return f"{uuid}.wav"

    processor._save_audio_to_temp = save_audio

    listener = threading.Thread(target=processor._listen_ws_events, daemon=True)
    listener.start()
    processor._event_queue.put(
        _agent_message(
            uuid="sentence-1",
            text="第一句",
            expression="开心",
            audio=base64.b64encode(b"audio-1").decode("ascii"),
            is_final_package=False,
        )
    )
    processor._event_queue.put(
        _agent_message(
            uuid="sentence-1",
            text="",
            expression="",
            audio=base64.b64encode(b"-tail").decode("ascii"),
            is_final_package=True,
        )
    )
    processor._event_queue.put(
        _agent_message(
            uuid="sentence-2",
            text="第二句",
            expression="期待",
            audio=base64.b64encode(b"audio-2").decode("ascii"),
            is_final_package=True,
        )
    )
    processor._event_queue.put(None)

    assert first_playback_wait_started.wait(timeout=2)
    assert "text-sentence-1" in events
    assert "expression-开心" in events
    assert "save-sentence-1-audio-1-tail" in events
    assert events.index("save-sentence-1-audio-1-tail") < events.index("finish-1")
    assert "text-sentence-2" not in events
    assert "expression-期待" not in events

    release_first_playback.set()
    assert second_text_displayed.wait(timeout=2)
    listener.join(timeout=2)

    assert "text-sentence-2" in events
    assert "expression-期待" in events
    assert "save-sentence-2-audio-2" in events
    assert not listener.is_alive()
