"""文本输入的预处理与落库：先落库再 READY，且不等于消费。"""
from datetime import datetime
from types import SimpleNamespace

import pytest

import src.domain.agent as d
from src.agent import Agent
from src.agent.handlers.stimulus.chat import ChatPreprocessingHandler
from src.agent.handlers.stimulus.router import StimulusRouter
from src.agent.skills.cognitive import TextPreprocessingSkill
from routing_support import Sink, request


class _Understanding:
    """固定返回给定关键词的文本预处理替身。"""

    def __init__(self, terms=()):
        self.terms = tuple(terms)

    def extract_terms(self, text):
        return self.terms


class _Conversation:
    def __init__(self):
        self.entries = []

    async def append(self, entries):
        self.entries.extend(entries)


def context(interaction_id="i", user_id="u", character_id="luotianyi"):
    value = SimpleNamespace(identity=SimpleNamespace(
        interaction_id=interaction_id, user_id=user_id, character_id=character_id))
    value.conversation = _Conversation()
    return value


def agent(terms=("《歌》是一首歌",)):
    return Agent(character_id="luotianyi", stimulus_router=StimulusRouter([
        (d.StimulusKind.TEXT_MESSAGE, ChatPreprocessingHandler(_Understanding(terms)))]))


@pytest.mark.asyncio
async def test_text_message_is_persisted_before_ready_and_not_consumed():
    ctx = context()
    report = await agent().handle_stimulus(request(), Sink(), context=ctx)
    assert len(ctx.conversation.entries) == 1
    entry = ctx.conversation.entries[0]
    assert entry.source == "user"
    assert entry.content.text == "你好"
    assert entry.content.terms == ("《歌》是一首歌",)
    assert isinstance(entry.timestamp, datetime) and entry.timestamp.tzinfo is None
    assert report.preprocessed_input.stimulus_id == "m2"
    assert report.preprocessed_input.text == "你好"
    assert report.preprocessed_input.conversation_entry_ids == (entry.entry_id,)
    assert report.consumed_pending_stimulus_ids == ()
    assert report.retained_pending_stimulus_ids == ("m2", "m1")
    assert report.emitted_plan_ids == ()
    assert report.request_status is d.HandlingRequestStatus.COMPLETED


@pytest.mark.asyncio
async def test_missing_context_fails_instead_of_silently_skipping_persistence():
    report = await agent().handle_stimulus(request(), Sink())
    assert report.request_status is d.HandlingRequestStatus.FAILED
    assert report.error_code is d.HandlingErrorCode.INTERNAL_ERROR
    assert report.preprocessed_input is None


def test_text_preprocessing_skill_returns_terms(monkeypatch):
    class _Linker:
        def __init__(self, config):
            self.config = config

        def extract_and_verify(self, text):
            return ["《歌》是一首歌"] if "歌" in text else []

    monkeypatch.setattr(
        "src.agent.skills.cognitive.text_preprocessing.SongEntityLinker", _Linker)
    skill = TextPreprocessingSkill({"song_entity_linker": {"songname_file": "unused"}})
    assert skill.extract_terms("唱《歌》") == ("《歌》是一首歌",)
    assert skill.extract_terms("随便聊聊") == ()
    with pytest.raises(TypeError):
        skill.extract_terms(None)
