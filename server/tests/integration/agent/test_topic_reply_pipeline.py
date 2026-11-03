"""从统一 topic_extract 到真实回复解析和 Say/Sing ActionPlan 的离线链路。"""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from support.reply_skill import make_reply_skill
from support.retrieval import stub_retrieval, stub_singing
from support.routing_support import Sink, request
from support.skill_support import invocation

import src.domain.agent as d
from src.agent import Agent
from src.agent.context import UserContextSnapshot
from src.agent.handlers.reply_skills import ReplySkills
from src.agent.handlers.stimulus.chat import ChatReplyHandler
from src.agent.handlers.stimulus.proactive import FirstLoginHandler
from src.agent.handlers.stimulus.router import StimulusRouter
from src.agent.skills.cognitive import JargonRecognitionSkill
from src.agent.skills.cognitive._prompt_assembly import RealizationPromptAssembler
from src.agent.skills.cognitive._reply_resources import ReplyResources
from src.agent.skills.cognitive._response_parser import StructuredResponseParser
from src.agent.skills.cognitive.topic_extraction import TopicExtractionSkill
from src.agent.skills.contracts import ReplyDraft


def pipeline(
    *,
    attempts=("权御天下",),
    queries=("用户喜欢的歌",),
    available=True,
    broken=False,
    song_id="权御天下",
    reply_song=None,
):
    events = []
    calls = {}

    async def extract(**kwargs):
        events.append("topic_extract")
        calls["extract"] = kwargs
        return "invalid json" if broken else json.dumps({"memory_attempts": queries, "sing_attempts": attempts})

    async def recall(user_id, keys):
        events.append("recall")
        calls["recall"] = (user_id, keys)
        return SimpleNamespace(hits=(), render_for_prompt=lambda: ["用户喜欢古风"])

    async def select(character_id, songs, **kwargs):
        events.append("songs")
        calls["songs"] = (character_id, songs, kwargs)
        return (song_id, "副歌") if available else (song_id, None)

    async def reply(**kwargs):
        events.append("replier")
        calls["replier"] = kwargs
        # A model-generated singing line must not become an action without a resolved segment.
        return f"[开心]好呀\n[sing]{reply_song or song_id}\n[开心]还想聊点什么？"

    extractor = TopicExtractionSkill(
        {"llm_module": {}},
        SimpleNamespace(register_llm_module=lambda *args: SimpleNamespace(generate_response=extract)),
        understanding=JargonRecognitionSkill(song_names=("权御天下",)),
    )
    generator = ReplyResources.__new__(ReplyResources)
    generator.character_name = "洛天依"
    generator.character_persona = "歌手"
    generator.speaking_style = "自然"
    generator.prompt_assembler = RealizationPromptAssembler()
    generator.llm = SimpleNamespace(generate_response=reply)
    generator.response_parser = StructuredResponseParser(
        default_draft=ReplyDraft("你好", "你好", "normal", None),
        tone_mapper=lambda tone: ("开心", "happy"),
    )
    singing = SimpleNamespace(build_sing_plan=select, get_segment_lyrics=lambda *args: "歌词")
    composition = ReplySkills(
        topic_extraction=extractor,
        retrieval=stub_retrieval({"luotianyi": SimpleNamespace(search_memory_context_for_topic=recall)}),
        singing=stub_singing(singing),
        reply=make_reply_skill({"luotianyi": generator}),
    )
    return composition, events, calls


class Conversation:
    def __init__(self):
        self.entries = []

    def read(self):
        return SimpleNamespace(summary=SimpleNamespace(text="以前讨论过歌曲"), entries=tuple(self.entries))

    async def append(self, entries):
        self.entries.extend(entries)


def context():
    return SimpleNamespace(
        identity=SimpleNamespace(character_id="luotianyi", user_id="u", interaction_id="i"),
        conversation=Conversation(),
        user=SimpleNamespace(read=UserContextSnapshot),
    )


async def run_handler(composition, mode="chat"):
    req = replace(
        request(),
        prepared_inputs=(
            d.PreprocessedInput(
                stimulus_id="m2",
                text="请唱权御天下，也聊聊我的喜好",
            ),
        ),
    )
    handler = ChatReplyHandler(composition)
    if mode == "memory":
        req = replace(
            req,
            prepared_inputs=(
                d.PreprocessedInput(stimulus_id="m2", text="请记住我喜欢古风"),
                d.PreprocessedInput(stimulus_id="m1", text="请唱权御天下"),
            ),
        )
        handler = ChatReplyHandler(
            composition,
            memory_intent=SimpleNamespace(detect=lambda text: text if text.startswith("请记住") else None),
            memory_commit=SimpleNamespace(
                commit_fact=AsyncMock(return_value=SimpleNamespace(memory_ids=("revision",)))
            ),
        )
    if mode == "proactive":
        stimulus = d.ProactivePromptDue(
            stimulus_id="reminder",
            schema_version=1,
            occurred_at=req.interaction.now,
            source=d.StimulusSource.STAGE,
            target_character_ids=("luotianyi",),
            user_id="u",
            ephemeral=True,
            reason=d.ProactiveReason(value="birthday"),
            due_at=req.interaction.now,
            dedup_key="birthday:u",
            fact_refs=(),
        )
        req = replace(req, stimulus=stimulus)
        handler = FirstLoginHandler(prepared_names=(), prepared_speech=None, skills=composition)
    agent = Agent(character_id="luotianyi", stimulus_router=StimulusRouter([(req.stimulus.kind, handler)]))
    sink = Sink()
    ctx = context()
    report = await agent.handle_stimulus(req, sink, context=ctx)
    return report, [action for plan in sink.values for action in plan.actions], ctx


