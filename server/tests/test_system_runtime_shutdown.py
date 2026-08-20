import asyncio
from types import SimpleNamespace

from src.capabilities.capability_manager import CapabilityManager
from src.capabilities.speech.speech import SpeechCapability
from src.capabilities.speech.tts_module import TTSModule
from src.system.system_runtime import SystemRuntime


def test_system_runtime_shutdown_releases_capabilities_before_database():
    calls: list[str] = []

    async def record_async(name: str) -> None:
        calls.append(name)

    tts_module = object.__new__(TTSModule)
    tts_module.tts_server = SimpleNamespace(stop=lambda: calls.append("tts_server"))
    speech = object.__new__(SpeechCapability)
    speech.tts_module = {"luotianyi": tts_module}
    capability_manager = object.__new__(CapabilityManager)
    capability_manager.speech = speech

    runtime = SystemRuntime(
        user_interface=SimpleNamespace(),
        world=SimpleNamespace(
            stop_background_services=lambda: record_async("world"),
        ),
        database_manager=SimpleNamespace(
            shutdown=lambda: record_async("database"),
        ),
        agent_runtime=SimpleNamespace(),
        capability_manager=capability_manager,
        chat_session_manager=SimpleNamespace(
            stop_background_services=lambda: record_async("chat_sessions"),
        ),
        llm_service=SimpleNamespace(),
        observability=SimpleNamespace(),
        owns_observability=False,
    )

    asyncio.run(runtime.shutdown())

    assert calls == ["world", "chat_sessions", "tts_server", "database"]
