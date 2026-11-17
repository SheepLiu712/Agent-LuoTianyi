"""音频模型模块的信封、prompt 和客户端委托。"""

import pytest

from src.infrastructure.models.audio.module import AudioModelModule
from src.infrastructure.models.llm.prompts import PromptTemplate


class _Interface:
    def __init__(self):
        self.calls = []

    async def generate_response(self, prompt, audio_base64, **kwargs):
        self.calls.append((prompt, audio_base64, kwargs))
        return {"content": "{}", "usage": {}, "response_time_s": 0.1}


class _Executor:
    def __init__(self):
        self.calls = []

    async def delegate(self, user_id, **kwargs):
        self.calls.append((user_id, kwargs))
        return {"content": "delegated", "usage": {}, "response_time_s": 0.1}


@pytest.mark.asyncio
async def test_audio_module_uses_server_interface_and_json_envelope():
    interface = _Interface()
    module = AudioModelModule("audio", {"use_json": True}, PromptTemplate("analyze"), interface)
    response = await module.generate_response("data:audio/mp4;base64,AA==")
    assert response["content"] == "{}"
    assert interface.calls == [("analyze", "data:audio/mp4;base64,AA==", {"response_format": {"type": "json_object"}})]


@pytest.mark.asyncio
async def test_audio_module_delegates_with_audio_kind(monkeypatch):
    interface = _Interface()
    executor = _Executor()
    monkeypatch.setattr("src.infrastructure.models.audio.module.get_trace_context", lambda: {"user_id": "u"})
    module = AudioModelModule(
        "audio",
        {"audio": {"client_model_type": "audio_understanding"}},
        PromptTemplate("analyze"),
        interface,
        executor,
    )
    response = await module.generate_response("data:audio/mp4;base64,AA==")
    assert response["content"] == "delegated"
    assert executor.calls[0][1]["model_kind"] == "audio"
    assert executor.calls[0][1]["audio_base64"] == "data:audio/mp4;base64,AA=="
    assert interface.calls == []
