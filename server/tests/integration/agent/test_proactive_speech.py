"""主动刺激到话题提示和已分享记录的可观察行为。"""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from support.routing_support import Sink, request

import src.domain.agent as d
from src.agent import Agent
from src.agent.handlers.action.call import _completed
from src.agent.handlers.action.proactive import MarkTopicSharedHandler
from src.agent.handlers.action.router import ActionRouter
from src.agent.handlers.stimulus.proactive_speech import ProactiveSpeechHandler
from src.agent.handlers.stimulus.router import StimulusRouter
from src.domain.stage.due_events import DueEvent
from tests.integration.agent.test_topic_reply_pipeline import context, pipeline


class Events:
    def __init__(self, values):
        self.values = values
        self.shared = set()

    def list_due(self, **kwargs):
        return tuple(replace(e, is_notified=e.is_notified or e.event_id in self.shared) for e in self.values)

    def claim(self, event_id, **kwargs):
        self.shared.add(event_id)
        return True


def event(**overrides):
    return DueEvent(
        **{
            "event_id": "birthday",
            "trigger_key": "day_of_event",
            "reason": "birthday",
            "due_at": request().interaction.now,
            "character_id": "luotianyi",
            "is_personal": True,
            "target_user_id": "u",
            "is_notified": False,
            "title": "用户生日",
            "description": "今天二十五岁",
            **overrides,
        }
    )


async def generate(events, *, failure=False):
    skills, _, calls = pipeline(attempts=(), queries=())

    async def say(action, execution_context, outputs):
        if failure:
            raise RuntimeError("模拟回复执行失败")
        return _completed(action)

    agent = Agent(
        character_id="luotianyi",
        stimulus_router=StimulusRouter(
            [(d.StimulusKind.PROACTIVE_SPEECH_DUE, ProactiveSpeechHandler(skills=skills, events=events))]
        ),
        action_router=ActionRouter(
            [
                (d.ActionKind.SAY, SimpleNamespace(realize=say)),
                (d.ActionKind.MARK_TOPIC_SHARED, MarkTopicSharedHandler(events)),
            ]
        ),
    )
    req = request()
    req = replace(
        req,
        stimulus=d.ProactiveSpeechDue(
            stimulus_id="proactive",
            schema_version=1,
            occurred_at=req.interaction.now,
            source=d.StimulusSource.AGENT,
            target_character_ids=("luotianyi",),
            user_id="u",
            ephemeral=True,
            generation=1,
        ),
        interaction=replace(req.interaction, pending_stimuli=()),
    )
    ctx, sink = context(), Sink()
    report = await agent.handle_stimulus(req, sink, context=ctx)
    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    assert len(sink.values) == 1
    assert not events.shared
    result = await agent.realize_action_plan(
        sink.values[0],
        d.ExecutionContext(
            execution_id="e",
            interaction_id="i",
            current_interaction_revision=req.interaction.interaction_revision,
            cancellation=d.CancellationToken(),
            interaction_context=ctx,
        ),
        Sink(),
    )
    return calls["replier"], result


@pytest.mark.asyncio
async def test_event_becomes_topic_and_is_marked_only_after_successful_reply():
    events = Events([event()])
    prompt, result = await generate(events)
    assert "今天是用户生日" in prompt["reply_topic"]
    assert "今天二十五岁" in prompt["extra_knowledge"]
    assert events.shared == {"birthday"}
    assert result.status is d.ExecutionStatus.COMPLETED


@pytest.mark.asyncio
async def test_failed_reply_does_not_mark_event_shared():
    events = Events([event()])
    _, result = await generate(events, failure=True)
    assert result.status is d.ExecutionStatus.FAILED
    assert not events.shared


@pytest.mark.asyncio
@pytest.mark.parametrize("values", [[], [event(target_user_id="other")], [event(character_id="other")], [event(is_notified=True)]])
async def test_no_eligible_event_uses_context_without_disclosing_private_event(values):
    events = Events(values)
    prompt, result = await generate(events)
    assert "上下文" in prompt["reply_topic"]
    assert "以前讨论过歌曲" in str(prompt)
    assert "今天二十五岁" not in str(prompt)
    assert result.status is d.ExecutionStatus.COMPLETED
