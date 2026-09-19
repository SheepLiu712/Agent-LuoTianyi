"""通过真实运行时构造和查找验证门面身份及兼容对象隔离。"""
import asyncio
import threading

import pytest

import src.domain.agent as d
from src.agent_runtime import agent_runtime as runtime_module


def test_lookup_returns_cached_facade_separate_from_legacy(runtime):
    default = runtime.get_agent()
    assert default is runtime.get_agent("luotianyi")
    assert default is not runtime.get_agent("miku")
    assert default is not runtime.get_character_runtime().conscious
    assert callable(getattr(default, "handle_stimulus", None)), "get_agent 尚未返回两接口门面"
    assert callable(getattr(default, "realize_action_plan", None))


def test_runtime_reuses_stateless_handlers_within_each_agent(runtime):
    agent = runtime.get_agent()
    stimulus_handlers = agent._stimulus_router._handlers
    preprocessing_kinds = (
        d.StimulusKind.TEXT_MESSAGE,
        d.StimulusKind.IMAGE_MESSAGE,
        d.StimulusKind.VOICE_MESSAGE,
        d.StimulusKind.USER_TYPING,
        d.StimulusKind.IMAGE_SELECTION_OPENED,
        d.StimulusKind.IMAGE_SELECTION_CLOSED,
    )
    preprocessing = stimulus_handlers[preprocessing_kinds[0]]
    assert all(stimulus_handlers[kind] is preprocessing for kind in preprocessing_kinds)

    song_learned = stimulus_handlers[d.StimulusKind.SONG_LEARNED]
    request_learning = agent._action_router._handlers[d.ActionKind.REQUEST_SONG_LEARNING]
    assert song_learned._dispatch is request_learning._dispatch


@pytest.mark.parametrize("character_id", ["missing", "disabled", "", " "])
def test_explicit_invalid_character_never_falls_back(runtime, character_id):
    with pytest.raises(KeyError):
        runtime.get_agent(character_id)


@pytest.mark.parametrize("character_id", [0, False, [], {}])
def test_lookup_rejects_non_string_identity(runtime, character_id):
    with pytest.raises(TypeError):
        runtime.get_agent(character_id)


async def test_legacy_registry_keeps_old_agent_and_callable_methods(runtime):
    legacy = runtime.get_character_runtime().conscious
    assert runtime.agent_registry.get() is legacy
    assert runtime.agent_registry.all()["luotianyi"] is legacy
    assert await legacy.search_song_facts_for_topic(["歌曲"]) == ["旧歌曲事实"]


async def test_shutdown_repeatedly_closes_owned_store_once(runtime, runtime_dependencies):
    _, store = runtime_dependencies
    await runtime.shutdown()
    await runtime.shutdown()
    assert store.close_calls == 1


async def test_shutdown_cancellation_keeps_vector_store_close_owned(runtime):
    started = threading.Event()
    release = threading.Event()

    class BlockingStore:
        def __init__(self):
            self.close_calls = 0

        def close(self):
            self.close_calls += 1
            started.set()
            release.wait(2)

    store = BlockingStore()
    runtime.vector_store = store
    runtime.shutdown_timeout_seconds = 1
    closing = asyncio.create_task(runtime.shutdown())
    assert await asyncio.to_thread(started.wait, 0.5)
    closing.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await closing

    assert store.close_calls == 1
    assert runtime._shutdown_complete is False
    await runtime.shutdown()
    assert runtime._shutdown_complete is True
    assert store.close_calls == 1


async def test_shutdown_retries_vector_store_close_after_failure(runtime):
    class FlakyStore:
        def __init__(self):
            self.close_calls = 0

        def close(self):
            self.close_calls += 1
            if self.close_calls == 1:
                raise RuntimeError("close failed")

    store = FlakyStore()
    runtime.vector_store = store
    with pytest.raises(RuntimeError, match="close failed"):
        await runtime.shutdown()

    assert runtime._shutdown_complete is False
    assert runtime._shutdown_task is None
    await runtime.shutdown()
    assert runtime._shutdown_complete is True
    assert store.close_calls == 2


def test_initialization_failure_clears_global_and_closes_store(runtime_dependencies):
    kwargs, store = runtime_dependencies
    kwargs["config"]["character_registry"]["characters"]["miku"]["default_target"] = True
    runtime_module.set_agent_runtime(None)
    with pytest.raises(ValueError, match="Multiple default"):
        runtime_module.AgentRuntime(**kwargs)
    assert store.close_calls == 1
    with pytest.raises(ValueError, match="not been initialized"):
        runtime_module.get_agent_runtime()