@pytest.mark.parametrize("mode", ["chat", "memory", "proactive"])
async def test_unavailable_requested_song_becomes_an_explicit_learning_action(mode):
    composition, _, _ = pipeline(available=False)
    report, actions, _ = await run_handler(composition, mode)
    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    assert [action.song_id for action in actions if isinstance(action, d.RequestSongLearning)] == ["权御天下"]
    assert not any(isinstance(action, d.Sing) for action in actions)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["chat", "memory"])
async def test_extract_recall_song_then_replier_produces_ordered_say_sing_actions(mode):
    composition, events, calls = pipeline()
    report, actions, ctx = await run_handler(composition, mode)
    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    assert events == ["topic_extract", "recall", "songs", "replier"]
    replies = [action for action in actions if isinstance(action, (d.Say, d.Sing))]
    assert [action.kind for action in replies] == [d.ActionKind.SAY, d.ActionKind.SING, d.ActionKind.SAY]
    assert replies[1].song_id == "权御天下" and replies[1].segment_id == "副歌"
    assert "歌词" in replies[1].content
    assert calls["recall"] == ("u", ["用户喜欢的歌"])
    assert calls["songs"][2]["confirmed_intent"] is True
    assert "用户喜欢古风" in calls["replier"]["extra_knowledge"]
    assert "权御天下" in calls["replier"]["sing_requirement"]
    assert calls["extract"]["conversation_history"] == "以前讨论过歌曲"
    assert len(ctx.conversation.entries) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["chat", "memory", "proactive"])
async def test_no_singing_decision_never_queries_song_catalog_or_emits_sing(mode):
    composition, events, _ = pipeline(attempts=(), queries=())
    report, actions, _ = await run_handler(composition, mode)
    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    assert events == ["topic_extract", "replier"]
    assert not any(isinstance(action, d.Sing) for action in actions)
    assert any(isinstance(action, d.Say) for action in actions)


@pytest.mark.asyncio
async def test_unavailable_song_does_not_create_invalid_sing_action():
    composition, events, calls = pipeline(available=False)
    _, actions, _ = await run_handler(composition)
    assert events == ["topic_extract", "recall", "songs", "replier"]
    assert not any(isinstance(action, d.Sing) for action in actions)
    assert calls["replier"]["sing_requirement"] == "在回复中你不需要为用户唱歌"


@pytest.mark.asyncio
async def test_extraction_parse_failure_still_replies_without_recall_or_song():
    composition, events, _ = pipeline(broken=True)
    _, actions, _ = await run_handler(composition)
    assert events == ["topic_extract", "replier"]
    assert not any(isinstance(action, d.Sing) for action in actions)


@pytest.mark.asyncio
async def test_cancellation_after_extraction_stops_recall_song_and_replier():
    composition, events, _ = pipeline()
    call = invocation()
    original = composition.topic_extraction.extract

    async def cancel_after_extract(*args, **kwargs):
        decision = await original(*args, **kwargs)
        call.cancellation.cancel(d.CancellationReason.SUPERSEDED)
        return decision

    composition.topic_extraction.extract = cancel_after_extract
    result = await ChatReplyHandler(composition)._generate_reply(
        call,
        user_context=UserContextSnapshot(),
        reply_topic="唱歌",
        conversation_history="",
    )
    assert result.drafts == ()
    assert events == ["topic_extract"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["chat", "memory", "proactive"])
@pytest.mark.parametrize("invalid", [("另一首歌", "副歌"), ("权御天下", "不存在的唱段")])
async def test_generated_singing_cannot_override_selected_song_or_segment(mode, invalid):
    from src.agent.handlers.reply_skills import ReplySkills

    skills, _, _ = pipeline()

    async def malicious_drafts(character_id, **kwargs):
        yield ReplyDraft("正常回答", "正常回答", "happy", "开心")
        yield ReplyDraft("不应演唱", "", "", None, sing=invalid)

    skills = ReplySkills(
        skills.topic_extraction, skills.retrieval, skills.singing, SimpleNamespace(generate=malicious_drafts)
    )
    report, actions, ctx = await run_handler(skills, mode)
    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    assert not any(isinstance(action, d.Sing) for action in actions)
    assert [entry.content.text for entry in ctx.conversation.entries] == ["正常回答"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["chat", "memory", "proactive"])
async def test_display_title_sings_the_selected_canonical_song_with_correct_lyrics(mode):
    skills, _, _ = pipeline(attempts=("HelloByeDays",), song_id="HelloByeDays", reply_song="Hello&Bye,Days")
    report, actions, ctx = await run_handler(skills, mode)
    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    sung = [action for action in actions if isinstance(action, d.Sing)]
    assert len(sung) == 1
    assert (sung[0].song_id, sung[0].segment_id) == ("HelloByeDays", "副歌")
    record = next(entry.content for entry in ctx.conversation.entries if hasattr(entry.content, "song"))
    assert record.song == "HelloByeDays" and record.segment == "副歌"
    assert record.text.endswith("歌词")
