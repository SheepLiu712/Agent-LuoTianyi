"""Use the real model adapter retry loop without paid requests or wall-clock sleeps."""

import asyncio
import threading
from types import SimpleNamespace

import pytest

from src.infrastructure.models.llm import interface as module


@pytest.mark.asyncio
@pytest.mark.parametrize("exhausted", [False, True])
async def test_openai_attempt_budget_exponential_backoff_and_no_sdk_retries(monkeypatch, exhausted):
    calls, delays, settings = [], [], []

    def create(**kwargs):
        calls.append(kwargs)
        if exhausted or len(calls) < 4:
            raise TimeoutError("request deadline")
        return object()

    def client(**kwargs):
        settings.append(kwargs)
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(module, "OpenAI", client)
    monkeypatch.setattr(module.random, "uniform", lambda a, b: 0.25)
    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    adapter = module.OpenAIAPIInterface({"api_key": "fake", "max_retries": 4, "retry_delay": 2, "request_timeout": 37})
    monkeypatch.setattr(adapter, "_extract_content", lambda response, elapsed: {"content": "final"})
    if exhausted:
        with pytest.raises(TimeoutError):
            await adapter.generate_response("prompt", {})
    else:
        assert await adapter.generate_response("prompt", {}) == {"content": "final"}
    assert len(calls) == 4
    assert delays == [2.25, 4.25, 8.25]
    assert settings[0]["timeout"] == 37
    assert settings[0]["max_retries"] == 0


@pytest.mark.asyncio
async def test_cancel_does_not_detach_started_blocking_model_request(monkeypatch):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def create(**kwargs):
        started.set()
        assert release.wait(5)
        finished.set()
        return object()

    monkeypatch.setattr(
        module,
        "OpenAI",
        lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
    )
    adapter = module.OpenAIAPIInterface({"api_key": "fake"})
    task = asyncio.create_task(adapter.generate_response("prompt", {}))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()


@pytest.mark.parametrize(
    "config", [{"max_retries": 0}, {"request_timeout": 0}, {"request_timeout": float("inf")}, {"retry_delay": -1}]
)
def test_invalid_model_budget_rejected(config):
    with pytest.raises(ValueError):
        module.OpenAIAPIInterface(config)
