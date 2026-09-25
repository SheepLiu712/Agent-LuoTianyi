import asyncio
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

server_root = str(Path(__file__).resolve().parents[3])
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.agent.skills.expression.speaking import backend as speech_module
from src.agent.skills.expression.speaking import tts_module as tts_module_module
from src.agent.skills.expression.speaking.backend import SpeechBackend
from src.agent.skills.expression.speaking.tts_server import TTSServer


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
        SpeechBackend({"first": {}, "second": {}})

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
