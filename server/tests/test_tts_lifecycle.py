import asyncio
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest


server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.capabilities.capability_manager import CapabilityManager
from src.capabilities.speech.speech import SpeechCapability
from src.capabilities.speech.tts_server import TTSServer


def make_speech(modules):
    speech = object.__new__(SpeechCapability)
    speech.tts_config = {}
    speech.tts_module = modules
    speech._stop_lock = asyncio.Lock()
    speech._stopped_server_ids = set()
    speech._stop_signaled_server_ids = set()
    speech._stop_tasks = {}
    speech.stop_timeout_seconds = 30.0
    return speech


class RecordingServer:
    def __init__(self, failures=0):
        self.failures = failures
        self.stop_calls = 0
        self.stop_thread_ids = []

    def stop(self):
        self.stop_calls += 1
        self.stop_thread_ids.append(threading.get_ident())
        if self.stop_calls <= self.failures:
            raise RuntimeError("stop failed")


@pytest.mark.asyncio
async def test_shared_tts_server_is_stopped_once_in_worker_thread():
    server = RecordingServer()
    speech = make_speech(
        {
            "luotianyi": SimpleNamespace(tts_server=server),
            "yanhe": SimpleNamespace(tts_server=server),
        }
    )
    event_loop_thread_id = threading.get_ident()

    await speech.stop()
    await speech.stop()

    assert server.stop_calls == 1
    assert len(server.stop_thread_ids) == 1
    assert server.stop_thread_ids[0] != event_loop_thread_id


@pytest.mark.asyncio
async def test_tts_stop_retries_only_failed_servers_and_preserves_shared_ownership():
    healthy_server = RecordingServer()
    flaky_server = RecordingServer(failures=1)
    speech = make_speech(
        {
            "luotianyi": SimpleNamespace(tts_server=healthy_server),
            "yanhe": SimpleNamespace(tts_server=flaky_server),
            "yuezhengling": SimpleNamespace(tts_server=flaky_server),
        }
    )

    with pytest.raises(RuntimeError, match="TTS shutdown failed"):
        await speech.stop()

    assert healthy_server.stop_calls == 1
    assert flaky_server.stop_calls == 1

    await speech.stop()
    await speech.stop()

    assert healthy_server.stop_calls == 1
    assert flaky_server.stop_calls == 2


@pytest.mark.asyncio
async def test_capability_manager_stop_is_idempotent_and_retryable():
    class FlakySpeech:
        def __init__(self):
            self.stop_calls = 0

        async def stop(self):
            self.stop_calls += 1
            if self.stop_calls == 1:
                raise RuntimeError("speech stop failed")

    manager = object.__new__(CapabilityManager)
    manager.speech = FlakySpeech()
    manager._stop_lock = asyncio.Lock()
    manager._stopped = False

    with pytest.raises(RuntimeError, match="speech stop failed"):
        await manager.stop()
    await manager.stop()
    await manager.stop()

    assert manager.speech.stop_calls == 2
    assert manager._stopped is True


@pytest.mark.asyncio
async def test_speech_stop_cancellation_waits_for_owned_thread():
    started = threading.Event()
    release = threading.Event()

    class BlockingServer:
        def __init__(self):
            self.stop_calls = 0

        def request_stop(self):
            pass

        def stop(self):
            self.stop_calls += 1
            started.set()
            release.wait(timeout=2)

    server = BlockingServer()
    speech = make_speech({"luotianyi": SimpleNamespace(tts_server=server)})
    stop_task = asyncio.create_task(speech.stop())
    assert await asyncio.to_thread(started.wait, 1)

    stop_task.cancel()
    await asyncio.sleep(0.02)
    assert not stop_task.done()

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await stop_task

    await speech.stop()
    assert server.stop_calls == 1


@pytest.mark.asyncio
async def test_speech_stop_timeout_retains_backend_task_for_retry():
    started = threading.Event()
    release = threading.Event()

    class BlockingServer:
        def __init__(self):
            self.stop_calls = 0

        def request_stop(self):
            pass

        def stop(self):
            self.stop_calls += 1
            started.set()
            release.wait(timeout=2)

    server = BlockingServer()
    speech = make_speech({"luotianyi": SimpleNamespace(tts_server=server)})
    speech.stop_timeout_seconds = 0.02

    with pytest.raises(RuntimeError, match="still running"):
        await speech.stop()

    assert started.is_set()
    assert server.stop_calls == 1

    release.set()
    await speech.stop()

    assert server.stop_calls == 1
    assert speech._stop_tasks == {}


def test_tts_server_retains_handles_when_process_cannot_be_stopped(tmp_path):
    class StubbornProcess:
        def __init__(self):
            self.terminate_calls = 0

        def is_alive(self):
            return True

        def join(self, timeout):
            _ = timeout

        def terminate(self):
            self.terminate_calls += 1

    class FakeQueue:
        def close(self):
            raise AssertionError("queues must remain available for a retry")

    class FakeEvent:
        def set(self):
            pass

    process = StubbornProcess()
    request_queue = FakeQueue()
    response_queue = FakeQueue()
    server = TTSServer(str(tmp_path / "tts.yaml"))
    server.server_process = process
    server.request_queue = request_queue
    server.response_queue = response_queue
    server.stop_event = FakeEvent()

    with pytest.raises(RuntimeError, match="still alive"):
        server.stop(force=True)

    assert process.terminate_calls == 1
    assert server.server_process is process
    assert server.request_queue is request_queue
    assert server.response_queue is response_queue
