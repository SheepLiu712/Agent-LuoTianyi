"""明确记忆请求的提交、承诺与隔离契约。"""
from dataclasses import replace

import pytest
from routing_support import Sink, request

import src.domain.agent as d
from src.agent import Agent
from src.agent.handlers.stimulus.chat import (
    _MEMORY_ACK_REPLY_TOPIC_PREFIX,
    ChatReplyHandler,
)
from src.agent.handlers.stimulus.router import StimulusRouter
from src.agent.skills.cognitive import ExplicitMemoryIntentSkill, ReplyDraft
from src.agent.skills.mutation import IntentionalMemoryCommit


class _Conversation:
    def read(self):
        return type("Snapshot", (), {"summary": type("Summary", (), {"text": ""})(), "entries": ()})()

    async def append(self, entries):
        return None


class _Context:
    def __init__(self, *, user_id="u"):
        self.identity = type("Identity", (), {
            "interaction_id": "i", "user_id": user_id, "character_id": "luotianyi",
        })()
        self.conversation = _Conversation()


class _Understanding:
    def extract_terms(self, text):
        return ()


class _Composer:
    def __init__(self, events=None):
        self.events = events
        self.calls = []

    async def compose(self, **kwargs):
        self.calls.append(kwargs)
        if self.events is not None:
            self.events.append("compose")
            return (ReplyDraft(
                content="compose-memory-ack",
                sound_content="compose-memory-ack-sound",
                tone="gentle",
                expression="smile",
            ),)
        pytest.fail("普通回复生成只允许由明确记忆确认路径按提示调用")


class _Intent:
    def detect(self, text):
        marker = "请记住"
        return text.split(marker, 1)[1].strip(" ：:，,") if marker in text else None


class _Commit:
    def __init__(self, events, *, failure=None):
        self.events = events
        self.failure = failure
        self.calls = []
        self._revisions = {}

    async def commit(self, *, character_id, user_id, content):
        self.calls.append((character_id, user_id, content))
        self.events.append("commit")
        if self.failure is not None:
            raise self.failure
        return self._revisions.setdefault((character_id, user_id, content), "memory-revision-1")


def _deadline(text="请记住我喜欢乌龙茶", *, user_id="u"):
    prepared = d.PreprocessedInput(stimulus_id="m2", text=text, conversation_entry_ids=("e1",))
    value = request()
    interaction = replace(value.interaction, user_id=user_id)
    return replace(value, interaction=interaction, prepared_inputs=(prepared,))


def _agent(commit, *, composer=None):
    handler = ChatReplyHandler(composer or _Composer(), _Understanding(), _Intent(), commit)
    return Agent(character_id="luotianyi", stimulus_router=StimulusRouter((
        (d.StimulusKind.TEXT_MESSAGE, handler),
    )))


@pytest.mark.asyncio
async def test_acknowledgement_is_emitted_after_memory_commit():
    events = []

    async def observe(plan):
        events.append("promise")
        return d.PlanReceipt(plan_id=plan.plan_id, status=d.PlanAcceptanceStatus.ACCEPTED)

    report = await _agent(_Commit(events), composer=_Composer(events)).handle_stimulus(
        _deadline(), Sink(observe), context=_Context(),
    )

    assert events == ["commit", "compose", "promise"]
    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    assert report.consumed_pending_stimulus_ids == ("m2", "m1")


@pytest.mark.asyncio
async def test_memory_acknowledgement_uses_composition_hint_after_commit():
    events = []
    composer = _Composer(events)
    sink = Sink()

    report = await _agent(_Commit(events), composer=composer).handle_stimulus(
        _deadline(), sink, context=_Context(),
    )

    assert events == ["commit", "compose"]
    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    assert len(sink.values) == 1
    action = sink.values[0].actions[0]
    assert isinstance(action, d.Say)
    assert action.content == "compose-memory-ack"
    assert action.sound_content == "compose-memory-ack-sound"
    assert action.tone.value == "gentle"
    assert action.expression == d.ChangeExpression(expression_id="smile")
    assert len(composer.calls) == 1
    compose_call = composer.calls[0]
    assert compose_call["character_id"] == "luotianyi"
    assert compose_call["user_id"] == "u"
    assert compose_call["reply_topic"].startswith(_MEMORY_ACK_REPLY_TOPIC_PREFIX)
    assert compose_call["reply_topic"].endswith("我喜欢乌龙茶")
    assert compose_call["conversation_history"] == ""
    assert compose_call["memory_queries"] == ()
    assert compose_call["sing_attempts"] == ()
    assert compose_call["excluded_segments"] == set()


