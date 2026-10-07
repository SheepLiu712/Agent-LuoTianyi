"""城市漫步的同步服务在事件循环外运行，并由任务持有到结束。"""

import asyncio
import threading
from types import SimpleNamespace

import pytest

from src.world.citywalk.llm_modules import CitywalkLLMModules
from src.world.citywalk.task import CitywalkTask


@pytest.mark.asyncio
async def test_citywalk_llm_facade_runs_from_worker_thread(tmp_path) -> None:
    caller_thread = threading.get_ident()
    report = tmp_path / "citywalk.json"
    calls = []

    class JsonModule:
        async def generate_response(self, **kwargs):
            calls.append((threading.get_ident(), kwargs))
            return '{"destination":"武康路"}'

    facade = CitywalkLLMModules(json_module=JsonModule())

    def run_once() -> str:
        assert threading.get_ident() != caller_thread
        response = facade.chat.completions.create(
            messages=[{"role": "user", "content": "选择散步目的地"}],
            response_format={"type": "json_object"},
        )
        report.write_text(response.choices[0].message.content, encoding="utf-8")
        return str(report)

    task = CitywalkTask({"daily_run_probability": 1.0})
    task.citywalk_service = SimpleNamespace(run_once=run_once)

    result = await task.run_once()

    assert result.ok and not result.skipped
    assert result.data["output_path"] == str(report)
    assert calls[0][0] != caller_thread
    assert report.read_text(encoding="utf-8") == '{"destination":"武康路"}'


@pytest.mark.asyncio
async def test_cancelled_citywalk_waits_for_owned_worker() -> None:
    started = threading.Event()
    release = threading.Event()

    def run_once() -> str:
        started.set()
        assert release.wait(2)
        return "citywalk.json"

    task = CitywalkTask({"daily_run_probability": 1.0})
    task.citywalk_service = SimpleNamespace(run_once=run_once)
    running = asyncio.create_task(task.run_once())
    try:
        assert await asyncio.to_thread(started.wait, 1)
        running.cancel()
        await asyncio.sleep(0)
        assert not running.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await running
