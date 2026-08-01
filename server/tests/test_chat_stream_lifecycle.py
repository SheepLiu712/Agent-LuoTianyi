import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

import src.chat_session.chat_stream_manager as chat_stream_manager_module
from src.agent_runtime.character_registry import CharacterRegistry
from src.chat_session.chat_stream_manager import ChatStreamManager


@pytest.mark.asyncio
async def test_concurrent_first_connections_create_one_stream_and_worker(monkeypatch):
    release_start = asyncio.Event()
    worker_stop = asyncio.Event()
    instances = []

    class ControlledChatStream:
        def __init__(self, config, ws_connection, character_id):
            self.config = config
            self.ws_connection = ws_connection
            self.character_id = character_id
            self.connection_lost_time = None
            self.start_calls = 0
            self.reconnect_calls = []
            self.worker_task = None
            instances.append(self)

        def set_system_runtime(self, system_runtime):
            self.system_runtime = system_runtime

        async def start_if_needed(self):
            self.start_calls += 1
            self.worker_task = asyncio.create_task(worker_stop.wait())
            await release_start.wait()

        async def reconnect(self, ws_connection):
            self.reconnect_calls.append(ws_connection)
            self.ws_connection = ws_connection

        def clean_up(self):
            if self.worker_task is not None:
                self.worker_task.cancel()

    monkeypatch.setattr(chat_stream_manager_module, "ChatStream", ControlledChatStream)
    manager = ChatStreamManager({"stream_lock_stripes": 1}, None, None, None, None)
    first_connection = SimpleNamespace(user_uuid="user-1", user_name="alice")
    second_connection = SimpleNamespace(user_uuid="user-1", user_name="alice")

    first = asyncio.create_task(
        manager.get_or_register_chat_stream(first_connection, system_runtime=object())
    )
    second = asyncio.create_task(
        manager.get_or_register_chat_stream(second_connection, system_runtime=object())
    )
    asyncio.get_running_loop().call_soon(release_start.set)
    first_result, second_result = await asyncio.gather(first, second)

    assert first_result is second_result
    assert len(instances) == 1
    assert instances[0].start_calls == 1
    assert instances[0].reconnect_calls == [second_connection]
    assert manager.user_streams[("user-1", "luotianyi")] is instances[0]
    assert instances[0].worker_task is not None
    assert not instances[0].worker_task.done()

    instances[0].clean_up()
    await asyncio.gather(instances[0].worker_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_stream_uses_runtime_default_character_when_unspecified(monkeypatch):
    instances = []

    class CapturingChatStream:
        def __init__(self, _config, ws_connection, character_id):
            self.ws_connection = ws_connection
            self.character_id = character_id
            instances.append(self)

        def set_system_runtime(self, system_runtime):
            self.system_runtime = system_runtime

        async def start_if_needed(self):
            return None

    registry = CharacterRegistry(
        {"characters": {"miku": {"enabled": True, "default_target": True}}}
    )
    runtime = SimpleNamespace(
        agent_runtime=SimpleNamespace(
            default_character_id="miku",
            character_registry=registry,
        )
    )
    monkeypatch.setattr(chat_stream_manager_module, "ChatStream", CapturingChatStream)
    manager = ChatStreamManager({}, None, None, None, None)
    connection = SimpleNamespace(user_uuid="user-1", user_name="alice")

    stream = await manager.get_or_register_chat_stream(
        connection,
        system_runtime=runtime,
    )

    assert stream.character_id == "miku"
    assert manager.user_streams[("user-1", "miku")] is stream
    assert len(instances) == 1


@pytest.mark.asyncio
async def test_failed_first_start_is_cleaned_and_not_registered(monkeypatch):
    instances = []

    class FailingChatStream:
        def __init__(self, config, ws_connection, character_id):
            self.cleaned = False
            instances.append(self)

        def set_system_runtime(self, system_runtime):
            self.system_runtime = system_runtime

        async def start_if_needed(self):
            raise RuntimeError("start failed")

        def clean_up(self):
            self.cleaned = True

    monkeypatch.setattr(chat_stream_manager_module, "ChatStream", FailingChatStream)
    manager = ChatStreamManager({}, None, None, None, None)
    connection = SimpleNamespace(user_uuid="user-1", user_name="alice")

    with pytest.raises(RuntimeError, match="start failed"):
        await manager.get_or_register_chat_stream(connection, system_runtime=object())

    assert len(instances) == 1
    assert instances[0].cleaned is True
    assert manager.user_streams == {}


class FakeWebSocket:
    def __init__(self, error=None):
        self.error = error
        self.close_calls = 0

    async def close(self):
        self.close_calls += 1
        if self.error is not None:
            raise self.error


class CleanupStream:
    def __init__(self, ws_connection=None, *, lost_at=None, cleanup_error=None):
        self.ws_connection = ws_connection
        self.connection_lost_time = lost_at
        self.cleanup_error = cleanup_error
        self.cleanup_calls = 0

    def lost_connection(self, ws_connection=None):
        if ws_connection is not None and self.ws_connection is not ws_connection:
            return False
        self.ws_connection = None
        self.connection_lost_time = 100.0
        return True

    def clean_up(self):
        self.cleanup_calls += 1
        if self.cleanup_error is not None:
            raise self.cleanup_error


@pytest.mark.asyncio
async def test_stale_connection_close_error_does_not_skip_other_streams():
    failed_websocket = FakeWebSocket(RuntimeError("close failed"))
    healthy_websocket = FakeWebSocket()
    failed_connection = SimpleNamespace(websocket=failed_websocket, last_ping_time=1)
    healthy_connection = SimpleNamespace(websocket=healthy_websocket, last_ping_time=1)
    failed_stream = CleanupStream(failed_connection)
    healthy_stream = CleanupStream(healthy_connection)
    manager = ChatStreamManager({"heartbeat_timeout_seconds": 10}, None, None, None, None)
    manager.user_streams = {
        ("user-1", "luotianyi"): failed_stream,
        ("user-2", "luotianyi"): healthy_stream,
    }

    await manager._cleanup_once(expiration_seconds=3600, current_time=100.0)

    assert failed_websocket.close_calls == 1
    assert healthy_websocket.close_calls == 1
    assert failed_stream.ws_connection is None
    assert healthy_stream.ws_connection is None
    assert set(manager.user_streams) == {
        ("user-1", "luotianyi"),
        ("user-2", "luotianyi"),
    }


@pytest.mark.asyncio
async def test_expired_stream_cleanup_error_does_not_skip_other_streams():
    failed_stream = CleanupStream(lost_at=1.0, cleanup_error=RuntimeError("cleanup failed"))
    healthy_stream = CleanupStream(lost_at=1.0)
    manager = ChatStreamManager({}, None, None, None, None)
    manager.user_streams = {
        ("user-1", "luotianyi"): failed_stream,
        ("user-2", "luotianyi"): healthy_stream,
    }

    await manager._cleanup_once(expiration_seconds=10, current_time=100.0)

    assert failed_stream.cleanup_calls == 1
    assert healthy_stream.cleanup_calls == 1
    assert manager.user_streams == {("user-1", "luotianyi"): failed_stream}