@pytest.mark.asyncio
async def test_write_failure_emits_no_promise_and_retains_pending():
    events = []
    sink = Sink()

    report = await _agent(_Commit(events, failure=RuntimeError("write failed"))).handle_stimulus(
        _deadline(), sink, context=_Context(),
    )

    assert events == ["commit"]
    assert sink.values == []
    assert report.request_status is d.HandlingRequestStatus.FAILED
    assert report.error_code is d.HandlingErrorCode.INTERNAL_ERROR
    assert report.retained_pending_stimulus_ids == ("m2", "m1")
    assert report.consumed_pending_stimulus_ids == ()
    assert report.retryable is False


@pytest.mark.asyncio
async def test_redelivery_reuses_memory_revision_without_duplicate_side_effect():
    events = []
    commit = _Commit(events)
    handler = _agent(commit, composer=_Composer(events))

    first = await handler.handle_stimulus(_deadline(), Sink(), context=_Context())
    second = await handler.handle_stimulus(_deadline(), Sink(), context=_Context())

    assert first.request_status is second.request_status is d.HandlingRequestStatus.COMPLETED
    assert len(commit._revisions) == 1
    assert commit.calls == [
        ("luotianyi", "u", "我喜欢乌龙茶"),
        ("luotianyi", "u", "我喜欢乌龙茶"),
    ]


@pytest.mark.asyncio
async def test_missing_user_identity_never_defaults_to_another_user():
    events = []
    commit = _Commit(events)
    sink = Sink()

    report = await _agent(commit).handle_stimulus(
        _deadline(user_id=None), sink, context=_Context(user_id=None),
    )

    assert commit.calls == []
    assert sink.values == []
    assert report.request_status is d.HandlingRequestStatus.FAILED
    assert report.error_code is d.HandlingErrorCode.INTERNAL_ERROR
    assert report.retained_pending_stimulus_ids == ("m2", "m1")
    assert report.consumed_pending_stimulus_ids == ()


def test_explicit_intent_config_extends_legacy_phrases_and_can_disable_detection():
    enabled = ExplicitMemoryIntentSkill({"enabled": True, "phrases": ["帮我记下"]})
    disabled = ExplicitMemoryIntentSkill({"enabled": False, "phrases": ["帮我记下"]})

    assert enabled.detect("帮我记下：我喜欢茉莉花茶") == "我喜欢茉莉花茶"
    assert enabled.detect("记一下我喜欢乌龙茶") == "我喜欢乌龙茶"
    assert disabled.detect("请记住我喜欢乌龙茶") is None


class _Writer:
    def __init__(self):
        self.calls = []

    async def commit_user_memory(self, **kwargs):
        self.calls.append(kwargs)
        return "vector-7", False


@pytest.mark.asyncio
async def test_commit_skill_wraps_memory_writer_and_preserves_identity():
    writer = _Writer()
    memory = type("Memory", (), {
        "memory_writer": writer,
        "vector_store": "vectors",
        "memory_store": "records",
        "owner_character_id": "miku",
    })()
    runtime = type("Runtime", (), {"mind": type("Mind", (), {"memory": memory})()})()

    revision = await IntentionalMemoryCommit(lambda character_id: runtime).commit(
        character_id="miku", user_id="user-2", content="喜欢抹茶",
    )

    assert revision.identifier == "vector-7"
    assert revision.committed is False
    assert writer.calls == [{
        "vector_store": "vectors",
        "memory_store": "records",
        "user_id": "user-2",
        "content": "喜欢抹茶",
        "owner_character_id": "miku",
    }]
