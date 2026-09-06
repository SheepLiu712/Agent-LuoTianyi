"""通过真实运行时构造和查找验证门面身份及兼容对象隔离。"""
import pytest

from src.agent_runtime import agent_runtime as runtime_module


def test_lookup_returns_cached_facade_separate_from_legacy(runtime):
    default = runtime.get_agent()
    assert default is runtime.get_agent("luotianyi")
    assert default is not runtime.get_agent("miku")
    assert default is not runtime.get_character_runtime().conscious
    assert callable(getattr(default, "handle_stimulus", None)), "get_agent 尚未返回两接口门面"
    assert callable(getattr(default, "realize_action_plan", None))


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


def test_initialization_failure_clears_global_and_closes_store(runtime_dependencies):
    kwargs, store = runtime_dependencies
    kwargs["config"]["character_registry"]["characters"]["miku"]["default_target"] = True
    runtime_module.set_agent_runtime(None)
    with pytest.raises(ValueError, match="Multiple default"):
        runtime_module.AgentRuntime(**kwargs)
    assert store.close_calls == 1
    with pytest.raises(ValueError, match="not been initialized"):
        runtime_module.get_agent_runtime()
