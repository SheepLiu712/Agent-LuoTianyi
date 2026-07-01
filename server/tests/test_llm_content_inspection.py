import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.agent.main_chat import MainChat
from src.utils.llm.llm_api_interface import LLMContentInspectionError, OpenAIAPIInterface


class FakeLogger:
    def __init__(self):
        self.warnings = []

    def warning(self, message):
        self.warnings.append(message)

    def error(self, *_args, **_kwargs):
        pass


class DataInspectionException(Exception):
    code = "data_inspection_failed"
    body = {
        "error": {
            "message": "<400> InternalError.Algo.DataInspectionFailed: Input text data may contain inappropriate content.",
            "code": "data_inspection_failed",
        }
    }


def test_openai_interface_does_not_retry_content_inspection_failure():
    calls = {"count": 0}

    def create(**_kwargs):
        calls["count"] += 1
        raise DataInspectionException("Error code: 400 - data_inspection_failed")

    interface = OpenAIAPIInterface.__new__(OpenAIAPIInterface)
    interface.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    interface.model = "test-model"
    interface.max_retries = 3
    interface.retry_delay = 0
    interface.default_parameters = {}
    interface.can_enable_thinking = False
    interface.can_use_json = False
    interface.logger = FakeLogger()

    async def run():
        try:
            await interface.generate_response("test", params={})
        except LLMContentInspectionError:
            return
        raise AssertionError("Expected LLMContentInspectionError")

    asyncio.run(run())
    assert calls["count"] == 1
    assert any("不再重试" in item for item in interface.logger.warnings)


def test_main_chat_returns_topic_switch_reply_on_content_inspection_failure():
    class FakeLLM:
        async def generate_response(self, **_kwargs):
            raise LLMContentInspectionError("data_inspection_failed")

    main_chat = MainChat.__new__(MainChat)
    main_chat.llm = FakeLLM()
    main_chat.logger = FakeLogger()

    response = asyncio.run(main_chat._call_llm(reply_topic="bad topic"))
    assert response == "[中性]这个话题不太合适，我们聊点别的吧"
