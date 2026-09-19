import asyncio
from types import SimpleNamespace

from src.infrastructure.runtime import InfrastructureRuntime
from src.infrastructure.speech.speech import SpeechBackend
from src.infrastructure.speech.tts_module import TTSModule
from src.system.system_runtime import SystemRuntime
from src.utils.llm.client_llm_executor import ClientLLMExecutor


def test_system_runtime_shutdown_releases_infrastructure_before_database():
    calls: list[str] = []

    async def record_async(name: str) -> None:
        calls.append(name)

    tts_module = object.__new__(TTSModule)
    tts_module.tts_server = SimpleNamespace(stop=lambda: calls.append("tts_server"))
    speech = SpeechBackend({})
    speech.tts_module = {"luotianyi": tts_module}
    infrastructure = object.__new__(InfrastructureRuntime)
    infrastructure.speech = speech
    infrastructure._stop_lock = asyncio.Lock()
    infrastructure._stopped = False

    runtime = SystemRuntime(
        user_interface=SimpleNamespace(),
        world=SimpleNamespace(
            stop_background_services=lambda: record_async("world"),
        ),
        database_manager=SimpleNamespace(
            shutdown=lambda: record_async("database"),
        ),
        agent_runtime=SimpleNamespace(),
        infrastructure=infrastructure,
        llm_service=SimpleNamespace(),
        observability=SimpleNamespace(),
        client_llm_executor=ClientLLMExecutor(),
        owns_observability=False,
    )

    asyncio.run(runtime.shutdown())

    assert calls == ["world", "tts_server", "database"]
