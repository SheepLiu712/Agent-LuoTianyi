import sys
from pathlib import Path

import pytest


server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.agent.main_chat import DEFAULT_LLM_FAILURE_RESPONSE, MainChat
from src.utils.llm.llm_api_interface import LLMContentInspectionError


class RecordingLogger:
    def __init__(self):
        self.warnings = []
        self.errors = []

    def warning(self, message):
        self.warnings.append(message)

    def error(self, message):
        self.errors.append(message)


class SequenceLLM:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def generate_response(self, **_kwargs):
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def build_main_chat(llm, *, max_attempts=2, fallback=DEFAULT_LLM_FAILURE_RESPONSE):
    chat = MainChat.__new__(MainChat)
    chat.llm = llm
    chat.logger = RecordingLogger()
    chat.llm_failure_max_attempts = max_attempts
    chat.llm_failure_retry_delay_seconds = 0
    chat.llm_failure_response = fallback
    return chat


@pytest.mark.asyncio
async def test_transient_llm_failure_retries_then_returns_response():
    llm = SequenceLLM(TimeoutError("first attempt timed out"), "[中性]现在可以回复了")
    chat = build_main_chat(llm)

    response = await chat._call_llm(reply_topic="hello")

    assert response == "[中性]现在可以回复了"
    assert llm.calls == 2
    assert len(chat.logger.warnings) == 1
    assert chat.logger.errors == []


@pytest.mark.asyncio
async def test_exhausted_llm_failure_has_bounded_attempts_and_non_empty_fallback():
    llm = SequenceLLM(TimeoutError("timeout"), RuntimeError("provider unavailable"))
    chat = build_main_chat(llm)

    response = await chat._call_llm(reply_topic="hello")

    assert llm.calls == 2
    assert response == DEFAULT_LLM_FAILURE_RESPONSE
    assert response.strip()
    assert response.startswith("[中性]")
    assert len(chat.logger.errors) == 1


@pytest.mark.asyncio
async def test_empty_llm_responses_are_retried_then_use_non_empty_fallback():
    llm = SequenceLLM("", "   ")
    chat = build_main_chat(llm)

    response = await chat._call_llm(reply_topic="hello")

    assert llm.calls == 2
    assert response == DEFAULT_LLM_FAILURE_RESPONSE


@pytest.mark.asyncio
async def test_content_inspection_failure_is_not_retried():
    llm = SequenceLLM(
        LLMContentInspectionError("blocked"),
        AssertionError("must not retry content inspection failures"),
    )
    chat = build_main_chat(llm)

    response = await chat._call_llm(reply_topic="hello")

    assert llm.calls == 1
    assert response == "[中性]这个话题不太合适，我们聊点别的吧"


def test_configured_failure_text_is_always_structured_and_non_empty():
    assert MainChat._structured_failure_response("稍后再试") == "[中性]稍后再试"
    assert MainChat._structured_failure_response("") == DEFAULT_LLM_FAILURE_RESPONSE
    assert MainChat._structured_failure_response("[中性]") == DEFAULT_LLM_FAILURE_RESPONSE
