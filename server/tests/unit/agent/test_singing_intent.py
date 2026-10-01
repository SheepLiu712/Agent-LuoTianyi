"""唱歌意图决策层的保守门控。"""

import pytest

from src.agent.skills.cognitive.singing_intent import SingingIntentSkill


class _LLM:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    async def generate_response(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class _Service:
    def __init__(self, llm):
        self.llm = llm
        self.registrations = []

    def register_llm_module(self, name, config):
        self.registrations.append((name, config))
        return self.llm


def skill(response=None, error=None):
    llm = _LLM(response, error)
    service = _Service(llm)
    return SingingIntentSkill({"llm_module": {"prompt_name": "topic_extraction_prompt"}}, service), llm


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "terms"),
    [
        ("《权御天下》是我很喜欢的一首歌", ("《权御天下》是一首歌",)),
        ("我记得歌词里有一句为你明灯三千", ("《牵丝戏》是一首歌",)),
        ("不用唱权御天下，我们聊聊这首歌", ("《权御天下》是一首歌",)),
    ],
)
async def test_mentions_and_lyrics_do_not_trigger_singing(message, terms):
    intent, _ = skill('{"sing_attempts": []}')
    assert await intent.decide(message, terms=terms) == ()


@pytest.mark.asyncio
async def test_explicit_song_request_returns_song_name():
    intent, _ = skill('{"sing_attempts": ["权御天下"]}')
    assert await intent.decide("请唱权御天下", terms=("《权御天下》是一首歌",)) == ("权御天下",)


@pytest.mark.asyncio
async def test_unspecified_song_request_returns_random_song():
    intent, _ = skill('{"sing_attempts": ["random_song"]}')
    assert await intent.decide("我想听歌") == ("random_song",)


@pytest.mark.asyncio
async def test_llm_failure_falls_back_to_no_singing():
    intent, _ = skill(error=RuntimeError("offline"))
    assert await intent.decide("请唱权御天下", terms=("《权御天下》是一首歌",)) == ()


@pytest.mark.asyncio
async def test_invalid_llm_response_falls_back_to_no_singing():
    intent, _ = skill("not-json")
    assert await intent.decide("请唱权御天下", terms=("《权御天下》是一首歌",)) == ()


@pytest.mark.asyncio
async def test_obvious_non_candidate_skips_llm():
    intent, llm = skill('{"sing_attempts": ["random_song"]}')
    assert await intent.decide("今天天气不错") == ()
    assert llm.calls == []
