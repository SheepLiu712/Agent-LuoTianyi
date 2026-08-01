import asyncio
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest


server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.agent.main_chat import OneSentenceChat, SongSegmentChat
from src.capabilities import capability_manager as capability_manager_module
from src.capabilities.speech import speech as speech_module
from src.capabilities.speech import tts_module as tts_module_module
from src.capabilities.speech.speech import SpeechCapability
from src.capabilities.speech.tts_server import TTSServer
from src.chat_session.dependency.global_speaking_worker import (
    GlobalSpeakingWorker,
    SpeakingJob,
    _iter_sync_gen_in_executor,
)


def test_speaking_queue_size_is_configurable_and_never_unbounded():
    assert GlobalSpeakingWorker({}).queue.maxsize == 512
    assert GlobalSpeakingWorker({"queue_maxsize": 7}).queue.maxsize == 7
    assert GlobalSpeakingWorker({"queue_maxsize": 0}).queue.maxsize == 1


@pytest.mark.asyncio
async def test_executor_generator_cancellation_waits_for_next_and_closes_generator():
    started = threading.Event()
    release = threading.Event()
    closed = threading.Event()

    def source():
        try:
            started.set()
            release.wait(timeout=2)
            yield "chunk"
        finally:
            closed.set()

    async def consume():
        async for _chunk in _iter_sync_gen_in_executor(source()):
            pass

    task = asyncio.create_task(consume())
    assert await asyncio.to_thread(started.wait, 1)

    task.cancel()
    await asyncio.sleep(0.02)

    assert not task.done(), "cancellation must wait for the executor's active next() call"

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert closed.is_set()


@pytest.mark.asyncio
async def test_speaking_worker_stop_signals_stream_then_waits_before_backend_stop():
    started = threading.Event()
    release = threading.Event()
    events = []

    class FakeServer:
        def __init__(self):
            self.stop_calls = 0

        def request_stop(self):
            events.append("stop_requested")
            release.set()

        def stop(self):
            self.stop_calls += 1
            events.append("backend_stopped")

    server = FakeServer()

    class FakeModule:
        tts_server = server

        def stream_synthesize_speech_with_tone(self, _text, _tone):
            try:
                started.set()
                release.wait(timeout=2)
                yield b"audio"
            finally:
                events.append("generator_closed")

        @staticmethod
        def encode_audio_to_base64(_audio):
            return "audio"

    speech = object.__new__(SpeechCapability)
    speech.tts_config = {}
    speech.tts_module = {"luotianyi": FakeModule()}
    speech._stop_lock = asyncio.Lock()
    speech._stopped_server_ids = set()
    speech._stop_signaled_server_ids = set()

    worker = GlobalSpeakingWorker({})
    worker.set_capabilities(SimpleNamespace(speech=speech))

    async def send_reply(_response):
        pass

    await worker.enqueue(
        SpeakingJob(
            send_reply_callback=send_reply,
            job_content=OneSentenceChat(content="hello", sound_content="hello", tone="normal"),
        )
    )
    assert await asyncio.to_thread(started.wait, 1)

    await worker.stop()
    await speech.stop()

    assert worker.worker_task is None
    assert events == ["stop_requested", "generator_closed", "backend_stopped"]
    assert server.stop_calls == 1
    with pytest.raises(RuntimeError, match="cannot be restarted"):
        worker.start_if_needed()


@pytest.mark.asyncio
async def test_speaking_worker_closes_generator_when_cancelled_during_send():
    callback_started = asyncio.Event()
    release_stream = threading.Event()
    generator_closed = threading.Event()

    class FakeSpeech:
        def request_stop(self):
            release_stream.set()

        def say_stream(self, _character, _text, _tone):
            try:
                yield "audio"
                release_stream.wait(timeout=2)
                yield "late-audio"
            finally:
                generator_closed.set()

    worker = GlobalSpeakingWorker({})
    worker.set_capabilities(SimpleNamespace(speech=FakeSpeech()))

    async def blocked_send(_response):
        callback_started.set()
        await asyncio.Event().wait()

    await worker.enqueue(
        SpeakingJob(
            send_reply_callback=blocked_send,
            job_content=OneSentenceChat(content="hello", sound_content="hello", tone="normal"),
        )
    )
    await asyncio.wait_for(callback_started.wait(), timeout=1)

    await worker.stop()

    assert generator_closed.is_set()


def test_tts_server_refuses_restart_while_old_request_is_active(tmp_path):
    server = TTSServer(str(tmp_path / "tts.yaml"))
    server._active_requests = 1

    with pytest.raises(RuntimeError, match="requests are still active"):
        server.start()


