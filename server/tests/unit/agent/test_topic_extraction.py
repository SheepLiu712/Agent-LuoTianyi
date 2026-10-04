"""同一次模型调用产生检索 key 和唱歌 attempt，普通聊天也不能跳过。"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.agent.skills.cognitive.text_preprocessing import TextPreprocessingSkill
from src.agent.skills.cognitive.topic_extraction import TopicExtractionSkill
from src.agent.skills.contracts import TopicExtraction


def skill(response=None, error=None):
    llm = SimpleNamespace(generate_response=AsyncMock(return_value=response, side_effect=error))
    service = SimpleNamespace(register_llm_module=Mock(return_value=llm))
    extractor = TopicExtractionSkill(
        {"llm_module": {"prompt_name": "topic_extraction_prompt"}},
        service,
        understanding=TextPreprocessingSkill(song_names=("权御天下",)),
    )
    return extractor, llm, service


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["今天天气不错", "你记得我的家乡吗", "这首歌写得很好", "不用唱歌"])
async def test_every_reply_extracts_once_even_without_singing_cues(message):
    extractor, llm, service = skill('{"memory_attempts": ["用户的家乡"], "sing_attempts": []}')
    result = await extractor.extract(message, conversation_history="历史")
    assert result == TopicExtraction(memory_queries=("用户的家乡",))
    llm.generate_response.assert_awaited_once()
    assert llm.generate_response.call_args.kwargs["message_content"] == message
    assert llm.generate_response.call_args.kwargs["conversation_history"] == "历史"
    assert service.register_llm_module.call_args.args[0] == "topic_extract"


@pytest.mark.asyncio
async def test_one_response_returns_both_lists_without_coercing_or_losing_attempts():
    extractor, llm, _ = skill(
        json.dumps(
            {
                "memory_attempts": [" 用户偏好 ", "用户偏好", "家乡", ""],
                "sing_attempts": ["权御天下", "random_song", "权御天下"],
            }
        )
    )
    result = await extractor.extract("唱首我喜欢的歌，也聊聊我的家乡")
    assert result == TopicExtraction(("用户偏好", "家乡"), ("权御天下", "random_song"))
    llm.generate_response.assert_awaited_once()


@pytest.mark.asyncio
async def test_song_terms_are_only_hints_not_singing_attempts():
    extractor, llm, _ = skill('{"memory_attempts": [], "sing_attempts": []}')
    result = await extractor.extract("不用唱《权御天下》，聊聊这首歌")
    assert result.sing_attempts == ()
    assert "权御天下" in llm.generate_response.call_args.kwargs["terms"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        "",
        "not-json",
        "[]",
        "null",
        '{"memory_attempts": "query", "sing_attempts": ["song"]}',
        '{"memory_attempts": [42], "sing_attempts": ["song"]}',
        '{"memory_attempts": ["query"], "sing_attempts": [{"song": "song"}]}',
        '{"sing_attempts": [null]}',
    ],
)
async def test_malformed_output_fails_closed_for_both_decisions(response):
    extractor, llm, _ = skill(response)
    assert await extractor.extract("请唱歌") == TopicExtraction()
    llm.generate_response.assert_awaited_once()


@pytest.mark.asyncio
async def test_model_error_does_not_retry_or_promote_raw_input_to_query():
    extractor, llm, _ = skill(error=RuntimeError("offline"))
    assert await extractor.extract("请唱权御天下") == TopicExtraction()
    llm.generate_response.assert_awaited_once()


@pytest.mark.asyncio
async def test_fenced_response_is_supported():
    extractor, _, _ = skill("""```json
{"memory_attempts": ["记忆"], "sing_attempts": ["random_song"]}
```""")
    assert await extractor.extract("听歌") == TopicExtraction(("记忆",), ("random_song",))


@pytest.mark.asyncio
async def test_task_cancellation_is_not_swallowed():
    extractor, _, _ = skill(error=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await extractor.extract("你好")


@pytest.mark.asyncio
async def test_missing_model_config_has_no_singing_or_raw_input_recall():
    service = SimpleNamespace(register_llm_module=Mock())
    extractor = TopicExtractionSkill({}, service, understanding=TextPreprocessingSkill())
    assert await extractor.extract("唱歌") == TopicExtraction()
    service.register_llm_module.assert_not_called()
