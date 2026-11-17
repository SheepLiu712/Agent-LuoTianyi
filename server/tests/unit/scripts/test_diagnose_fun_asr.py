"""诊断main公开入口只替换外部WebSocket，不借生产Manager预算。"""

import asyncio
import json
import wave
from types import SimpleNamespace

import pytest

from scripts import diagnose_fun_asr as script
from src.infrastructure.models.realtime_speech import fun_asr


class _Socket:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.sent = []
        self.closed = False
        self.started = asyncio.Event()

    async def send(self, message):
        self.sent.append(message)
        self.started.set()

    async def recv(self):
        return await self.incoming.get()

    async def close(self):
        self.closed = True


@pytest.fixture
def args(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTLUO_CONFIG_DIR", str(tmp_path / "config"))
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "stage_manager": {"call_setup_timeout": 999},
                "call_transport": {
                    "realtime_speech": {
                        "enabled": True,
                        "api_key": "offline",
                        "model": "fun-asr-realtime",
                        "endpoint": "wss://provider.invalid/api-ws/v1/inference",
                        "connect_timeout_seconds": "old-invalid",
                        "session_timeout_seconds": "old-invalid",
                        "close_timeout_seconds": 0.02,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    wav = tmp_path / "sample.wav"
    with wave.open(str(wav), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b"\0\0" * 160)
    return SimpleNamespace(
        config_root=tmp_path,
        wav=wav,
        output=tmp_path / "result.json",
        adapter=True,
        initial_silence_seconds=0,
        silence_seconds=0,
        silence_only=True,
        connect_timeout_seconds=0.02,
        session_timeout_seconds=0.02,
    )


@pytest.mark.asyncio
async def test_adapter_main_uses_script_limits_instead_of_invalid_legacy_config(args, monkeypatch):
    socket = _Socket()
    connected = []

    async def connector(_url, *, open_timeout, **_options):
        connected.append(open_timeout)
        return socket

    monkeypatch.setattr(fun_asr, "connect", connector)
    with pytest.raises(RuntimeError, match="Fun-ASR initialization failed"):
        await script.main(args)
    assert connected == [0.02]
    assert socket.closed


class _DirectConnection:
    def __init__(self, socket, called):
        self.socket = socket
        self.called = called

    async def __aenter__(self):
        self.called.set()
        return self.socket

    async def __aexit__(self, *_errors):
        await self.socket.close()


@pytest.mark.asyncio
async def test_direct_main_times_out_ready_with_script_limit_and_closes_socket(args, monkeypatch):
    args.adapter = False
    socket = _Socket()
    opened = []
    entered = asyncio.Event()

    def connector(_url, *, open_timeout, **_options):
        opened.append(open_timeout)
        return _DirectConnection(socket, entered)

    monkeypatch.setattr(script, "connect", connector)
    task = asyncio.create_task(script.main(args))
    done, _ = await asyncio.wait({task}, timeout=0.5)
    if not done:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert done, "脚本应在自身0.02秒上限内终止，而不是依赖测试0.5秒取消"
    with pytest.raises(asyncio.TimeoutError):
        task.result()
    assert entered.is_set()
    assert opened == [0.02]
    assert socket.sent and socket.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", [False, True], ids=["direct", "adapter"])
async def test_connect_wait_is_bounded_by_script_option(args, monkeypatch, adapter):
    args.adapter = adapter
    args.session_timeout_seconds = 60
    cancelled = asyncio.Event()

    async def connect_wait(seconds):
        try:
            await asyncio.wait_for(asyncio.Event().wait(), seconds)
        finally:
            cancelled.set()

    async def adapter_connector(_url, *, open_timeout, **_options):
        await connect_wait(open_timeout)

    class PendingConnection:
        async def __aenter__(self):
            await connect_wait(args.connect_timeout_seconds)

        async def __aexit__(self, *_errors):
            pass

    def direct_connector(_url, *, open_timeout, **_options):
        assert open_timeout == 0.02
        return PendingConnection()

    monkeypatch.setattr(fun_asr, "connect", adapter_connector)
    monkeypatch.setattr(script, "connect", direct_connector)
    task = asyncio.create_task(script.main(args))
    done, _ = await asyncio.wait({task}, timeout=0.5)
    if not done:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert done
    with pytest.raises((RuntimeError, asyncio.TimeoutError)):
        task.result()
    assert cancelled.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", [False, True], ids=["direct", "adapter"])
async def test_cancel_main_preserves_cancel_and_closes_socket(args, monkeypatch, adapter):
    args.adapter = adapter
    args.session_timeout_seconds = 60
    socket = _Socket()

    async def adapter_connector(_url, **_options):
        return socket

    def direct_connector(_url, **_options):
        return _DirectConnection(socket, asyncio.Event())

    monkeypatch.setattr(fun_asr, "connect", adapter_connector)
    monkeypatch.setattr(script, "connect", direct_connector)
    task = asyncio.create_task(script.main(args))
    await socket.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert socket.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [0, -1, True, float("nan"), float("inf")])
async def test_main_rejects_invalid_script_limits_before_opening(args, monkeypatch, invalid):
    args.connect_timeout_seconds = invalid

    def unexpected(*_args, **_kwargs):
        pytest.fail("非法等待上限不能访问外部连接")

    monkeypatch.setattr(script, "connect", unexpected)
    monkeypatch.setattr(fun_asr, "connect", unexpected)
    with pytest.raises(ValueError, match="正的有限秒数"):
        await script.main(args)


@pytest.mark.parametrize("invalid", ["0", "-1", "nan", "inf"])
def test_cli_rejects_invalid_waiting_limits(args, invalid):
    with pytest.raises(SystemExit) as failed:
        script.parse_args(
            [
                "--config-root",
                str(args.config_root),
                "--wav",
                str(args.wav),
                "--output",
                str(args.output),
                "--session-timeout-seconds",
                invalid,
            ]
        )
    assert failed.value.code == 2