@pytest.mark.asyncio
async def test_tts_start_waits_until_stop_finishes_closing_old_queues(tmp_path):
    join_started = threading.Event()
    release_join = threading.Event()
    events = []

    class FakeProcess:
        def __init__(self):
            self.alive = True

        def is_alive(self):
            return self.alive

        def join(self, timeout):
            _ = timeout
            join_started.set()
            release_join.wait(timeout=2)
            self.alive = False

        def terminate(self):
            self.alive = False

    class FakeQueue:
        def put(self, _message):
            pass

        def close(self):
            events.append("queue_closed")

        def cancel_join_thread(self):
            pass

    class FakeEvent:
        def set(self):
            pass

    server = TTSServer(str(tmp_path / "tts.yaml"))
    server.server_process = FakeProcess()
    server.request_queue = FakeQueue()
    server.response_queue = FakeQueue()
    server.stop_event = FakeEvent()
    server._start = lambda: events.append("start_body")

    stop_task = asyncio.create_task(asyncio.to_thread(server.stop))
    assert await asyncio.to_thread(join_started.wait, 1)
    start_task = asyncio.create_task(asyncio.to_thread(server.start))
    await asyncio.sleep(0.02)

    assert not start_task.done()

    release_join.set()
    await stop_task
    await start_task

    assert events == ["queue_closed", "queue_closed", "start_body"]


def test_partial_speech_construction_stops_already_started_tts(monkeypatch):
    events = []

    class FakeServer:
        def request_stop(self):
            events.append("stop_requested")

        def stop(self):
            events.append("backend_stopped")

    calls = 0

    def init_module(_config):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("second TTS failed")
        return SimpleNamespace(tts_server=FakeServer())

    monkeypatch.setattr(speech_module, "init_tts_module", init_module)

    with pytest.raises(RuntimeError, match="second TTS failed"):
        SpeechCapability({"first": {}, "second": {}})

    assert events == ["stop_requested", "backend_stopped"]


def test_tts_module_factory_stops_server_when_module_construction_fails(monkeypatch):
    events = []

    class FakeServer:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            events.append("server_started")

        def stop(self):
            events.append("server_stopped")

    class FailingModule:
        def __init__(self, **_kwargs):
            raise RuntimeError("module failed")

    monkeypatch.setattr(tts_module_module, "TTSServer", FakeServer)
    monkeypatch.setattr(tts_module_module, "TTSModule", FailingModule)

    with pytest.raises(RuntimeError, match="module failed"):
        tts_module_module.init_tts_module({})

    assert events == ["server_started", "server_stopped"]


def test_tts_module_factory_rolls_back_server_start_failure(monkeypatch):
    events = []

    class FakeServer:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            events.append("server_start_attempted")
            raise RuntimeError("server start failed")

        def stop(self):
            events.append("server_stopped")

    monkeypatch.setattr(tts_module_module, "TTSServer", FakeServer)

    with pytest.raises(RuntimeError, match="server start failed"):
        tts_module_module.init_tts_module({})

    assert events == ["server_start_attempted", "server_stopped"]


def test_capability_construction_failure_rolls_back_speech(monkeypatch):
    events = []

    class FakeSpeech:
        def __init__(self, _config):
            events.append("speech_started")

        def _abort_initialization(self):
            events.append("speech_stopped")

    class FailingSinging:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("singing failed")

    monkeypatch.setattr(capability_manager_module, "SpeechCapability", FakeSpeech)
    monkeypatch.setattr(capability_manager_module, "SingingCapability", FailingSinging)

    with pytest.raises(RuntimeError, match="singing failed"):
        capability_manager_module.CapabilityManager({}, object())

    assert events == ["speech_started", "speech_stopped"]


@pytest.mark.asyncio
async def test_speaking_worker_stop_waits_for_owned_singing_thread():
    started = threading.Event()
    release = threading.Event()

    class FakeSpeech:
        def request_stop(self):
            pass

    class FakeSinging:
        def sing(self, _character, _song, _segment):
            started.set()
            release.wait(timeout=2)
            return b"audio"

    worker = GlobalSpeakingWorker({})
    worker.set_capabilities(SimpleNamespace(speech=FakeSpeech(), singing=FakeSinging()))

    async def send_reply(_response):
        pass

    await worker.enqueue(
        SpeakingJob(
            send_reply_callback=send_reply,
            job_content=SongSegmentChat(song="song", lyrics="lyrics", segment="segment"),
        )
    )
    assert await asyncio.to_thread(started.wait, 1)

    stop_task = asyncio.create_task(worker.stop())
    await asyncio.sleep(0.02)
    assert not stop_task.done()

    release.set()
    await stop_task
    assert worker.worker_task is None


@pytest.mark.asyncio
async def test_terminal_send_retries_until_callback_accepts_once():
    attempts = 0
    accepted = []

    class FakeSpeech:
        def request_stop(self):
            pass

    worker = GlobalSpeakingWorker(
        {
            "terminal_send_max_attempts": 2,
            "terminal_send_retry_delay_seconds": 0,
        }
    )
    worker.set_capabilities(SimpleNamespace(speech=FakeSpeech()))
    content = OneSentenceChat(content="text", expression="smile")
    content.sound_content = ""

    async def flaky_send(response):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary send failure")
        accepted.append(response)

    await worker.enqueue(SpeakingJob(send_reply_callback=flaky_send, job_content=content))
    await asyncio.wait_for(worker.queue.join(), timeout=1)
    await worker.stop()

    assert attempts == 2
    assert len(accepted) == 1
    assert accepted[0].is_final_package is True
    assert accepted[0].text == "text"
